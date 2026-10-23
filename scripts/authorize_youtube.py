#!/usr/bin/env python3
"""Bulletproof YouTube OAuth Receiver & Token Exchanger (Zero MismatchingStateError)."""
import http.server
import json
import logging
import socketserver
import sys
import urllib.parse
import webbrowser
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.oauth")

CLIENT_SECRETS_FILE = Path("data/credentials/client_secrets.json")
TOKEN_FILE = Path("data/credentials/token.json")
TOKEN_2_FILE = Path("data/credentials/token_2.json")
PORT = 8080
REDIRECT_URI = f"http://127.0.0.1:{PORT}/"
SCOPES = "https://www.googleapis.com/auth/youtube.upload"


def get_client_credentials() -> tuple[str, str]:
    with open(CLIENT_SECRETS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    info = data.get("installed") or data.get("web")
    return info["client_id"], info["client_secret"]


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

    # Structure into google-auth compatible format
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
                TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(TOKEN_FILE, "w", encoding="utf-8") as f:
                    json.dump(tokens, f, indent=2)
                with open(TOKEN_2_FILE, "w", encoding="utf-8") as f:
                    json.dump(tokens, f, indent=2)

                log.info("SUCCESS! Saved OAuth tokens to token.json and token_2.json!")
                OAuthCallbackHandler.auth_completed = True

                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                html = """
                <html>
                <body style="font-family:sans-serif; text-align:center; padding:50px; background:#121212; color:white;">
                    <h1 style="color:#00E5FF;">VyralX Authorization Successful!</h1>
                    <p style="font-size:18px;">Your new Google Cloud Project is connected.</p>
                    <p style="color:#888;">You can close this window now. VyralX is uploading your videos directly to YouTube!</p>
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
        pass  # Suppress default noisy access logs


def main():
    client_id, client_secret = get_client_credentials()
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
    print("VyralX Bulletproof YouTube OAuth Server (Port 8080)", flush=True)
    print("=" * 60, flush=True)
    print("\n👉 AUTHORIZATION URL:\n", flush=True)
    print(auth_url, flush=True)
    print("\n" + "=" * 60, flush=True)
    print("Opening browser for authorization...", flush=True)

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    # Allow address reuse to prevent 'Address already in use' errors
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", PORT), OAuthCallbackHandler) as httpd:
        log.info("Server listening on %s. Waiting for callback...", REDIRECT_URI)
        while not OAuthCallbackHandler.auth_completed:
            httpd.handle_request()

    log.info("Authorization completed! Now launching raw viral video uploads...")
    sys.path.insert(0, str(Path.cwd()))
    from scripts.upload_raw_viral_videos import upload_all_raw
    upload_all_raw()


if __name__ == "__main__":
    main()
