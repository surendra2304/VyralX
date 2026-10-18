from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone

from app.main import app
from app.services.renderer import PRESETS
from app.services.rights import source_is_publishable
from app.config import Settings
from app.models import ContentPack, PublishJob, RenderJob, Source, VideoProject
from app.schemas import PublishRequest
import pytest

client = TestClient(app)

def test_health_and_dashboard():
    assert client.get("/health").json()["service"] == "vyralx"
    assert "VyralX Control Room" in client.get("/").text

def test_pending_publish_listing_exposes_final_description_and_tags():
    from app.database import SessionLocal
    from uuid import uuid4

    description = (
        "An original video description.\n\nStock footage credits:\n"
        "- Pexels creator (Pexels): https://www.pexels.com/video/123456/ "
        "— License: https://www.pexels.com/license/"
    )
    with SessionLocal() as db:
        job = PublishJob(
            asset_id=987654,
            render_job_id=987655,
            title="Operator review fixture " + uuid4().hex[:8],
            description=description,
            tags_json='["solar", "education"]',
            privacy_status="private",
            status="pending_approval",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

    try:
        response = client.get("/api/publish")
        assert response.status_code == 200
        row = next(item for item in response.json() if item["id"] == job_id)
        assert row["description"] == description
        assert row["tags"] == ["solar", "education"]
        assert row["status"] == "pending_approval"
    finally:
        with SessionLocal() as db:
            db.query(PublishJob).filter(PublishJob.id == job_id).delete()
            db.commit()


def test_publish_listing_includes_project_qa_snapshot():
    from uuid import uuid4
    from app.database import SessionLocal

    project_key = "qa-review-" + uuid4().hex[:12]
    with SessionLocal() as db:
        pack = ContentPack(
            topic="Test video topic",
            video_format="shorts",
            status="generated",
            pack_json=json.dumps({
                "production_qa": {
                    "status": "review_required",
                    "warning_count": 2,
                    "passed_count": 5,
                    "checks": [{"id": "caption_timing", "status": "warning"}],
                    "automatic_publish_approval": False,
                }
            }),
        )
        db.add(pack)
        db.flush()
        project = VideoProject(
            project_key=project_key,
            topic="Test video topic",
            video_format="shorts",
            target_seconds=45,
            status="completed",
            content_pack_id=pack.id,
        )
        db.add(project)
        db.flush()
        render = RenderJob(
            asset_id=987654,
            preset="shorts",
            status="completed",
            output_path="/not-downloaded-by-this-list-test.mp4",
            project_id=project.id,
            options_json="{}",
        )
        db.add(render)
        db.flush()
        job = PublishJob(
            asset_id=987654,
            render_job_id=render.id,
            title="Project QA review fixture " + uuid4().hex[:8],
            description="Review test description",
            status="pending_approval",
        )
        db.add(job)
        db.commit()
        job_id, render_id, project_id, pack_id = job.id, render.id, project.id, pack.id

    try:
        response = client.get("/api/publish")
        assert response.status_code == 200
        row = next(item for item in response.json() if item["id"] == job_id)
        assert row["production_qa"]["status"] == "review_required"
        assert row["production_qa"]["warning_count"] == 2
        assert row["production_qa"]["checks"][0]["id"] == "caption_timing"
    finally:
        with SessionLocal() as db:
            db.query(PublishJob).filter(PublishJob.id == job_id).delete()
            db.query(RenderJob).filter(RenderJob.id == render_id).delete()
            db.query(VideoProject).filter(VideoProject.id == project_id).delete()
            db.query(ContentPack).filter(ContentPack.id == pack_id).delete()
            db.commit()


def test_dashboard_requires_reviewing_final_publish_description():
    html = client.get("/").text
    assert "Review final description and stock attributions" in html
    assert "Review production QA" in html
    assert "I reviewed the final render, title, description and creator credits" in html
    assert "Download MP4 for review" in html


def test_publish_approval_refreshes_changed_attribution_before_queuing(tmp_path, monkeypatch):
    from uuid import uuid4

    from app import main as main_module
    from app.database import SessionLocal
    from app.models import Asset, RenderJob, Source

    monkeypatch.setattr(main_module.settings, "youtube_upload_enabled", True)
    render_path = tmp_path / "completed-render.mp4"
    render_path.write_bytes(b"test render placeholder")
    suffix = uuid4().hex[:10]
    with SessionLocal() as db:
        source = Source(
            title="Attribution review source",
            source_url=f"https://www.pexels.com/video/{suffix}/",
            platform="pexels",
            creator="Current Pexels Creator",
            license_name="Pexels Content License",
            permission_reference="https://www.pexels.com/license/",
            rights_verified=True,
            status="licensed",
        )
        db.add(source)
        db.flush()
        asset = Asset(
            source_id=source.id,
            title="Attribution review asset",
            file_path=str(tmp_path / "source.mp4"),
            rights_verified=True,
        )
        db.add(asset)
        db.flush()
        render = RenderJob(
            asset_id=asset.id,
            preset="shorts",
            status="completed",
            output_path=str(render_path),
            options_json="{}",
        )
        db.add(render)
        db.flush()
        job = PublishJob(
            asset_id=asset.id,
            render_job_id=render.id,
            title="Attribution review test",
            description="Original description without generated credits",
            tags_json='["education"]',
            privacy_status="private",
            status="pending_approval",
        )
        db.add(job)
        db.commit()
        source_id, asset_id, render_id, job_id = source.id, asset.id, render.id, job.id

    try:
        response = client.post(f"/api/publish/{job_id}/execute")
        assert response.status_code == 409
        assert "review the refreshed description" in response.json()["detail"].lower()
        with SessionLocal() as db:
            saved = db.get(PublishJob, job_id)
            assert saved is not None and saved.status == "pending_approval"
            assert "Current Pexels Creator" in saved.description
            assert "Stock attribution changed" in saved.error
    finally:
        with SessionLocal() as db:
            db.query(PublishJob).filter(PublishJob.id == job_id).delete()
            db.query(RenderJob).filter(RenderJob.id == render_id).delete()
            db.query(Asset).filter(Asset.id == asset_id).delete()
            db.query(Source).filter(Source.id == source_id).delete()
            db.commit()


def test_publish_metadata_obeys_youtube_title_description_and_tag_limits():
    with pytest.raises(ValueError, match="cannot contain"):
        PublishRequest(asset_id=1, render_job_id=1, title="Invalid <title>")

    with pytest.raises(ValueError, match="UTF-8 bytes"):
        PublishRequest(
            asset_id=1,
            render_job_id=1,
            title="Unicode description",
            description="é" * 2501,
        )

    exact_budget = PublishRequest(
        asset_id=1,
        render_job_id=1,
        title="Valid title",
        tags=["a" * 250, "b" * 249],
    )
    assert exact_budget.tags == ["a" * 250, "b" * 249]

    with pytest.raises(ValueError, match="500-character API limit"):
        PublishRequest(
            asset_id=1,
            render_job_id=1,
            title="Tag overflow",
            tags=["a" * 251, "b" * 249],
        )

    normalized = PublishRequest(
        asset_id=1,
        render_job_id=1,
        title="  Clean title  ",
        tags=[" solar ", "solar", "wind energy", ""],
    )
    assert normalized.title == "Clean title"
    assert normalized.tags == ["solar", "wind energy"]


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
