"""One-time YouTube OAuth authorization for VyralX uploads.

Run this on the machine that owns the Google account:

    python scripts/youtube_authorize.py

It opens a browser consent screen, then writes the refreshed token to
``YOUTUBE_TOKEN_FILE`` (``./data/credentials/token.json`` by default). After it
finishes, ``scripts/run_autopilot.py`` can upload without further interaction.
"""
from __future__ import annotations

import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import get_settings

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def main() -> None:
    settings = get_settings()
    secrets_path = Path(settings.youtube_client_secrets_file).resolve()
    token_path = Path(settings.youtube_token_file).resolve()
    if not secrets_path.is_file():
        raise SystemExit(f"Client secrets file not found: {secrets_path}")

    raw = json.loads(secrets_path.read_text(encoding="utf-8"))
    client_type = "installed" if "installed" in raw else "web"
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    print(f"Client type: {client_type}. Opening browser for Google consent...")
    creds = flow.run_local_server(
        port=8080,
        prompt="consent",
        authorization_prompt_message="Open this URL to authorize VyralX: {url}",
    )
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    try:
        token_path.chmod(0o600)
    except OSError:
        pass
    print(f"Saved OAuth token to {token_path}")
    print("Verify with: python -c \"from app.services.youtube import youtube_credentials; youtube_credentials(); print('OK')\"")


if __name__ == "__main__":
    main()
