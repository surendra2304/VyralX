"""Official YouTube OAuth and resumable upload adapter.

Errors after a resumable request has started are marked as outcome-unknown unless the
API returned a definite client-side rejection. The worker must reconcile those cases
against YouTube before retrying, to avoid duplicate public videos.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.config import get_settings


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
    started = False
    while response is None:
        try:
            # Google client internally retries transient responses; a failure after
            # earlier chunks may still represent an upload accepted by YouTube.
            _, response = request.next_chunk(num_retries=5)
            started = True
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
            # The resumable HTTP request may have reached Google even if the
            # client raised a provider-specific exception.
            if started:
                raise UploadOutcomeUnknown(
                    f"YouTube upload outcome is uncertain after {type(exc).__name__}; reconcile before retrying"
                ) from None
            raise RuntimeError(f"YouTube upload failed before confirmation ({type(exc).__name__})") from None
        started = True
    video_id = response.get("id")
    if not video_id:
        raise UploadOutcomeUnknown("YouTube response lacked a video ID; reconcile provider state before retrying")
    return str(video_id)
