"""Tests for FRIDAY Universe task envelope (/v1/task/execute), task status, and worker queue execution."""
from __future__ import annotations

import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AgentTask, VideoProject
from app.worker import claim_video_project, process_video_project, run_once

client = TestClient(app)


def test_universe_task_execute_validation_and_idempotency():
    task_id = "univ-task-" + uuid4().hex[:12]

    # 1. Sync mode rejected
    res_sync = client.post(
        "/v1/task/execute",
        json={
            "task_id": task_id,
            "target_agent": "vyralx",
            "action": "vyralx.discover.pexels",
            "requested_mode": "sync",
            "inputs": {"query": "cyberpunk"},
        },
    )
    assert res_sync.status_code == 422
    assert "asynchronous" in res_sync.text

    # 2. Target agent must be vyralx
    res_wrong_agent = client.post(
        "/v1/task/execute",
        json={
            "task_id": task_id,
            "target_agent": "sentinel",
            "action": "vyralx.discover.pexels",
            "requested_mode": "async",
            "inputs": {"query": "cyberpunk"},
        },
    )
    assert res_wrong_agent.status_code == 422

    # 3. Unsupported action rejected
    res_unsupported = client.post(
        "/v1/task/execute",
        json={
            "task_id": task_id,
            "target_agent": "vyralx",
            "action": "unsupported.action.here",
            "requested_mode": "async",
            "inputs": {},
        },
    )
    assert res_unsupported.status_code == 422

    # 4. Valid submission
    valid_payload = {
        "task_id": task_id,
        "target_agent": "vyralx",
        "action": "vyralx.discover.pexels",
        "requested_mode": "async",
        "inputs": {"query": "neon streets", "max_results": 5, "orientation": "portrait"},
    }
    res_ok = client.post("/v1/task/execute", json=valid_payload)
    assert res_ok.status_code == 202
    data = res_ok.json()
    assert data["task_id"] == task_id
    assert data["status"] == "PENDING"
    assert data["idempotent_replay"] is False

    # 5. Idempotent replay
    res_replay = client.post("/v1/task/execute", json=valid_payload)
    assert res_replay.status_code == 202
    assert res_replay.json()["idempotent_replay"] is True

    # 6. Conflict on different inputs with same task_id
    res_conflict = client.post(
        "/v1/task/execute",
        json={**valid_payload, "inputs": {"query": "different query"}},
    )
    assert res_conflict.status_code == 409

    # 7. GET status
    res_status = client.get(f"/v1/task/{task_id}")
    assert res_status.status_code == 200
    assert res_status.json()["task_id"] == task_id

    # 8. GET 404 for unknown task
    assert client.get("/v1/task/unknown-task-id").status_code == 404

    # Cleanup
    with SessionLocal() as db:
        t = db.query(AgentTask).filter(AgentTask.task_id == task_id).one_or_none()
        if t:
            db.delete(t)
            db.commit()


def test_api_v1_tasks_endpoints():
    task_id = "v1-api-task-" + uuid4().hex[:12]
    payload = {
        "task_id": task_id,
        "task_type": "discover.pexels",
        "input": {"query": "mountains", "orientation": "portrait"},
    }
    res = client.post("/api/v1/tasks", json=payload)
    assert res.status_code == 202
    assert res.json()["task_id"] == task_id

    res_get = client.get(f"/api/v1/tasks/{task_id}")
    assert res_get.status_code == 200
    assert res_get.json()["task_id"] == task_id

    assert client.get("/api/v1/tasks/nonexistent-task").status_code == 404

    with SessionLocal() as db:
        t = db.query(AgentTask).filter(AgentTask.task_id == task_id).one_or_none()
        if t:
            db.delete(t)
            db.commit()


def test_worker_run_once_and_agent_task_execution(monkeypatch: pytest.MonkeyPatch):
    task_id = "worker-task-" + uuid4().hex[:12]

    # Insert queued task
    with SessionLocal() as db:
        task = AgentTask(
            task_id=task_id,
            idempotency_key=f"taskid:{task_id}",
            task_type="discover.pexels",
            input_json=json.dumps({"query": "abstract"}),
            action="discover.pexels",
            status="queued",
            target_agent="vyralx",
        )
        db.add(task)
        db.commit()

    # Mock dispatch_agent_task
    monkeypatch.setattr(
        "app.worker.dispatch_agent_task",
        lambda task_type, payload, db: {"items": [{"id": 1, "title": "Abstract Video"}]},
    )

    try:
        # run_once should pick up and execute the task
        worked = run_once()
        assert worked is True

        with SessionLocal() as db:
            refreshed = db.query(AgentTask).filter(AgentTask.task_id == task_id).one()
            assert refreshed.status == "completed"
            assert "Abstract Video" in refreshed.result_json
    finally:
        with SessionLocal() as db:
            t = db.query(AgentTask).filter(AgentTask.task_id == task_id).one_or_none()
            if t:
                db.delete(t)
                db.commit()


def test_worker_claim_and_process_video_project(monkeypatch: pytest.MonkeyPatch):
    key = "proj-work-" + uuid4().hex[:10]
    with SessionLocal() as db:
        db.query(VideoProject).filter(VideoProject.status == "queued").delete()
        proj = VideoProject(
            project_key=key,
            topic="Test Work",
            video_format="shorts",
            status="queued",
        )
        db.add(proj)
        db.commit()
        proj_id = proj.id

    try:
        # Claim project
        with SessionLocal() as db:
            claimed_id = claim_video_project(db)
            assert claimed_id == proj_id

        with SessionLocal() as db:
            refreshed = db.get(VideoProject, proj_id)
            assert refreshed.status == "running"
            assert refreshed.attempts == 1

        # Process project with failure mock to exercise error handling
        def mock_failing_pipeline(pid, db):
            raise RuntimeError("Pipeline failed due to missing scene assets")

        monkeypatch.setattr("app.worker.execute_project_pipeline", mock_failing_pipeline)

        process_video_project(proj_id)

        with SessionLocal() as db:
            refreshed = db.get(VideoProject, proj_id)
            assert refreshed.status == "failed"
            assert "Pipeline failed due to missing scene assets" in refreshed.error
    finally:
        with SessionLocal() as db:
            p = db.get(VideoProject, proj_id)
            if p:
                db.delete(p)
                db.commit()
