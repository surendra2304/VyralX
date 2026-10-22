"""VyralX Multi-Project Google Cloud Quota Rotator.

Enables pooling multiple Google Cloud Projects to multiply YouTube upload quotas.
When Project 1 reaches its 10,000 daily units limit (HTTP 429), VyralX automatically
rotates to Project 2 and Project 3, allowing continuous multi-video publishing.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from app.config import get_settings

log = logging.getLogger("vyralx.quota_rotator")

QUOTA_TRACKER_FILE = "data/credentials/quota_status.json"


def _get_daily_reset_time_utc() -> datetime:
    """YouTube API quota resets at midnight Pacific Time (08:00 UTC during PDT / 07:00 UTC during PST)."""
    now_utc = datetime.now(timezone.utc)
    # Target 07:00 UTC (midnight PST)
    reset_candidate = now_utc.replace(hour=7, minute=0, second=0, microsecond=0)
    if reset_candidate <= now_utc:
        reset_candidate += timedelta(days=1)
    return reset_candidate


def load_quota_status() -> dict[str, Any]:
    p = Path(QUOTA_TRACKER_FILE)
    if not p.is_file():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_quota_status(status: dict[str, Any]) -> None:
    p = Path(QUOTA_TRACKER_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)


def mark_project_exhausted(token_path: Path, error_message: str = "") -> None:
    """Mark a project token as quota-exhausted until the next daily reset."""
    status = load_quota_status()
    key = str(token_path.resolve())
    reset_time = _get_daily_reset_time_utc().isoformat()
    status[key] = {
        "exhausted_at": datetime.now(timezone.utc).isoformat(),
        "resets_at": reset_time,
        "reason": error_message[:200],
    }
    save_quota_status(status)
    log.warning("Project token %s marked quota-exhausted until %s", token_path.name, reset_time)


def is_project_exhausted(token_path: Path) -> bool:
    """Check if a project token is currently in a quota exhaustion blackout."""
    status = load_quota_status()
    key = str(token_path.resolve())
    entry = status.get(key)
    if not entry:
        return False

    resets_at_str = entry.get("resets_at")
    if not resets_at_str:
        return False

    try:
        resets_at = datetime.fromisoformat(resets_at_str)
        if datetime.now(timezone.utc) >= resets_at:
            # Blackout period has passed; auto-clear
            del status[key]
            save_quota_status(status)
            return False
        return True
    except Exception:
        return False


def get_all_project_tokens() -> list[Path]:
    """Discover all registered Google OAuth project token files."""
    settings = get_settings()
    cred_dir = settings.data_dir / "credentials"
    if not cred_dir.is_dir():
        return []

    # Priority 1: Primary token.json
    primary = cred_dir / "token.json"
    tokens: list[Path] = []
    if primary.is_file():
        tokens.append(primary)

    # Priority 2: Additional project tokens (token_2.json, token_3.json, token_project_*.json)
    for p in sorted(cred_dir.glob("token_*.json")):
        if p.is_file() and p not in tokens:
            tokens.append(p)

    return tokens


def get_next_available_credentials() -> tuple[Credentials, Path]:
    """Return the next active, non-quota-exhausted Google Cloud credentials."""
    token_files = get_all_project_tokens()
    if not token_files:
        raise RuntimeError("No Google Cloud YouTube OAuth tokens found in data/credentials/")

    exhausted_count = 0
    selected_token: Path | None = None

    for tf in token_files:
        if is_project_exhausted(tf):
            exhausted_count += 1
            continue
        selected_token = tf
        break

    if selected_token is None:
        # All available projects are exhausted; fallback to primary token and inform user
        log.warning("All %d registered Google Cloud projects are quota-exhausted for today.", len(token_files))
        selected_token = token_files[0]

    with open(selected_token, "r", encoding="utf-8") as f:
        data = json.load(f)

    creds = Credentials.from_authorized_user_info(data)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(selected_token, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    log.info("Using Google Cloud credentials from: %s", selected_token.name)
    return creds, selected_token


def register_new_oauth_project(client_secrets_path: Path, output_token_path: Path | None = None) -> Path:
    """Run interactive OAuth consent flow for a new Google Cloud project."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    settings = get_settings()
    cred_dir = settings.data_dir / "credentials"
    cred_dir.mkdir(parents=True, exist_ok=True)

    if output_token_path is None:
        # Auto-increment token number: token_2.json, token_3.json...
        idx = 2
        while (cred_dir / f"token_{idx}.json").exists():
            idx += 1
        output_token_path = cred_dir / f"token_{idx}.json"

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets_path), scopes=scopes)
    credentials = flow.run_local_server(port=0)

    with open(output_token_path, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())

    log.info("Successfully registered new Google Cloud project token: %s", output_token_path)
    return output_token_path
