#!/usr/bin/env python3
"""Create a local YouTube OAuth token without printing credentials."""

from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import get_settings

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"


def main() -> int:
    settings = get_settings()
    client_file = settings.youtube_client_secrets_file
    token_file = settings.youtube_token_file

    if not client_file.is_file():
        print(
            "OAuth client file was not found at "
            f"{client_file}. Place your downloaded Desktop OAuth client JSON there."
        )
        return 2

    token_file.parent.mkdir(parents=True, exist_ok=True)
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
        # Some filesystems (notably Windows mounts) do not support POSIX modes.
        pass

    print(f"YouTube OAuth token saved to {token_file}.")
    print("Keep this file private; it grants upload access to the connected channel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
