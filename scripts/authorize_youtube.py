#!/usr/bin/env python3
"""Flexible YouTube OAuth Receiver & Token Exchanger."""
from __future__ import annotations

import http.server
import json
import logging
import socketserver
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.oauth")

PORT = 8080
REDIRECT_URI = f"http://127.0.0.1:{PORT}/"
SCOPES = "https://www.googleapis.com/auth/youtube.upload"


def get_client_credentials(secrets_path: Path) -> tuple[str, str, str]:
    with open(secrets_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    info = data.get("installed") or data.get("web")
    return info["client_id"], info["client_secret"], info.get("project_id", "unknown")


def exchange_code_for_tokens(code: str, client_id: str, client_secret: str) -> dict:
    url = "https://oauth2.googleapis.com/token"
    payload = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": REDIRECT_URI,
        "grant_type": "authorization_code",
    }
    resp = requests.post(url, data=payload, timeout=30)
    resp.raise_for_status()
    token_data = resp.json()

    formatted = {
        "token": token_data.get("access_token"),
        "refresh_token": token_data.get("refresh_token"),
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": client_id,
        "client_secret": client_secret,
        "scopes": [SCOPES],
    }
    return formatted


class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    client_id: str = ""
    client_secret: str = ""
    auth_completed: bool = False

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            code = params["code"][0]
            log.info("Received authorization code from Google! Exchanging for token...")
            try:
                tokens = exchange_code_for_tokens(code, self.client_id, self.client_secret)
                token_file = Path("data/credentials/token.json")
                token_file.parent.mkdir(parents=True, exist_ok=True)
                with open(token_file, "w", encoding="utf-8") as f:
                    json.dump(tokens, f, indent=2)

                log.info("SUCCESS! Saved new OAuth tokens to token.json!")
                OAuthCallbackHandler.auth_completed = True

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = """
                <html>
                <body style="font-family:sans-serif; text-align:center; padding:50px; background:#121212; color:white;">
                    <h1 style="color:#00E5FF;">VyralX Authorization Successful!</h1>
                    <p style="font-size:18px;">Account connected successfully.</p>
                    <p style="color:#888;">Publishing the 2 approved commentary shorts to YouTube now!</p>
                </body>
                </html>
                """
                self.wfile.write(html.encode("utf-8"))
            except Exception as e:
                log.exception("Token exchange failed: %s", e)
                self.send_response(500)
                self.end_headers()
                self.wfile.write(f"Token exchange failed: {e}".encode("utf-8"))
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No code parameter found in callback.")

    def log_message(self, format, *args):
        pass


def run_auth(secrets_file: str = "data/credentials/client_secrets.json"):
    secrets_path = Path(secrets_file)
    if not secrets_path.exists():
        log.error("Secrets file not found: %s", secrets_path)
        return

    client_id, client_secret, project_id = get_client_credentials(secrets_path)
    OAuthCallbackHandler.client_id = client_id
    OAuthCallbackHandler.client_secret = client_secret

    auth_params = {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    auth_url = f"https://accounts.google.com/o/oauth2/auth?{urllib.parse.urlencode(auth_params)}"

    print("=" * 60, flush=True)
    print(f"VyralX YouTube OAuth Receiver (Project: {project_id})", flush=True)
    print("=" * 60, flush=True)
    print("\n👉 AUTHORIZATION URL:\n", flush=True)
    print(auth_url, flush=True)
    print("\n" + "=" * 60, flush=True)
    print("Opening browser for authorization...", flush=True)

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), OAuthCallbackHandler) as httpd:
        log.info("Server listening on %s. Waiting for callback...", REDIRECT_URI)
        while not OAuthCallbackHandler.auth_completed:
            httpd.handle_request()

    log.info("Authorization completed! Now launching approved shorts publication...")
    from scripts.publish_approved_videos import publish_all
    publish_all()


if __name__ == "__main__":
    secrets = sys.argv[1] if len(sys.argv) > 1 else "data/credentials/client_secrets.json"
    run_auth(secrets)
