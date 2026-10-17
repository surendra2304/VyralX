# VyralX API

Interactive OpenAPI docs: /docs. Health: /health. Readiness: /ready.

Outside development mode, send the X-API-Key header for all /api/* routes.

| Method | Route | Purpose |
|---|---|---|
| POST | /api/sources | Register source/provenance and rights record |
| GET | /api/sources | List source catalog |
| POST | /api/assets/upload | Import an authorized video file |
| GET | /api/assets | List imported assets |
| POST | /api/render | Render an asset with shorts, long, or square preset |
| GET | /api/render | List render jobs |
| POST | /api/publish | Queue a chosen completed render after explicit rights confirmation |
| POST | /api/publish/{id}/execute | Upload completed render through YouTube API |
| GET | /api/publish | List publishing jobs |

## First run
1. Copy .env.example to .env and set a strong API_KEY.
2. Install FFmpeg and Python 3.11+.
3. Install with pip install -e ".[dev]".
4. Run uvicorn app.main:app --host 127.0.0.1 --port 8010.
5. Visit /docs, check /health, and run pytest.

Publish requests must include `asset_id` and `render_job_id` so the queued job remains bound to the reviewed rendition. Omit `privacy_status` to use `YOUTUBE_DEFAULT_PRIVACY` (defaults to `private`).

Production publishing remains disabled until OAuth is tested and YOUTUBE_UPLOAD_ENABLED=true is explicitly configured.
