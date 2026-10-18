from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from app.main import app
from app.services.renderer import PRESETS
from app.services.rights import source_is_publishable
from app.config import Settings
from app.models import Source
from app.schemas import PublishRequest
import pytest

client = TestClient(app)

def test_health_and_dashboard():
    assert client.get("/health").json()["service"] == "vyralx"
    assert "VyralX Control Room" in client.get("/").text

def test_render_presets_are_defined():
    assert PRESETS["shorts"] == (1080, 1920)
    assert PRESETS["long"] == (1920, 1080)
    assert PRESETS["square"] == (1080, 1080)

def test_rights_gate_fails_closed():
    assert not source_is_publishable(None)
    assert not source_is_publishable(Source(title="unverified", rights_verified=False))
    assert not source_is_publishable(Source(title="no evidence", rights_verified=True))
    assert source_is_publishable(Source(title="licensed", rights_verified=True, license_name="CC BY 4.0", permission_reference="https://creativecommons.org/licenses/by/4.0/"))

def test_invalid_source_rejected_without_auth_in_dev():
    response = client.post("/api/sources", json={"title": ""})
    assert response.status_code == 422


def test_discovery_errors_do_not_leak_provider_secrets(monkeypatch):
    from app import main as main_module

    def fail_discovery(*args, **kwargs):
        raise RuntimeError("upstream URL contains key=do-not-leak")

    monkeypatch.setattr(main_module, "discover_youtube_videos", fail_discovery)
    response = client.post("/api/discover", json={"query": "test"})
    assert response.status_code == 502
    assert "do-not-leak" not in response.text
    assert "check server logs" in response.text


def test_production_rejects_default_api_key():
    with pytest.raises(ValueError, match="unique API_KEY"):
        Settings(app_env="production")


def test_publish_request_binds_render_and_uses_configured_privacy_default():
    request = PublishRequest(asset_id=4, render_job_id=12, title="Demo Short")
    assert request.render_job_id == 12
    assert request.privacy_status is None


@pytest.mark.parametrize(
    "payload",
    [
        {"query": ""},
        {"query": "trend", "max_results": 26},
        {"query": "trend", "order": "popular"},
    ],
)
def test_discovery_rejects_invalid_request(payload):
    response = client.post("/api/discover", json=payload)
    assert response.status_code == 422


def test_publish_schedule_requires_timezone_and_future_time():
    with pytest.raises(ValueError, match="timezone"):
        PublishRequest(asset_id=1, render_job_id=1, title="Demo", scheduled_at="2030-01-01T10:00:00")
    scheduled = datetime.now(timezone.utc) + timedelta(days=1)
    request = PublishRequest(
        asset_id=1,
        render_job_id=1,
        title="Demo",
        scheduled_at=scheduled.isoformat(),
    )
    assert request.scheduled_at is not None
    assert request.scheduled_at.utcoffset() == timedelta(0)


def test_canonical_friday_task_contract_and_idempotent_replay(monkeypatch):
    from uuid import uuid4

    from app.database import SessionLocal
    from app.models import AgentTask

    task_id = "test-friday-" + uuid4().hex
    idempotency_key = "test-idem-" + uuid4().hex
    payload = {
        "task_id": task_id,
        "trace_id": "trace-test-001",
        "parent_task_id": "parent-test-001",
        "request_id": "request-test-001",
        "actor": "friday",
        "capability": "content.generate",
        "objective": "Create an original short about solar energy",
        "inputs": {"topic": "How solar energy works", "video_format": "shorts"},
        "trust_level": "operator_confirmed",
        "authorization_context": {"scope": "video-create", "api_key": "must-not-be-persisted"},
        "idempotency_key": idempotency_key,
        "requested_mode": "async",
        "source_agent": "friday",
        "target_agent": "vyralx",
        "action": "vyralx.content.generate",
        "payload": {"topic": "How solar energy works", "video_format": "shorts"},
        "priority": "high",
    }
    try:
        first = client.post("/v1/task/execute", json=payload)
        assert first.status_code == 202
        first_data = first.json()
        assert first_data["task_id"] == task_id
        assert first_data["target_agent"] == "vyralx"
        assert first_data["status"] == "PENDING"
        assert first_data["trace_id"] == "trace-test-001"

        sync_payload = {**payload, "task_id": task_id + "-sync", "requested_mode": "sync"}
        assert client.post("/v1/task/execute", json=sync_payload).status_code == 422

        replay = client.post("/v1/task/execute", json=payload)
        assert replay.status_code == 202
        assert replay.json()["idempotent_replay"] is True

        changed = {
            **payload,
            "inputs": {"topic": "different topic"},
            "payload": {"topic": "different topic"},
        }
        conflict = client.post("/v1/task/execute", json=changed)
        assert conflict.status_code == 409

        polled = client.get("/v1/task/" + task_id)
        assert polled.status_code == 200
        assert polled.json()["status"] == "PENDING"

        with SessionLocal() as db:
            task = db.query(AgentTask).filter(AgentTask.task_id == task_id).one()
            assert task.trace_id == "trace-test-001"
            assert "must-not-be-persisted" not in task.authorization_context_json
            assert "[REDACTED]" in task.authorization_context_json
            task_row_id = task.id

        # Exercise the worker path without calling any external service.
        from app import worker
        monkeypatch.setattr(worker, "dispatch_agent_task", lambda task_type, task_input, db: {"asset_id": 42, "status": "queued"})
        worker.process_agent_task(task_row_id)

        completed = client.get("/v1/task/" + task_id)
        assert completed.status_code == 200
        completed_data = completed.json()
        assert completed_data["status"] == "SUCCESS"
        assert completed_data["final_state"] == "SUCCESS"
        receipt = completed_data["receipt"]
        assert receipt["requested_action"] == "vyralx.content.generate"
        assert receipt["target"] == "vyralx"
        assert receipt["authorization_decision"] == "AUTHORIZED"
        assert receipt["verification_evidence"]["task_row_id"] == task_row_id

        changed_action = {**payload, "action": "vyralx.discover.youtube"}
        action_conflict = client.post("/v1/task/execute", json=changed_action)
        assert action_conflict.status_code == 409
    finally:
        with SessionLocal() as db:
            db.query(AgentTask).filter(AgentTask.task_id == task_id).delete()
            db.commit()


def test_video_project_api_is_idempotent_and_requires_license_confirmation():
    from uuid import uuid4

    from app.database import SessionLocal
    from app.models import VideoProject

    key = "test-project-" + uuid4().hex[:12]
    payload = {
        "project_key": key,
        "topic": "How wind power works",
        "video_format": "shorts",
        "target_seconds": 30,
        "scene_count": 3,
        "confirm_pexels_license": True,
        "use_voiceover": True,
    }
    try:
        denied = client.post("/api/projects", json={**payload, "confirm_pexels_license": False})
        assert denied.status_code == 403
        created = client.post("/api/projects", json=payload)
        assert created.status_code == 202
        result = created.json()
        assert result["status"] == "queued"
        assert result["project_key"] == key
        replay = client.post("/api/projects", json=payload)
        assert replay.status_code == 202
        assert replay.json()["idempotent_replay"] is True
        conflict = client.post("/api/projects", json={**payload, "topic": "Different topic"})
        assert conflict.status_code == 409
        polled = client.get("/api/projects/" + str(result["project_id"]))
        assert polled.status_code == 200
        assert polled.json()["status"] == "queued"
    finally:
        with SessionLocal() as db:
            db.query(VideoProject).filter(VideoProject.project_key == key).delete()
            db.commit()


def test_project_captions_are_persisted_and_download_requires_completed_project():
    from uuid import uuid4

    from app.config import get_settings
    from app.database import SessionLocal
    from app.models import VideoProject

    key = "caption-download-" + uuid4().hex[:12]
    settings = get_settings()
    caption_file = None
    project_id = None
    try:
        with SessionLocal() as db:
            project = VideoProject(
                project_key=key,
                topic="Caption persistence test",
                status="completed",
                attempts=1,
                confirm_pexels_license=True,
            )
            db.add(project)
            db.commit()
            db.refresh(project)
            project_id = project.id
        caption_file = settings.data_dir / "subtitles" / f"project-{project_id}-attempt-1.srt"
        caption_file.parent.mkdir(parents=True, exist_ok=True)
        caption_file.write_text(
            "1\n00:00:00,000 --> 00:00:02,000\nReview this caption.\n",
            encoding="utf-8",
        )

        response = client.get(f"/api/projects/{project_id}/captions")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/x-subrip")
        assert "Review this caption." in response.text
        project_summary = client.get(f"/api/projects/{project_id}").json()
        assert project_summary["captions_download_path"] == f"/api/projects/{project_id}/captions"

        with SessionLocal() as db:
            project = db.get(VideoProject, project_id)
            project.status = "failed"
            db.commit()
        assert client.get(f"/api/projects/{project_id}/captions").status_code == 404
    finally:
        if caption_file is not None:
            caption_file.unlink(missing_ok=True)
        if project_id is not None:
            with SessionLocal() as db:
                db.query(VideoProject).filter(VideoProject.id == project_id).delete()
                db.commit()


def test_integration_configuration_endpoint_never_exposes_credentials():
    response = client.get("/api/integrations")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "configuration_only_not_live_connectivity"
    assert {"inference", "pexels", "youtube_data_api", "youtube_upload", "tts", "intelx", "memora", "sentinel", "worker", "media_tools"} <= set(data["providers"])
    assert "api_key" not in str(data).lower()
    assert "secret_value" not in str(data).lower()
