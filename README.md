# VyralX

**VyralX — Viral Content Discovery & Distribution Agent**  
*Discover. Edit. Publish. Scale.*

VyralX is the video workflow agent in the FRIDAY Universe. It is designed to find promising content ideas, track provenance and usage rights, import authorized media, produce Shorts and long-form edits, publish through the official YouTube API, and retain job history for future analytics.

## Current implementation
- FastAPI service with health/readiness endpoints and a small operator dashboard.
- Persistent source, asset, render-job and publish-job records.
- Source license/permission evidence checks before media processing and publishing.
- Media metadata probing with FFprobe.
- FFmpeg render presets for 9:16 Shorts, 16:9 landscape, and square videos.
- YouTube OAuth credential loading and resumable upload; uploads are disabled by default.
- Docker image, Compose deployment template, CI workflow and initial tests.
- API documentation at `/docs` when running.

## Quick start
Requirements: Python 3.11+, FFmpeg/FFprobe.

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env
# Set a unique API_KEY in .env before exposing the service.
uvicorn app.main:app --host 127.0.0.1 --port 8000
pytest
```

Open `http://127.0.0.1:8000` for the dashboard and `http://127.0.0.1:8010/docs` for API docs.

## Video workflow
1. Register a candidate source with creator, source URL, license/permission reference and rights status.
2. Import a local video file that you own, licensed, or have explicit permission to republish.
3. VyralX probes the file and stores its metadata.
4. Render a Shorts, landscape, or square variant.
5. Select the completed render job and create a publishing job with its `asset_id` and `render_job_id`, plus title, description, tags, privacy and optional schedule.
6. Execute the job through YouTube's official API; persist the returned video ID.

A public URL is a discovery lead, not permission to download or republish a creator's work. Platform download/access controls must not be bypassed. The code does not implement third-party social scraping or unauthorized ripping.

## YouTube OAuth setup

1. Download a **Desktop app** OAuth client JSON from Google Cloud Console and save it at the path configured by `YOUTUBE_CLIENT_SECRETS_FILE` (default: `./secrets/youtube-client-secret.json`).
2. Install the project dependencies with `pip install -e ".[dev]"`.
3. Run `python scripts/authorize_youtube.py` on a machine with a browser and complete consent for the intended channel.
4. The helper writes the token to `YOUTUBE_TOKEN_FILE` (default: `./secrets/youtube-token.json`). Transfer it securely to the protected VyralX secrets volume when deploying.
5. Keep `YOUTUBE_UPLOAD_ENABLED=false` until the private test upload and live account/channel have been verified.

The client JSON and token are excluded from Git and from the Docker build context. Never paste either file's contents into an issue, pull request, or chat.

## FRIDAY Universe integration
VyralX is intended to become the tenth service. Planned peers are FRIDAY (orchestration), IntelX (research), Inference (AI generation), Memora (the sole long-term memory authority), and Sentinel (policy/security). Peer integration is not enabled until authenticated contracts, timeouts, health checks and tests are added. Dokploy remains the deployment controller.

## Configuration and security
- Copy values from `.env.example` into protected environment configuration; never commit real credentials.
- YouTube publishing is disabled unless `YOUTUBE_UPLOAD_ENABLED=true` is explicitly set.
- `YOUTUBE_DEFAULT_PRIVACY` defaults to `private`; omitted request privacy uses that setting. Verify OAuth and perform a private test upload before public publishing.
- Use a strong API key in production; do not expose the database or internal service ports publicly.
- The Compose template expects the existing external Docker network `friday_mesh` and persistent volumes.
- Render concurrency is intentionally conservative for small Oracle Cloud VMs.

## Status
This is the first implementation slice, not a verified 100% production deployment. CI, container build, OAuth, test upload, live mesh connectivity, backup/restore and actual Dokploy deployment still need execution evidence. See [Architecture](docs/ARCHITECTURE.md) and [Roadmap](docs/ROADMAP.md).
