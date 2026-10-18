"""Official YouTube OAuth and resumable upload adapter.

Errors after a resumable request has started are marked as outcome-unknown unless the
API returned a definite client-side rejection. The worker must reconcile those cases
against YouTube before retrying, to avoid duplicate public videos.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from requests.exceptions import RequestException

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


_UPLOAD_ENDPOINT = "https://www.googleapis.com/upload/youtube/v3/videos"
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
_UPLOAD_HTTP_TIMEOUT = (10, 90)
_UPLOAD_STALL_LIMIT = 3


class _UploadSessionExpired(RuntimeError):
    """The provider no longer recognizes this resumable-session URI."""


def _upload_session_checkpoint_path(
    publish_job_id: int, *, create_parent: bool = False
) -> Path:
    base = _upload_checkpoint_path(publish_job_id, create_parent=create_parent)
    return base.with_name(base.stem + ".session.json")


def upload_session_checkpoint_exists(publish_job_id: int) -> bool:
    try:
        return _upload_session_checkpoint_path(publish_job_id).is_file()
    except (OSError, ValueError):
        return False


def _valid_upload_session_uri(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlsplit(value)
        hostname = (parsed.hostname or "").casefold()
        return bool(
            parsed.scheme == "https"
            and (hostname == "googleapis.com" or hostname.endswith(".googleapis.com"))
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and parsed.path == "/upload/youtube/v3/videos"
            and parsed.query
        )
    except ValueError:
        return False


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _metadata_sha256(body: dict) -> str:
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def write_upload_session_checkpoint(
    publish_job_id: int,
    upload_attempt: int,
    *,
    session_uri: str,
    file_path: str,
    file_size: int,
    file_sha256: str,
    metadata_sha256: str,
    confirmed_offset: int = 0,
) -> bool:
    """Atomically persist a private, attempt-scoped resumable session and confirmed offset."""
    _upload_session_checkpoint_path(publish_job_id)
    if (
        isinstance(upload_attempt, bool)
        or not isinstance(upload_attempt, int)
        or upload_attempt < 1
        or not _valid_upload_session_uri(session_uri)
        or not isinstance(file_path, str)
        or not file_path
        or isinstance(file_size, bool)
        or not isinstance(file_size, int)
        or file_size < 1
        or not _is_sha256(file_sha256)
        or not _is_sha256(metadata_sha256)
        or isinstance(confirmed_offset, bool)
        or not isinstance(confirmed_offset, int)
        or confirmed_offset < 0
        or confirmed_offset > file_size
    ):
        return False
    payload = {
        "version": 1,
        "publish_job_id": publish_job_id,
        "upload_attempt": upload_attempt,
        "session_uri": session_uri,
        "file_path": str(Path(file_path).resolve()),
        "file_size": file_size,
        "file_sha256": file_sha256,
        "metadata_sha256": metadata_sha256,
        "confirmed_offset": confirmed_offset,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_private_write(
        _upload_session_checkpoint_path(publish_job_id, create_parent=True),
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
    )
    return True


def load_upload_session_checkpoint(
    publish_job_id: int, upload_attempt: int
) -> dict | None:
    """Load only a structurally valid receipt for this exact upload attempt."""
    if (
        isinstance(upload_attempt, bool)
        or not isinstance(upload_attempt, int)
        or upload_attempt < 1
    ):
        return None
    try:
        payload = json.loads(
            _upload_session_checkpoint_path(publish_job_id).read_text(encoding="utf-8")
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
        or not _valid_upload_session_uri(payload.get("session_uri"))
        or not isinstance(payload.get("file_path"), str)
        or not payload.get("file_path")
        or type(payload.get("file_size")) is not int
        or payload.get("file_size") < 1
        or not _is_sha256(payload.get("file_sha256"))
        or not _is_sha256(payload.get("metadata_sha256"))
        or type(payload.get("confirmed_offset")) is not int
        or not 0 <= payload.get("confirmed_offset") <= payload.get("file_size")
    ):
        return None
    return payload


def clear_upload_session_checkpoint(publish_job_id: int) -> None:
    """Remove a session receipt after the job is committed or manually reconciled."""
    try:
        _upload_session_checkpoint_path(publish_job_id).unlink(missing_ok=True)
    except (OSError, ValueError):
        log.warning(
            "Could not remove YouTube session checkpoint for publish job %s", publish_job_id
        )


def youtube_credentials() -> Credentials:
    """Load and refresh the private OAuth token for both API and resumable HTTP requests."""
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
    return credentials


def youtube_service():
    return build("youtube", "v3", credentials=youtube_credentials(), cache_discovery=False)


def _video_id_from_response(response) -> str | None:
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, dict) or not _valid_video_id(payload.get("id")):
        return None
    return str(payload["id"])


def _resume_offset_from_response(response, file_size: int) -> int:
    header = response.headers.get("Range") or response.headers.get("range") or ""
    if not header:
        return 0
    match = re.fullmatch(r"bytes=0-(\d+)", str(header).strip())
    if match is None:
        raise UploadOutcomeUnknown("YouTube returned an invalid resumable-upload Range header")
    last_received = int(match.group(1))
    if last_received >= file_size:
        raise UploadOutcomeUnknown("YouTube resumable-upload Range exceeded the source file size")
    return last_received + 1


def _probe_upload_session(session, session_uri: str, file_size: int) -> tuple[int, str | None]:
    """Ask YouTube for its authoritative offset; never infer progress from bytes sent locally."""
    try:
        response = session.put(
            session_uri,
            data=b"",
            headers={
                "Content-Length": "0",
                "Content-Range": f"bytes */{file_size}",
                "Content-Type": "video/*",
            },
            timeout=_UPLOAD_HTTP_TIMEOUT,
            allow_redirects=False,
        )
    except (RequestException, OSError, TimeoutError):
        raise UploadOutcomeUnknown(
            "Could not query the saved YouTube upload session; reconcile before retrying"
        ) from None
    status = int(getattr(response, "status_code", 0) or 0)
    if status in (200, 201):
        video_id = _video_id_from_response(response)
        if video_id:
            return file_size, video_id
        raise UploadOutcomeUnknown(
            "YouTube reported a completed upload without a usable video ID; reconcile before retrying"
        )
    if status == 308:
        return _resume_offset_from_response(response, file_size), None
    if status == 404:
        raise _UploadSessionExpired("The YouTube resumable upload session expired")
    raise UploadOutcomeUnknown(
        f"Could not determine YouTube upload progress (HTTP {status or 'unknown'}); reconcile before retrying"
    )


def _write_session_progress(
    publish_job_id: int | None,
    upload_attempt: int | None,
    *,
    session_uri: str,
    file_path: Path,
    file_size: int,
    file_sha256: str,
    metadata_sha256: str,
    confirmed_offset: int,
) -> None:
    if publish_job_id is None or upload_attempt is None:
        return
    try:
        ok = write_upload_session_checkpoint(
            publish_job_id,
            upload_attempt,
            session_uri=session_uri,
            file_path=str(file_path),
            file_size=file_size,
            file_sha256=file_sha256,
            metadata_sha256=metadata_sha256,
            confirmed_offset=confirmed_offset,
        )
    except (OSError, ValueError):
        raise UploadOutcomeUnknown(
            "Could not persist YouTube upload progress; reconcile before retrying"
        ) from None
    if not ok:
        raise UploadOutcomeUnknown(
            "YouTube upload checkpoint validation failed; reconcile before retrying"
        )


def _start_upload_session(
    session,
    body: dict,
    *,
    file_size: int,
    file_path: Path,
    file_sha256: str,
    metadata_sha256: str,
    publish_job_id: int | None,
    upload_attempt: int | None,
) -> str:
    try:
        response = session.post(
            _UPLOAD_ENDPOINT,
            params={"uploadType": "resumable", "part": "snippet,status"},
            json=body,
            headers={
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(file_size),
                "X-Upload-Content-Type": "video/*",
            },
            timeout=_UPLOAD_HTTP_TIMEOUT,
            allow_redirects=False,
        )
    except (RequestException, OSError, TimeoutError) as exc:
        # No video bytes have been sent yet, so the worker may safely retry after review.
        raise RuntimeError(
            f"YouTube resumable session initialization failed ({type(exc).__name__})"
        ) from None
    status = int(getattr(response, "status_code", 0) or 0)
    if status != 200:
        raise RuntimeError(f"YouTube rejected resumable session initialization (HTTP {status})")
    session_uri = response.headers.get("Location") or response.headers.get("location")
    if not _valid_upload_session_uri(session_uri):
        raise RuntimeError("YouTube did not return a trusted resumable session URI")
    _write_session_progress(
        publish_job_id,
        upload_attempt,
        session_uri=session_uri,
        file_path=file_path,
        file_size=file_size,
        file_sha256=file_sha256,
        metadata_sha256=metadata_sha256,
        confirmed_offset=0,
    )
    return session_uri


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
    """Upload through the YouTube resumable protocol with crash-safe session receipts."""
    settings = get_settings()
    if not settings.youtube_upload_enabled:
        raise RuntimeError("Publishing disabled; enable only after OAuth verification")
    if (publish_job_id is None) != (upload_attempt is None):
        raise ValueError("publish_job_id and upload_attempt must be supplied together")
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Rendered video does not exist")
    file_size = path.stat().st_size
    if file_size <= 0:
        raise ValueError("Rendered video is empty")
    if privacy_status not in {"private", "unlisted", "public"}:
        raise ValueError("Invalid privacy status")
    if not title.strip() or len(title) > 100:
        raise ValueError("YouTube title must contain 1–100 characters")
    if len(description.encode("utf-8")) > 5000 or len(tags) > 30 or any(
        len(str(tag)) > 100 for tag in tags
    ):
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
        try:
            scheduled = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("scheduled_at must be an ISO-8601 timestamp") from None
        if scheduled.tzinfo is None or scheduled.utcoffset() is None:
            raise ValueError("scheduled_at must include a timezone")
        if scheduled.astimezone(timezone.utc) <= datetime.now(timezone.utc):
            raise ValueError("scheduled_at must be in the future")
        body["status"]["publishAt"] = (
            scheduled.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        )

    # Hash the exact input before initiating/reusing a remote session. A changed render
    # or metadata must never be appended to a session created for different content.
    file_sha256 = _file_sha256(path)
    metadata_sha256 = _metadata_sha256(body)
    session_state = None
    if publish_job_id is not None and upload_attempt is not None:
        session_state = load_upload_session_checkpoint(publish_job_id, upload_attempt)
        if session_state is None and upload_session_checkpoint_exists(publish_job_id):
            raise UploadOutcomeUnknown(
                "A saved YouTube session checkpoint is invalid or belongs to a different attempt; "
                "reconcile before retrying"
            )
        if session_state is not None:
            if (
                session_state["file_path"] != str(path)
                or session_state["file_size"] != file_size
                or session_state["file_sha256"] != file_sha256
                or session_state["metadata_sha256"] != metadata_sha256
            ):
                raise UploadOutcomeUnknown(
                    "Saved YouTube session does not match the current render or metadata; "
                    "reconcile before retrying"
                )

    credentials = youtube_credentials()
    with AuthorizedSession(credentials) as session:
        if session_state is None:
            session_uri = _start_upload_session(
                session,
                body,
                file_size=file_size,
                file_path=path,
                file_sha256=file_sha256,
                metadata_sha256=metadata_sha256,
                publish_job_id=publish_job_id,
                upload_attempt=upload_attempt,
            )
            offset = 0
        else:
            session_uri = session_state["session_uri"]
            try:
                offset, already_uploaded_id = _probe_upload_session(
                    session, session_uri, file_size
                )
            except _UploadSessionExpired:
                # The official protocol returns the final resource for a completed session;
                # 404 means an incomplete session expired. Starting a fresh session is safe.
                if publish_job_id is not None:
                    clear_upload_session_checkpoint(publish_job_id)
                session_uri = _start_upload_session(
                    session,
                    body,
                    file_size=file_size,
                    file_path=path,
                    file_sha256=file_sha256,
                    metadata_sha256=metadata_sha256,
                    publish_job_id=publish_job_id,
                    upload_attempt=upload_attempt,
                )
                offset = 0
            else:
                if already_uploaded_id:
                    _record_confirmed_upload(publish_job_id, upload_attempt, already_uploaded_id)
                    return already_uploaded_id
                _write_session_progress(
                    publish_job_id,
                    upload_attempt,
                    session_uri=session_uri,
                    file_path=path,
                    file_size=file_size,
                    file_sha256=file_sha256,
                    metadata_sha256=metadata_sha256,
                    confirmed_offset=offset,
                )

        stalls = 0
        session_renewals = 0
        with path.open("rb") as media_file:
            while offset < file_size:
                media_file.seek(offset)
                chunk = media_file.read(min(UPLOAD_CHUNK_BYTES, file_size - offset))
                if not chunk:
                    raise UploadOutcomeUnknown(
                        "Local render ended before the saved YouTube upload completed; reconcile before retrying"
                    )
                first = offset
                last = offset + len(chunk) - 1
                try:
                    response = session.put(
                        session_uri,
                        data=chunk,
                        headers={
                            "Content-Length": str(len(chunk)),
                            "Content-Type": "video/*",
                            "Content-Range": f"bytes {first}-{last}/{file_size}",
                        },
                        timeout=_UPLOAD_HTTP_TIMEOUT,
                        allow_redirects=False,
                    )
                except (RequestException, OSError, TimeoutError):
                    # The server may have received all, some or none of this chunk.
                    try:
                        remote_offset, completed_id = _probe_upload_session(
                            session, session_uri, file_size
                        )
                    except _UploadSessionExpired:
                        remote_offset, completed_id = -1, None
                    if remote_offset == -1:
                        if session_renewals >= 1:
                            raise UploadOutcomeUnknown(
                                "YouTube upload session expired repeatedly; reconcile before retrying"
                            ) from None
                        session_renewals += 1
                        if publish_job_id is not None:
                            clear_upload_session_checkpoint(publish_job_id)
                        session_uri = _start_upload_session(
                            session,
                            body,
                            file_size=file_size,
                            file_path=path,
                            file_sha256=file_sha256,
                            metadata_sha256=metadata_sha256,
                            publish_job_id=publish_job_id,
                            upload_attempt=upload_attempt,
                        )
                        offset = 0
                        stalls = 0
                        continue
                    if completed_id:
                        _record_confirmed_upload(publish_job_id, upload_attempt, completed_id)
                        return completed_id
                    _write_session_progress(
                        publish_job_id,
                        upload_attempt,
                        session_uri=session_uri,
                        file_path=path,
                        file_size=file_size,
                        file_sha256=file_sha256,
                        metadata_sha256=metadata_sha256,
                        confirmed_offset=remote_offset,
                    )
                    if remote_offset == offset:
                        stalls += 1
                        if stalls > _UPLOAD_STALL_LIMIT:
                            raise UploadOutcomeUnknown(
                                "YouTube did not advance the resumable upload after repeated connection "
                                "failures; reconcile before retrying"
                            ) from None
                    else:
                        offset, stalls = remote_offset, 0
                    continue

                status = int(getattr(response, "status_code", 0) or 0)
                if status in (200, 201):
                    video_id = _video_id_from_response(response)
                    if not video_id:
                        raise UploadOutcomeUnknown(
                            "YouTube completed an upload response without a usable video ID; "
                            "reconcile before retrying"
                        )
                    _record_confirmed_upload(publish_job_id, upload_attempt, video_id)
                    return video_id
                if status == 308:
                    remote_offset = _resume_offset_from_response(response, file_size)
                    _write_session_progress(
                        publish_job_id,
                        upload_attempt,
                        session_uri=session_uri,
                        file_path=path,
                        file_size=file_size,
                        file_sha256=file_sha256,
                        metadata_sha256=metadata_sha256,
                        confirmed_offset=remote_offset,
                    )
                    if remote_offset == offset:
                        stalls += 1
                        if stalls > _UPLOAD_STALL_LIMIT:
                            raise UploadOutcomeUnknown(
                                "YouTube repeatedly reported no upload progress; reconcile before retrying"
                            )
                    else:
                        offset, stalls = remote_offset, 0
                    continue
                if status == 404:
                    if session_renewals >= 1:
                        raise UploadOutcomeUnknown(
                            "YouTube upload session expired repeatedly; reconcile before retrying"
                        )
                    session_renewals += 1
                    if publish_job_id is not None:
                        clear_upload_session_checkpoint(publish_job_id)
                    session_uri = _start_upload_session(
                        session,
                        body,
                        file_size=file_size,
                        file_path=path,
                        file_sha256=file_sha256,
                        metadata_sha256=metadata_sha256,
                        publish_job_id=publish_job_id,
                        upload_attempt=upload_attempt,
                    )
                    offset = 0
                    stalls = 0
                    continue
                if 500 <= status <= 599:
                    try:
                        remote_offset, completed_id = _probe_upload_session(
                            session, session_uri, file_size
                        )
                    except _UploadSessionExpired:
                        remote_offset, completed_id = -1, None
                    if remote_offset == -1:
                        if session_renewals >= 1:
                            raise UploadOutcomeUnknown(
                                "YouTube upload session expired repeatedly; reconcile before retrying"
                            )
                        session_renewals += 1
                        if publish_job_id is not None:
                            clear_upload_session_checkpoint(publish_job_id)
                        session_uri = _start_upload_session(
                            session,
                            body,
                            file_size=file_size,
                            file_path=path,
                            file_sha256=file_sha256,
                            metadata_sha256=metadata_sha256,
                            publish_job_id=publish_job_id,
                            upload_attempt=upload_attempt,
                        )
                        offset = 0
                        continue
                    if completed_id:
                        _record_confirmed_upload(publish_job_id, upload_attempt, completed_id)
                        return completed_id
                    _write_session_progress(
                        publish_job_id,
                        upload_attempt,
                        session_uri=session_uri,
                        file_path=path,
                        file_size=file_size,
                        file_sha256=file_sha256,
                        metadata_sha256=metadata_sha256,
                        confirmed_offset=remote_offset,
                    )
                    if remote_offset == offset:
                        stalls += 1
                        if stalls > _UPLOAD_STALL_LIMIT:
                            raise UploadOutcomeUnknown(
                                "YouTube server errors persisted without upload progress; reconcile before retrying"
                            )
                    else:
                        offset, stalls = remote_offset, 0
                    continue

                if publish_job_id is not None:
                    clear_upload_session_checkpoint(publish_job_id)
                raise RuntimeError(f"YouTube rejected the resumable upload (HTTP {status})")

        # A 308 after every byte was sent is unusual; ask the server for the final result.
        try:
            _, completed_id = _probe_upload_session(session, session_uri, file_size)
        except _UploadSessionExpired:
            completed_id = None
        if completed_id:
            _record_confirmed_upload(publish_job_id, upload_attempt, completed_id)
            return completed_id
        raise UploadOutcomeUnknown(
            "All video bytes were sent but YouTube has not returned a completed video resource; "
            "reconcile before retrying"
        )


def _record_confirmed_upload(
    publish_job_id: int | None, upload_attempt: int | None, video_id: str
) -> None:
    """Write the success receipt before the worker's database commit."""
    if publish_job_id is None or upload_attempt is None:
        return
    try:
        write_upload_success_checkpoint(publish_job_id, upload_attempt, video_id)
    except (OSError, ValueError) as exc:
        # The provider has confirmed success. The worker still commits normally; if
        # it crashes, the retained session URI can return the same final provider response.
        log.warning(
            "YouTube success checkpoint could not be persisted for job %s (%s)",
            publish_job_id,
            type(exc).__name__,
        )