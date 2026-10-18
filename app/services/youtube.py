"""Official YouTube OAuth and resumable upload adapter.

Errors after a resumable request has started are marked as outcome-unknown unless the
API returned a definite client-side rejection. The worker must reconcile those cases
against YouTube before retrying, to avoid duplicate public videos.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.config import get_settings


log = logging.getLogger(__name__)


class UploadOutcomeUnknown(RuntimeError):
    """Remote upload might have been accepted; automated retry is unsafe."""


def _atomic_private_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temp.chmod(0o600)
        except OSError:
            pass
        temp.replace(path)
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def _upload_checkpoint_path(publish_job_id: int, *, create_parent: bool = False) -> Path:
    """Return a job-scoped receipt path below the private OAuth data directory."""
    if isinstance(publish_job_id, bool) or not isinstance(publish_job_id, int) or publish_job_id < 1:
        raise ValueError("publish_job_id must be a positive integer")
    settings = get_settings()
    token_path = Path(
        getattr(settings, "youtube_token_file", Path("./data/secrets/youtube-token.json"))
    ).resolve()
    directory = token_path.parent / "upload-checkpoints"
    if create_parent:
        directory.mkdir(parents=True, exist_ok=True)
        try:
            directory.chmod(0o700)
        except OSError:
            pass
    root = directory.resolve()
    path = (root / f"{publish_job_id}.json").resolve()
    if root not in path.parents:
        raise ValueError("Invalid upload checkpoint path")
    return path


def _valid_video_id(value: object) -> bool:
    return (
        isinstance(value, str)
        and 6 <= len(value) <= 100
        and all(char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in value)
    )


def write_upload_success_checkpoint(
    publish_job_id: int, upload_attempt: int, video_id: str
) -> bool:
    """Persist provider-confirmed success before the worker commits its database state."""
    if (
        isinstance(upload_attempt, bool)
        or not isinstance(upload_attempt, int)
        or upload_attempt < 1
        or not _valid_video_id(video_id)
    ):
        return False
    payload = {
        "version": 1,
        "publish_job_id": publish_job_id,
        "upload_attempt": upload_attempt,
        "video_id": video_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_private_write(
        _upload_checkpoint_path(publish_job_id, create_parent=True),
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
    )
    return True


def load_upload_success_checkpoint(publish_job_id: int, upload_attempt: int) -> str | None:
    """Return only an explicit success receipt matching this job and attempt."""
    if (
        isinstance(upload_attempt, bool)
        or not isinstance(upload_attempt, int)
        or upload_attempt < 1
    ):
        return None
    try:
        payload = json.loads(
            _upload_checkpoint_path(publish_job_id).read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if (
        type(payload.get("version")) is not int
        or payload.get("version") != 1
        or type(payload.get("publish_job_id")) is not int
        or payload.get("publish_job_id") != publish_job_id
        or type(payload.get("upload_attempt")) is not int
        or payload.get("upload_attempt") != upload_attempt
        or not _valid_video_id(payload.get("video_id"))
    ):
        return None
    return str(payload["video_id"])


def clear_upload_success_checkpoint(publish_job_id: int) -> None:
    """Remove a success receipt after the corresponding outcome is durably committed."""
    try:
        _upload_checkpoint_path(publish_job_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        log.warning("Could not remove YouTube success checkpoint for publish job %s", publish_job_id)


def youtube_service():
    settings = get_settings()
    token_path = settings.youtube_token_file
    if not token_path.is_file():
        raise RuntimeError("YouTube OAuth token file is missing; complete OAuth setup first")
    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError("YouTube OAuth token file is unreadable or invalid JSON") from None
    credentials = Credentials.from_authorized_user_info(data)
    if credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
        except Exception as exc:
            raise RuntimeError(f"YouTube OAuth refresh failed ({type(exc).__name__})") from None
        _atomic_private_write(token_path, credentials.to_json())
    if not credentials.valid:
        raise RuntimeError("YouTube OAuth credentials are invalid or expired")
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


def upload_video(
    file_path: str,
    *,
    title: str,
    description: str,
    tags: list[str],
    privacy_status: str,
    category_id: str,
    scheduled_at: str = "",
    publish_job_id: int | None = None,
    upload_attempt: int | None = None,
) -> str:
    settings = get_settings()
    if not settings.youtube_upload_enabled:
        raise RuntimeError("Publishing disabled; enable only after OAuth verification")
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Rendered video does not exist")
    if path.stat().st_size <= 0:
        raise ValueError("Rendered video is empty")
    if privacy_status not in {"private", "unlisted", "public"}:
        raise ValueError("Invalid privacy status")
    if not title.strip() or len(title) > 100:
        raise ValueError("YouTube title must contain 1–100 characters")
    if len(description) > 5000 or len(tags) > 30 or any(len(str(tag)) > 100 for tag in tags):
        raise ValueError("YouTube description/tag limits exceeded")
    body = {
        "snippet": {
            "title": title.strip(),
            "description": description,
            "tags": [str(tag) for tag in tags[:30]],
            "categoryId": category_id,
        },
        "status": {"privacyStatus": privacy_status},
    }
    if scheduled_at:
        if privacy_status != "private":
            raise ValueError("Scheduled publishing must start with privacy_status=private")
        # Do not pass malformed timestamps to the YouTube API.
        from datetime import datetime, timezone
        try:
            scheduled = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("scheduled_at must be an ISO-8601 timestamp") from None
        if scheduled.tzinfo is None or scheduled.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone")
        if scheduled.astimezone(timezone.utc) <= datetime.now(timezone.utc):
            raise ValueError("scheduled_at must be in the future")
        body["status"]["publishAt"] = scheduled.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    # Preflight (credential loading and request construction) is safe to report as a
    # normal failure: the upload body has not been transmitted yet.
    service = youtube_service()
    media = MediaFileUpload(str(path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/*")
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        try:
            # Google client internally retries transient responses; a failure after
            # earlier chunks may still represent an upload accepted by YouTube.
            _, response = request.next_chunk(num_retries=5)
        except HttpError as exc:
            status_code = int(getattr(getattr(exc, "resp", None), "status", 0) or 0)
            if 400 <= status_code < 500:
                raise RuntimeError(f"YouTube rejected the upload (HTTP {status_code})") from None
            raise UploadOutcomeUnknown(
                f"YouTube upload outcome is uncertain after HTTP {status_code or 'server error'}; reconcile before retrying"
            ) from None
        except (httpx.RequestError, OSError, TimeoutError) as exc:
            raise UploadOutcomeUnknown(
                f"YouTube upload outcome is uncertain after {type(exc).__name__}; reconcile before retrying"
            ) from None
        except Exception as exc:
            # Calling next_chunk means the request may have reached Google, even
            # when the first chunk raises an unexpected provider/client exception.
            raise UploadOutcomeUnknown(
                f"YouTube upload outcome is uncertain after {type(exc).__name__}; reconcile before retrying"
            ) from None
    video_id = response.get("id")
    if not video_id:
        raise UploadOutcomeUnknown("YouTube response lacked a video ID; reconcile provider state before retrying")
    normalized_video_id = str(video_id)
    if publish_job_id is not None and upload_attempt is not None:
        try:
            write_upload_success_checkpoint(publish_job_id, upload_attempt, normalized_video_id)
        except (OSError, ValueError) as exc:
            # The provider has confirmed success. Preserve normal DB commit behavior;
            # the receipt only narrows the crash window before that commit.
            log.warning(
                "YouTube success checkpoint could not be persisted for job %s (%s)",
                publish_job_id,
                type(exc).__name__,
            )
    return normalized_video_id
