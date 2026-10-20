"""Tests for recover_interrupted_jobs across all durable queues, and the /ready health endpoint."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.main import app
from app.models import AgentTask, PublishJob, RenderJob, VideoProject
from app.worker import recover_interrupted_jobs, run_once

client = TestClient(app)


def test_ready_endpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("app.main.shutil.which", lambda bin: "/usr/bin/ffmpeg")

    # 1. worker_required=False -> ready 200
    monkeypatch.setattr(
        "app.main.settings",
        SimpleNamespace(
            worker_required=False,
            ffmpeg_bin="ffmpeg",
            data_dir=tmp_path,
        ),
    )
    res = client.get("/ready")
    assert res.status_code == 200
    assert res.json()["status"] == "ready"
    assert res.json()["worker"] == "not_required"

    # 2. worker_required=True with missing heartbeat -> degraded 503
    monkeypatch.setattr(
        "app.main.settings",
        SimpleNamespace(
            worker_required=True,
            ffmpeg_bin="ffmpeg",
            data_dir=tmp_path,
            worker_heartbeat_timeout_seconds=30,
        ),
    )
    res_degraded = client.get("/ready")
    assert res_degraded.status_code == 503
    assert res_degraded.json()["worker"] == "missing"

    # 3. worker_required=True with fresh heartbeat -> ready 200
    heartbeat_path = tmp_path / "worker-heartbeat.json"
    heartbeat_path.write_text(
        json.dumps({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "state": "idle",
        }),
        encoding="utf-8",
    )
    res_healthy = client.get("/ready")
    assert res_healthy.status_code == 200
    assert res_healthy.json()["worker"] == "healthy"


def test_recover_interrupted_jobs_all_queues():
    with SessionLocal() as db:
        # 1. Running render job
        render = RenderJob(
            asset_id=1,
            preset="shorts",
            status="running",
            output_path="",
            options_json="{}",
        )
        # 2. Running agent task
        task = AgentTask(
            task_id="recov-task-" + uuid4().hex[:10],
            task_type="discover.pexels",
            status="running",
            action="discover.pexels",
        )
        # 3. Running video project
        proj = VideoProject(
            project_key="recov-proj-" + uuid4().hex[:10],
            topic="Recover topic",
            video_format="shorts",
            status="running",
        )
        db.add_all([render, task, proj])
        db.commit()
        render_id = render.id
        task_id = task.id
        proj_id = proj.id

    try:
        counts = recover_interrupted_jobs()
        assert counts["renders"] >= 1
        assert counts["agent_tasks"] >= 1
        assert counts["projects"] >= 1

        with SessionLocal() as db:
            ref_render = db.get(RenderJob, render_id)
            assert ref_render.status == "failed"
            assert "Worker restarted during render" in ref_render.error

            ref_task = db.get(AgentTask, task_id)
            assert ref_task.status == "failed"
            assert "Worker restarted during task execution" in ref_task.error

            ref_proj = db.get(VideoProject, proj_id)
            assert ref_proj.status == "failed"
            assert "Worker restarted while creating this project" in ref_proj.error
    finally:
        with SessionLocal() as db:
            r = db.get(RenderJob, render_id)
            t = db.get(AgentTask, task_id)
            p = db.get(VideoProject, proj_id)
            if r:
                db.delete(r)
            if t:
                db.delete(t)
            if p:
                db.delete(p)
            db.commit()


def test_run_once_cycles_through_queues(monkeypatch: pytest.MonkeyPatch):
    """Test run_once rotating across render, project, and publish queue handlers."""
    # 1. Empty queues -> returns False
    with SessionLocal() as db:
        db.query(AgentTask).filter(AgentTask.status == "queued").delete()
        db.query(VideoProject).filter(VideoProject.status == "queued").delete()
        db.query(RenderJob).filter(RenderJob.status == "queued").delete()
        db.query(PublishJob).filter(PublishJob.status == "queued").delete()
        db.commit()

    assert run_once() is False

    # 2. Add queued render job
    with SessionLocal() as db:
        r = RenderJob(
            asset_id=1,
            preset="shorts",
            status="queued",
            output_path="",
            options_json="{}",
        )
        db.add(r)
        db.commit()
        r_id = r.id

    called = []
    monkeypatch.setattr("app.worker.process_render_job", lambda jid: called.append(jid))

    try:
        # Run until the render queue is hit
        found = False
        for _ in range(4):
            if run_once():
                found = True
                break
        assert found is True
        assert r_id in called
    finally:
        with SessionLocal() as db:
            item = db.get(RenderJob, r_id)
            if item:
                db.delete(item)
                db.commit()
