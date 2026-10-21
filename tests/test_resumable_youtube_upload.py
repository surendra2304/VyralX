"""Comprehensive tests for resumable YouTube uploads, scheduled/unlisted publishing, and Safety Invariant 1."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from requests.exceptions import RequestException

from app.database import SessionLocal
from app.models import Asset, PublishJob, RenderJob, Source
from app.services import youtube as yt
from app.worker import process_publish_job


def _make_dummy_video(tmp_path: Path, filename: str = "video.mp4", size: int = 2048) -> Path:
    path = tmp_path / filename
    path.write_bytes(b"A" * size)
    return path


def test_write_load_clear_session_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    token_file = tmp_path / "secrets" / "token.json"
    monkeypatch.setattr(yt, "get_settings", lambda: SimpleNamespace(youtube_token_file=token_file))

    session_uri = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=sess123"
    file_sha = "a" * 64
    meta_sha = "b" * 64
    media_path = str(tmp_path / "render.mp4")

    # Invalid upload_attempt: bool, 0, or negative
    assert not yt.write_upload_session_checkpoint(
        10, True, session_uri=session_uri, file_path=media_path,
        file_size=1000, file_sha256=file_sha, metadata_sha256=meta_sha, confirmed_offset=0,
    )
    assert not yt.write_upload_session_checkpoint(
        10, 0, session_uri=session_uri, file_path=media_path,
        file_size=1000, file_sha256=file_sha, metadata_sha256=meta_sha, confirmed_offset=0,
    )

    # Invalid session_uri
    assert not yt.write_upload_session_checkpoint(
        10, 1, session_uri="http://insecure.com/upload", file_path=media_path,
        file_size=1000, file_sha256=file_sha, metadata_sha256=meta_sha, confirmed_offset=0,
    )
    assert not yt.write_upload_session_checkpoint(
        10, 1, session_uri="https://www.googleapis.com/other/path?upload_id=1", file_path=media_path,
        file_size=1000, file_sha256=file_sha, metadata_sha256=meta_sha, confirmed_offset=0,
    )

    # Invalid hash length
    assert not yt.write_upload_session_checkpoint(
        10, 1, session_uri=session_uri, file_path=media_path,
        file_size=1000, file_sha256="short", metadata_sha256=meta_sha, confirmed_offset=0,
    )

    # Invalid offset
    assert not yt.write_upload_session_checkpoint(
        10, 1, session_uri=session_uri, file_path=media_path,
        file_size=1000, file_sha256=file_sha, metadata_sha256=meta_sha, confirmed_offset=2000,
    )

    # Valid write
    assert yt.write_upload_session_checkpoint(
        10, 1, session_uri=session_uri, file_path=media_path,
        file_size=1000, file_sha256=file_sha, metadata_sha256=meta_sha, confirmed_offset=500,
    )

    assert yt.upload_session_checkpoint_exists(10)

    # Correct attempt load
    loaded = yt.load_upload_session_checkpoint(10, 1)
    assert loaded is not None
    assert loaded["session_uri"] == session_uri
    assert loaded["confirmed_offset"] == 500
    assert loaded["file_size"] == 1000

    # Attempt mismatch returns None
    assert yt.load_upload_session_checkpoint(10, 2) is None
    assert yt.load_upload_session_checkpoint(10, -1) is None
    assert yt.load_upload_session_checkpoint(10, True) is None  # type: ignore

    # Clear checkpoint
    yt.clear_upload_session_checkpoint(10)
    assert not yt.upload_session_checkpoint_exists(10)
    assert yt.load_upload_session_checkpoint(10, 1) is None


def test_scheduled_publishing_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    token_file = tmp_path / "secrets" / "token.json"
    monkeypatch.setattr(yt, "get_settings", lambda: SimpleNamespace(
        youtube_token_file=token_file,
        youtube_upload_enabled=True,
    ))
    video = _make_dummy_video(tmp_path)

    # scheduled_at with non-private status must fail
    with pytest.raises(ValueError, match="Scheduled publishing must start with privacy_status=private"):
        yt.upload_video(
            str(video), title="Title", description="", tags=[],
            privacy_status="unlisted", category_id="22",
            scheduled_at="2026-12-01T12:00:00Z",
        )

    with pytest.raises(ValueError, match="Scheduled publishing must start with privacy_status=private"):
        yt.upload_video(
            str(video), title="Title", description="", tags=[],
            privacy_status="public", category_id="22",
            scheduled_at="2026-12-01T12:00:00Z",
        )

    # scheduled_at with invalid ISO format
    with pytest.raises(ValueError, match="scheduled_at must be an ISO-8601 timestamp"):
        yt.upload_video(
            str(video), title="Title", description="", tags=[],
            privacy_status="private", category_id="22",
            scheduled_at="tomorrow at noon",
        )

    # scheduled_at without timezone
    with pytest.raises(ValueError, match="scheduled_at must include a timezone"):
        yt.upload_video(
            str(video), title="Title", description="", tags=[],
            privacy_status="private", category_id="22",
            scheduled_at="2026-12-01T12:00:00",
        )

    # scheduled_at in the past
    past_iso = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="scheduled_at must be in the future"):
        yt.upload_video(
            str(video), title="Title", description="", tags=[],
            privacy_status="private", category_id="22",
            scheduled_at=past_iso,
        )


def test_scheduled_publishing_payload_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    token_file = tmp_path / "secrets" / "token.json"
    monkeypatch.setattr(yt, "get_settings", lambda: SimpleNamespace(
        youtube_token_file=token_file,
        youtube_upload_enabled=True,
    ))
    video = _make_dummy_video(tmp_path, size=100)

    # Mock credentials
    fake_creds = MagicMock()
    fake_creds.valid = True
    monkeypatch.setattr(yt, "youtube_credentials", lambda: fake_creds)

    posted_bodies = []

    class MockInitResponse:
        status_code = 200
        headers = {
            "Location": "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=mock1",
        }

    class MockUploadResponse:
        status_code = 200

        def json(self):
            return {"id": "v_scheduled_123"}

    class MockSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            posted_bodies.append(kwargs.get("json"))
            return MockInitResponse()

        def put(self, url, **kwargs):
            return MockUploadResponse()

    monkeypatch.setattr(yt, "AuthorizedSession", lambda creds: MockSession())

    future_time = datetime.now(timezone.utc) + timedelta(days=5)
    future_iso = future_time.isoformat()

    video_id = yt.upload_video(
        str(video),
        title="Scheduled Video",
        description="Description",
        tags=["short", "scheduled"],
        privacy_status="private",
        category_id="22",
        scheduled_at=future_iso,
        publish_job_id=99,
        upload_attempt=1,
    )

    assert video_id == "v_scheduled_123"
    assert len(posted_bodies) == 1
    sent_body = posted_bodies[0]
    assert sent_body["status"]["privacyStatus"] == "private"
    assert sent_body["status"]["publishAt"].endswith("Z")
    assert yt.load_upload_success_checkpoint(99, 1) == "v_scheduled_123"
    yt.clear_upload_success_checkpoint(99)
    yt.clear_upload_session_checkpoint(99)


def test_unlisted_publication_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    token_file = tmp_path / "secrets" / "token.json"
    monkeypatch.setattr(yt, "get_settings", lambda: SimpleNamespace(
        youtube_token_file=token_file,
        youtube_upload_enabled=True,
    ))
    video = _make_dummy_video(tmp_path, size=100)

    fake_creds = MagicMock()
    fake_creds.valid = True
    monkeypatch.setattr(yt, "youtube_credentials", lambda: fake_creds)

    posted_bodies = []

    class MockInitResponse:
        status_code = 200
        headers = {
            "Location": "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=mock_unlisted",
        }

    class MockUploadResponse:
        status_code = 200

        def json(self):
            return {"id": "v_unlisted_456"}

    class MockSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            posted_bodies.append(kwargs.get("json"))
            return MockInitResponse()

        def put(self, url, **kwargs):
            return MockUploadResponse()

    monkeypatch.setattr(yt, "AuthorizedSession", lambda creds: MockSession())

    video_id = yt.upload_video(
        str(video),
        title="Unlisted Preview",
        description="Private unlisted link for review",
        tags=["unlisted"],
        privacy_status="unlisted",
        category_id="22",
    )

    assert video_id == "v_unlisted_456"
    assert len(posted_bodies) == 1
    assert posted_bodies[0]["status"]["privacyStatus"] == "unlisted"
    assert "publishAt" not in posted_bodies[0]["status"]


def test_youtube_credentials_refresh_retry_and_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    token_file = tmp_path / "secrets" / "youtube-token.json"
    token_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(yt, "get_settings", lambda: SimpleNamespace(youtube_token_file=token_file))

    # 1. Missing token file
    with pytest.raises(RuntimeError, match="YouTube OAuth token file is missing"):
        yt.youtube_credentials()

    # 2. Corrupt JSON
    token_file.write_text("invalid json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="YouTube OAuth token file is unreadable or invalid JSON"):
        yt.youtube_credentials()

    # 3. Expired token with retry logic: first fails, second succeeds
    token_data = {
        "token": "old_token",
        "refresh_token": "valid_refresh",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "test_client",
        "client_secret": "test_secret",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
    }
    token_file.write_text(json.dumps(token_data), encoding="utf-8")

    fake_creds = MagicMock()
    fake_creds.expired = True
    fake_creds.refresh_token = "valid_refresh"
    fake_creds.valid = True
    fake_creds.to_json.return_value = json.dumps({"token": "new_token"})

    refresh_attempts = 0

    def mock_refresh(req):
        nonlocal refresh_attempts
        refresh_attempts += 1
        if refresh_attempts == 1:
            raise ConnectionError("Network glitch on first refresh attempt")
        # second attempt succeeds
        fake_creds.expired = False
        fake_creds.token = "new_token"

    fake_creds.refresh.side_effect = mock_refresh
    monkeypatch.setattr(yt.Credentials, "from_authorized_user_info", lambda data: fake_creds)

    creds = yt.youtube_credentials()
    assert creds.valid is True
    assert refresh_attempts == 2

    # 4. Refresh fails both attempts
    refresh_attempts = 0

    def mock_refresh_always_fail(req):
        nonlocal refresh_attempts
        refresh_attempts += 1
        raise ConnectionResetError("Server unavailable")

    fake_creds.expired = True
    fake_creds.refresh.side_effect = mock_refresh_always_fail
    with pytest.raises(RuntimeError, match="YouTube OAuth refresh failed"):
        yt.youtube_credentials()
    assert refresh_attempts == 2


def test_probe_upload_session_responses():
    session = MagicMock()

    # Case 1: 200 with video id
    res200 = MagicMock()
    res200.status_code = 200
    res200.json.return_value = {"id": "vid_finished_123"}
    session.put.return_value = res200
    offset, vid = yt._probe_upload_session(session, "https://www.googleapis.com/upload/youtube/v3/videos?id=1", 5000)
    assert offset == 5000
    assert vid == "vid_finished_123"

    # Case 2: 200 with missing video id -> UploadOutcomeUnknown
    res200_bad = MagicMock()
    res200_bad.status_code = 200
    res200_bad.json.return_value = {}
    session.put.return_value = res200_bad
    with pytest.raises(yt.UploadOutcomeUnknown, match="without a usable video ID"):
        yt._probe_upload_session(session, "https://www.googleapis.com/upload/youtube/v3/videos?id=1", 5000)

    # Case 3: 308 with Range 0-2047 -> offset 2048
    res308 = MagicMock()
    res308.status_code = 308
    res308.headers = {"Range": "bytes=0-2047"}
    session.put.return_value = res308
    offset, vid = yt._probe_upload_session(session, "https://www.googleapis.com/upload/youtube/v3/videos?id=1", 5000)
    assert offset == 2048
    assert vid is None

    # Case 4: 308 with Range exceeding file size -> UploadOutcomeUnknown
    res308_overflow = MagicMock()
    res308_overflow.status_code = 308
    res308_overflow.headers = {"Range": "bytes=0-9999"}
    session.put.return_value = res308_overflow
    with pytest.raises(yt.UploadOutcomeUnknown, match="exceeded the source file size"):
        yt._probe_upload_session(session, "https://www.googleapis.com/upload/youtube/v3/videos?id=1", 5000)

    # Case 5: 404 Session Expired -> _UploadSessionExpired
    res404 = MagicMock()
    res404.status_code = 404
    session.put.return_value = res404
    with pytest.raises(yt._UploadSessionExpired):
        yt._probe_upload_session(session, "https://www.googleapis.com/upload/youtube/v3/videos?id=1", 5000)

    # Case 6: Network exception -> UploadOutcomeUnknown
    session.put.side_effect = RequestException("Timeout")
    with pytest.raises(yt.UploadOutcomeUnknown, match="Could not query the saved YouTube upload session"):
        yt._probe_upload_session(session, "https://www.googleapis.com/upload/youtube/v3/videos?id=1", 5000)


def test_safety_invariant_1_never_blindly_retry_and_uncertain_on_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Verify Safety Invariant 1:
    Interrupted uploads enter 'resumable' only if session checkpoint exactly matches file size/hash.
    If corrupted or mismatched, enters 'uncertain' state to prevent duplicate publication.
    """
    token_file = tmp_path / "secrets" / "token.json"
    settings_obj = SimpleNamespace(
        youtube_token_file=token_file,
        youtube_upload_enabled=True,
        sentinel_required_for_publish=False,
        sentinel_policy_path="/v1/security/audit",
        ffmpeg_bin="ffmpeg",
        youtube_category_id="22",
    )
    monkeypatch.setattr(yt, "get_settings", lambda: settings_obj)
    monkeypatch.setattr("app.worker.get_settings", lambda: settings_obj)

    video = _make_dummy_video(tmp_path, "invariant_test.mp4", size=4096)

    with SessionLocal() as db:
        source = Source(
            title="Inv1 Test Source",
            platform="manual",
            license_name="Standard Commercial License",
            permission_reference="INV-TEST-REF-001",
            rights_verified=True,
        )
        db.add(source)
        db.flush()

        asset = Asset(
            source_id=source.id,
            title="Inv1 Test Asset",
            file_path=str(video),
            rights_verified=True,
        )
        db.add(asset)
        db.flush()

        render = RenderJob(
            asset_id=asset.id,
            preset="shorts",
            status="completed",
            output_path=str(video),
            options_json="{}",
        )
        db.add(render)
        db.flush()

        publish = PublishJob(
            asset_id=asset.id,
            render_job_id=render.id,
            title="Invariant 1 Test Video",
            description="Pre-approved clean description",
            status="uploading",
            attempts=1,
            privacy_status="private",
            tags_json="[]",
            approved_at=datetime.now(timezone.utc),
        )
        db.add(publish)
        db.commit()

        job_id = publish.id

    try:
        session_uri = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=inv1"
        file_sha = yt._file_sha256(video)
        meta_sha = yt._metadata_sha256({"snippet": {"title": "Invariant 1 Test Video"}})

        # Fail upload with UploadOutcomeUnknown after recording a valid attempt checkpoint
        def mock_failing_upload(*args, **kwargs):
            attempt = kwargs.get("upload_attempt") or 1
            yt.write_upload_session_checkpoint(
                job_id,
                attempt,
                session_uri=session_uri,
                file_path=str(video),
                file_size=4096,
                file_sha256=file_sha,
                metadata_sha256=meta_sha,
                confirmed_offset=1024,
            )
            raise yt.UploadOutcomeUnknown("Connection reset by peer after 1024 bytes sent")

        monkeypatch.setattr("app.worker.upload_video", mock_failing_upload)

        process_publish_job(job_id)

        with SessionLocal() as db:
            refreshed = db.get(PublishJob, job_id)
            assert refreshed is not None
            # Matching checkpoint -> status set to 'resumable'
            assert refreshed.status == "resumable"
            assert "paused with a saved YouTube session" in refreshed.error

        # Case B: The render file changed -> enters 'uncertain' state
        video.write_bytes(b"B" * 5000)

        process_publish_job(job_id)

        with SessionLocal() as db:
            refreshed = db.get(PublishJob, job_id)
            assert refreshed is not None
            # Mismatched render -> status enters 'uncertain'
            assert refreshed.status == "uncertain"
            assert "Connection reset by peer" in refreshed.error

    finally:
        yt.clear_upload_success_checkpoint(job_id)
        yt.clear_upload_session_checkpoint(job_id)
        with SessionLocal() as db:
            p = db.get(PublishJob, job_id)
            if p:
                r = db.get(RenderJob, p.render_job_id)
                a = db.get(Asset, p.asset_id)
                s = db.get(Source, a.source_id) if a and a.source_id else None
                db.delete(p)
                if r:
                    db.delete(r)
                if a:
                    db.delete(a)
                if s:
                    db.delete(s)
                db.commit()


def test_resumable_upload_network_drop_then_probe_confirms_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    token_file = tmp_path / "secrets" / "token.json"
    monkeypatch.setattr(yt, "get_settings", lambda: SimpleNamespace(
        youtube_token_file=token_file,
        youtube_upload_enabled=True,
    ))
    video = _make_dummy_video(tmp_path, "probe_drop.mp4", size=100)

    fake_creds = MagicMock()
    fake_creds.valid = True
    monkeypatch.setattr(yt, "youtube_credentials", lambda: fake_creds)

    class MockInitResponse:
        status_code = 200
        headers = {
            "Location": "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=mock_probe_drop",
        }

    class MockSession:
        def __init__(self):
            self.put_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            return MockInitResponse()

        def put(self, url, **kwargs):
            self.put_calls += 1
            if self.put_calls == 1:
                # First chunk put drops connection
                raise RequestException("Network connection dropped during chunk write")
            # Second put is the probe query (Content-Range: bytes */100)
            res = MagicMock()
            res.status_code = 200
            res.json.return_value = {"id": "vid_recovered_after_drop"}
            return res

    mock_session = MockSession()
    monkeypatch.setattr(yt, "AuthorizedSession", lambda creds: mock_session)

    vid = yt.upload_video(
        str(video),
        title="Probe Drop Test",
        description="Testing recovery after drop",
        tags=["probe"],
        privacy_status="private",
        category_id="22",
        publish_job_id=88,
        upload_attempt=1,
    )

    assert vid == "vid_recovered_after_drop"
    assert yt.load_upload_success_checkpoint(88, 1) == "vid_recovered_after_drop"
    yt.clear_upload_success_checkpoint(88)
    yt.clear_upload_session_checkpoint(88)


def test_resumable_upload_session_expired_and_renewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    token_file = tmp_path / "secrets" / "token.json"
    monkeypatch.setattr(yt, "get_settings", lambda: SimpleNamespace(
        youtube_token_file=token_file,
        youtube_upload_enabled=True,
    ))
    video = _make_dummy_video(tmp_path, "renewed.mp4", size=100)

    fake_creds = MagicMock()
    fake_creds.valid = True
    monkeypatch.setattr(yt, "youtube_credentials", lambda: fake_creds)

    sessions_started = 0

    class MockSession:
        def __init__(self):
            self.put_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            nonlocal sessions_started
            sessions_started += 1
            res = MagicMock()
            res.status_code = 200
            res.headers = {
                "Location": f"https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=renew_{sessions_started}",
            }
            return res

        def put(self, url, **kwargs):
            self.put_calls += 1
            if self.put_calls == 1:
                # Session expired on first chunk upload
                res = MagicMock()
                res.status_code = 404
                return res
            # Second chunk upload on renewed session succeeds
            res = MagicMock()
            res.status_code = 200
            res.json.return_value = {"id": "vid_renewed_success"}
            return res

    mock_session = MockSession()
    monkeypatch.setattr(yt, "AuthorizedSession", lambda creds: mock_session)

    vid = yt.upload_video(
        str(video),
        title="Renew Test",
        description="Testing session renewal",
        tags=["renew"],
        privacy_status="private",
        category_id="22",
        publish_job_id=89,
        upload_attempt=1,
    )

    assert vid == "vid_renewed_success"
    assert sessions_started == 2
    yt.clear_upload_success_checkpoint(89)
    yt.clear_upload_session_checkpoint(89)


def test_resumable_upload_stall_limit_exceeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    token_file = tmp_path / "secrets" / "token.json"
    monkeypatch.setattr(yt, "get_settings", lambda: SimpleNamespace(
        youtube_token_file=token_file,
        youtube_upload_enabled=True,
    ))
    video = _make_dummy_video(tmp_path, "stall.mp4", size=100)

    fake_creds = MagicMock()
    fake_creds.valid = True
    monkeypatch.setattr(yt, "youtube_credentials", lambda: fake_creds)

    class MockSession:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def post(self, url, **kwargs):
            res = MagicMock()
            res.status_code = 200
            res.headers = {
                "Location": "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&upload_id=stall_sess",
            }
            return res

        def put(self, url, **kwargs):
            # Check if this is a probe
            content_range = kwargs.get("headers", {}).get("Content-Range", "")
            if content_range.startswith("bytes */"):
                # Probe says offset is still 0
                res = MagicMock()
                res.status_code = 308
                res.headers = {"Range": "bytes=0--1"}  # offset 0
                return res
            # Chunk upload raises connection error
            raise RequestException("Network connection failed repeatedly")

    monkeypatch.setattr(yt, "AuthorizedSession", lambda creds: MockSession())

    # Probe should return offset 0, so remote_offset == offset stalls
    monkeypatch.setattr(yt, "_resume_offset_from_response", lambda res, size: 0)

    with pytest.raises(yt.UploadOutcomeUnknown, match="did not advance the resumable upload"):
        yt.upload_video(
            str(video),
            title="Stall Test",
            description="Testing stall limit",
            tags=["stall"],
            privacy_status="private",
            category_id="22",
            publish_job_id=90,
            upload_attempt=1,
        )

    yt.clear_upload_session_checkpoint(90)


