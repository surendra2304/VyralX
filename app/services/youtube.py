import json
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from app.config import get_settings

def youtube_service():
    settings = get_settings()
    token_path = settings.youtube_token_file
    if not token_path.is_file():
        raise RuntimeError("YouTube OAuth token file is missing; complete OAuth setup first")
    data = json.loads(token_path.read_text(encoding="utf-8"))
    credentials = Credentials.from_authorized_user_info(data)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        token_path.write_text(credentials.to_json(), encoding="utf-8")
    if not credentials.valid:
        raise RuntimeError("YouTube OAuth credentials are invalid or expired")
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)

def upload_video(file_path: str, *, title: str, description: str, tags: list[str],
                 privacy_status: str, category_id: str, scheduled_at: str = "") -> str:
    settings = get_settings()
    if not settings.youtube_upload_enabled:
        raise RuntimeError("Publishing disabled; enable only after OAuth verification")
    path = Path(file_path).resolve()
    if not path.is_file():
        raise FileNotFoundError("Rendered video does not exist")
    if privacy_status not in {"private", "unlisted", "public"}:
        raise ValueError("Invalid privacy status")
    body = {"snippet": {"title": title, "description": description, "tags": tags[:30],
                        "categoryId": category_id},
            "status": {"privacyStatus": privacy_status}}
    if scheduled_at:
        if privacy_status != "private":
            raise ValueError("Scheduled publishing must start with privacy_status=private")
        body["status"]["publishAt"] = scheduled_at
    service = youtube_service()
    media = MediaFileUpload(str(path), chunksize=8 * 1024 * 1024, resumable=True, mimetype="video/*")
    request = service.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()
    video_id = response.get("id")
    if not video_id:
        raise RuntimeError("YouTube API returned no video ID")
    return video_id
