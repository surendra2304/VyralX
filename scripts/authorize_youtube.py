#!/usr/bin/env python3
"""Standard Google OAuth Receiver & Token Exchanger for VyralX."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.oauth")

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]


def run_auth(secrets_file: str = "data/credentials/client_secrets.json"):
    secrets_path = Path(secrets_file)
    if not secrets_path.exists():
        log.error("Secrets file not found: %s", secrets_path)
        return

    log.info("Starting Google OAuth flow using %s...", secrets_path)
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes=SCOPES)
    
    # run_local_server uses http://localhost:8080/ matching the installed client config
    credentials = flow.run_local_server(
        port=8080,
        prompt="consent",
        access_type="offline",
        success_message="VyralX YouTube Authorization Successful! You may close this tab.",
    )

    token_file = Path("data/credentials/token.json")
    token_file.parent.mkdir(parents=True, exist_ok=True)
    with open(token_file, "w", encoding="utf-8") as f:
        f.write(credentials.to_json())

    log.info("SUCCESS! Saved new OAuth tokens to %s!", token_file)
    log.info("Now launching approved shorts publication...")
    from scripts.publish_approved_videos import publish_all
    publish_all()


if __name__ == "__main__":
    secrets = sys.argv[1] if len(sys.argv) > 1 else "data/credentials/client_secrets.json"
    run_auth(secrets)

