# VyralX

**FRIDAY Universe video production and distribution agent**  
*Discover. Research. Script. Produce. Review. Publish. Measure.*

VyralX is the tenth service planned for the FRIDAY Universe. It runs as an independent service and worker, exposes a machine-readable capability manifest and durable task API, and keeps source rights, media assets, renders, publish approvals, and performance snapshots in its own operational database. Memora remains the ecosystem's only long-term cross-agent memory authority.

## Implemented capabilities

- **FRIDAY task envelope:** authenticated \`POST /api/v1/tasks\`, durable queue, task polling/listing/cancellation, correlation IDs, and idempotent replay when the same task ID and payload are reused.
- **Discovery:** YouTube Data API search with view/like/comment metadata and heuristic trend scoring; official Pexels stock video search with creator, file choices and license links.
- **Content intelligence:** the real FRIDAY Inference Universal Task API (`/v1/task/execute`) that generates an original script, hook, scene plan, voiceover text, title variants, description, tags, thumbnail brief and fact-check notes.
- **Stock media import:** official Pexels video detail/download flow, size limits, FFprobe inspection, attribution metadata and explicit license confirmation. Search results remain unverified leads until import is confirmed.
- **Media library:** chunked local upload, source/creator/license/permission provenance, metadata inspection and persistent asset records.
- **Production:** FFmpeg Shorts (9:16), landscape (16:9) and square presets; trim ranges, pad or crop, SRT caption burn-in, optional generated narration, and thumbnail extraction.
- **Durable worker:** separate worker container, conditional job claims, persistent status/error/attempt timestamps, bounded resource use, heartbeat-based readiness, retry endpoints, and restart recovery. Interrupted uploads become \`uncertain\` and are never blindly repeated.
- **Publishing:** official YouTube OAuth credentials and resumable upload; privacy defaults to private; scheduled publish requires a future timezone-aware time; upload is disabled unless explicitly enabled; publishing requires a separate approval step and verified source evidence.
- **Governance:** optional fail-closed Sentinel policy check, source rights gate, no arbitrary command execution, Bearer or X-API-Key authentication, no provider secrets returned in API error bodies.
- **Learning loop:** stored YouTube view/like/comment snapshots and engagement ratios for VyralX-published videos.
- **Operations:** health/readiness, agent peer health, OpenAPI docs, Docker Compose stack, tests and GitHub Actions for lint, tests and Docker build.

## Architecture

\`\`\`text
FRIDAY
  | Bearer-token task envelope + correlation ID
  v
VyralX API (:8000) ------ shared volume/database ------ VyralX Worker
  |                                                        |
  +-- YouTube Data API: discovery/metrics                  +-- FFmpeg/FFprobe
  +-- Pexels API: stock search/import                      +-- render jobs
  +-- Inference API: original script / voiceover            +-- approved YouTube uploads
  +-- optional Sentinel policy gate
  +-- Memora remains the cross-agent long-term memory authority
\`\`\`

The Compose template attaches both containers to the existing \`friday_mesh\` network and publishes no database or API port directly to the host. It expects Dokploy to manage secrets and the reverse proxy.

## Quick start (local development)

Requirements: Python 3.11+, FFmpeg/FFprobe.

\`\`\`bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
pytest
ruff check app tests scripts
\`\`\`

Visit \`http://127.0.0.1:8000\` for the operator dashboard and \`http://127.0.0.1:8000/docs\` for interactive API docs. Development can bypass the placeholder key only when \`APP_ENV=development\`; never expose that mode to the internet.

## FRIDAY task contract

In production, send \`Authorization: Bearer $VYRALX_API_KEY\` or \`X-API-Key: $VYRALX_API_KEY\`. Use a stable caller-generated \`task_id\` when retrying submission; reusing the same ID with a different type or payload returns HTTP 409.

Example task:

\`\`\`json
{
  "task_id": "topic-research-2026-001",
  "task_type": "content.generate",
  "correlation_id": "friday-conversation-or-workflow-id",
  "input": {
    "topic": "How solar panels work",
    "video_format": "shorts",
    "audience": "general audience",
    "tone": "clear, energetic and factual",
    "target_seconds": 45
  }
}
\`\`\`

Submit to \`POST /api/v1/tasks\`, then poll the returned \`status_url\`. Supported task types are \`discover.youtube\`, \`discover.pexels\`, \`content.generate\`, \`content.voiceover\`, \`render.create\`, and \`publish.request\`. A publish task only creates a pending-approval job; it does not bypass human approval.

The stable machine-readable contract is at \`GET /api/agent/manifest\`. Peer health is available at \`GET /api/agents/health\`. Peer base URLs and API keys remain unconfigured until set in Dokploy.

## Direct API workflow

1. Discover candidates through \`POST /api/discover\` or \`POST /api/discover/pexels\`.
2. Generate an original script through \`POST /api/content/generate\`; generate its narration with \`POST /api/content/{content_id}/voiceover\` when an Inference TTS model is configured.
3. Import a local file you have rights to, or import a Pexels stock clip after reviewing the license and setting \`confirm_license=true\`.
4. Queue a render through \`POST /api/render\`; the worker processes it. Poll \`GET /api/render\` for status.
5. Create a publish request via \`POST /api/publish\` and inspect the completed render and metadata.
6. Approve the reviewed request via \`POST /api/publish/{job_id}/execute\`. The worker uploads only if YouTube upload is enabled.
7. Refresh public performance counters with \`POST /api/analytics/refresh\` after enabling \`YOUTUBE_ANALYTICS_ENABLED\`.

A discovered public link is not permission to download or republish someone else's work. VyralX does not implement unauthorized YouTube/Instagram/TikTok ripping or access-control bypass. Use stock media through its official API, owned content, or media backed by explicit permission.

## Configuration

Start with \`.env.example\`. Main integrations:

- \`YOUTUBE_DATA_API_KEY\`: YouTube video discovery and public performance statistics.
- \`YOUTUBE_CLIENT_SECRETS_FILE\` and \`YOUTUBE_TOKEN_FILE\`: OAuth client and token paths, which must remain private.
- \`YOUTUBE_UPLOAD_ENABLED=false\`: keep disabled until OAuth and a private test upload are verified.
- \`PEXELS_API_KEY\`: optional official stock-footage search/import.
- \`INFERENCE_URL\`, \`INFERENCE_API_KEY\`, \`INFERENCE_MODEL\`: OpenAI-compatible generation API.
- \`INFERENCE_TTS_MODEL\` and related TTS settings: optional narration generation. The configured gateway must support the documented compatible request format.
- \`SENTINEL_REQUIRED_FOR_PUBLISH=false\`: when enabled, a configured Sentinel peer and the correct deployed policy path are required, and the gate fails closed.
- \`WORKER_REQUIRED=true\` in Compose: readiness fails if the worker heartbeat is missing or stale.
- \`API_KEY\`: must be a unique high-entropy secret for any non-development deployment.

Generate a local YouTube OAuth token with \`python scripts/authorize_youtube.py\` using the intended channel account. Transfer it securely to the protected secrets volume; never commit the token or client JSON. Upload requires the official Google Data API and proper OAuth consent. Refer to [Google's upload guide](https://developers.google.com/youtube/v3/guides/uploading_a_video).

## Run in Docker / Dokploy

The Compose file starts \`vyralx\` and \`vyralx-worker\` with shared persistent volumes for the database, media, renders and mounted secrets. It expects a pre-existing external \`friday_mesh\` Docker network. Use Dokploy environment variables/secret mounts; do not add credentials to Git. The resource limits are conservative for the interim ~1 GB AMD VM; render and worker pressure must be measured before increasing limits. The API and worker need write access to the shared media/data volumes.

No deployment or live OAuth test is performed by CI. The stack configuration must be reconciled against the actual Dokploy project, actual network name, mounted secret paths, reverse-proxy rules and hardware before deploying.

## Current limitations (explicit)

- The repository provides authenticated generic peer clients and a FRIDAY task contract, but live FRIDAY/IntelX/Memora/Sentinel routes and authorization keys must be verified against those deployed repositories before claiming mesh integration is complete.
- Content generation and speech synthesis need a compatible configured Inference endpoint/model; these are not mocked as live in production.
- YouTube OAuth/token validity, upload quota, channel policy and private test upload must be verified against the real channel.
- This branch adds additive SQLite migrations for existing volumes; large-scale schema evolution should move to Alembic before broad rollout.
- Analytics currently tracks Data API public counters, not private channel retention/impression metrics (which require the relevant authorized YouTube Analytics API scopes).
- CI provides evidence only when its actual run is green; Docker build and workflow status are not inferred from the presence of files.

See [API](docs/API.md), [Architecture](docs/ARCHITECTURE.md), [Operations](docs/OPERATIONS.md), and [Roadmap](docs/ROADMAP.md).
