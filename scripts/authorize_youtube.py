#!/usr/bin/env python3
"""Create a local YouTube OAuth token without printing credentials."""
import sys
from pathlib import Path

# Ensure VyralX package is prioritized over other editable workspace agents
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from google_auth_oauthlib.flow import InstalledAppFlow
from app.config import get_settings

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def main() -> int:
    settings = get_settings()
    client_file = settings.youtube_client_secrets_file
    token_file = settings.youtube_token_file

    if not client_file.is_file():
        print(
            "ERROR: OAuth client file was not found at "
            f"{client_file}.\nPlease place your downloaded client_secrets.json in data/credentials/.",
            flush=True,
        )
        return 2

    token_file.parent.mkdir(parents=True, exist_ok=True)
    print("\n" + "=" * 60, flush=True)
    print("VyralX YouTube OAuth Authorization", flush=True)
    print("=" * 60, flush=True)
    print("Opening browser for Google authorization...", flush=True)
    print("If your browser does not open automatically, copy the URL below:\n", flush=True)

    flow = InstalledAppFlow.from_client_secrets_file(
        str(client_file),
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )
    credentials = flow.run_local_server(
        host="127.0.0.1",
        port=0,
        open_browser=True,
        access_type="offline",
        prompt="consent",
    )
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    try:
        token_file.chmod(0o600)
    except OSError:
        pass

    print("\n" + "=" * 60, flush=True)
    print(f"SUCCESS! YouTube OAuth token saved to:\n{token_file}", flush=True)
    print("VyralX is now fully authorized to publish to your channel!", flush=True)
    print("=" * 60 + "\n", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
