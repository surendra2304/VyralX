# VyralX Architecture

## Role in the FRIDAY Universe

VyralX is an independent video discovery, production and distribution specialist (the tenth planned service). It owns operational data for source provenance, assets, render jobs, publish requests and outcome snapshots. It is not a replacement for FRIDAY orchestration or Memora's memory authority.

## Runtime topology

- \`vyralx\`: FastAPI control plane, standard specialist port 8000.
- \`vyralx-worker\`: one bounded worker process consuming persistent AgentTask, RenderJob and PublishJob queues.
- A shared mounted data volume holds the SQLite database and worker heartbeat.
- Shared media and render volumes hold uploaded/stock source files, narration, renders and thumbnails.
- Both containers join the existing \`friday_mesh\` bridge; the Compose template has no host port mappings.

The worker is single-process by design. This serializes CPU-heavy FFmpeg renders and avoids competing with FRIDAY's latency-sensitive voice service on the interim ~1 GB RAM VM. Resource limits are conservative and need adjustment only after measured profiling.

## Major components

### Control plane
- \`app/main.py\`: authenticated APIs, operator dashboard, readiness, catalog and job lifecycle.
- \`app/schemas.py\`: Pydantic request validation, including trim/caption ranges, timezone-aware publish schedules and task envelope.
- \`app/security.py\`: supports the FRIDAY mesh's Bearer-token convention and \`X-API-Key\` for operator tooling.

### Discovery and content
- \`app/services/discovery.py\`: public YouTube Data API search and statistics; output is discovery-only.
- \`app/services/trends.py\`: deterministic, bounded heuristic ranking using reach, engagement and recency. It is a prioritization score, not a promise of virality.
- \`app/services/pexels.py\`: official Pexels search/details endpoint and size-limited import of API-returned media files. Source URL, creator, license references and attribution notice are retained.
- \`app/services/content.py\`: Original script and scene-plan generation via the FRIDAY Inference `/v1/task/execute` envelope. Generated factual claims require review.
- \`app/services/voiceover.py\`: optional Inference-compatible narration synthesis.
- \`app/services/captions.py\`: SRT subtitle-file construction.
- \`app/services/thumbnail.py\`: deterministic FFmpeg thumbnail extraction.

### Media production and delivery
- \`app/services/probe.py\`: FFprobe technical inspection.
- \`app/services/renderer.py\`: FFmpeg rendering, trim, crop/pad, captions, voiceover and output validation.
- \`app/services/youtube.py\`: official OAuth token loading and resumable uploads. Credentials are stored only in a private mounted file.
- \`app/services/youtube_analytics.py\`: public video counter snapshots using YouTube Data API.
- \`app/worker.py\`: atomic queue claiming, job processing, restart recovery, status reporting and optional pre-publish Sentinel policy call.

### Task contract and ecosystem boundaries
- \`POST /api/v1/tasks\` is the machine-to-machine task envelope. Caller IDs support idempotent replay; correlation IDs let FRIDAY join logs/steps.
- \`GET /api/agent/manifest\` declares capabilities; \`GET /api/agents/health\` checks configured peers.
- \`app/services/peers.py\` provides timeout-bounded authenticated clients. Actual URLs, routes, request/response models and keys must match the current deployed peer implementation before calling an integration "connected."
- Memora remains the only long-term memory authority. VyralX does not create universal/shared memory copies. An explicit Memora API contract must be used for any future memory exchange.
- Sentinel policy enforcement is disabled by default. When enabled, VyralX fails closed if the configured policy endpoint does not explicitly allow publication.

## Topic-to-video project pipeline

\`VideoProject\` is a durable job record separate from the generic FRIDAY task envelope. \`POST /api/projects\` or a FRIDAY \`project.create\` task queues it. The worker claims it with a conditional state update, generates/reuses its \`ContentPack\`, searches official Pexels results against each scene visual, imports unique MP4 scenes under the stock-download size cap, creates a voiceover (local eSpeak by default), computes approximate weighted subtitle timings, and invokes the FFmpeg montage renderer. A montage strips source audio, normalizes clip dimensions/frame rate, concatenates scenes, burns captions, adds narration, probes output and extracts a thumbnail.

The completed \`RenderJob.options_json\` retains the montage asset IDs. Source-rights validation resolves every referenced asset, not just the first asset displayed as the primary asset. Pexels attribution is propagated into the publish description. A video project can only become publishable through the usual explicit approval gate.

## Main data path

1. YouTube/Pexels discovery yields metadata leads; no rights are inferred.
2. A local or approved Pexels asset enters the source catalog with creator and license/permission evidence.
3. FFprobe verifies technical properties.
4. Original script/scene plan and optional narration are generated through configured Inference endpoints.
5. A durable render job is queued with JSON options (preset, trim, framing, captions, narration reference).
6. Worker renders and probes output; failures become observable job states.
7. A publish request binds one source asset to one exact completed render and remains pending approval.
8. Approved publish jobs are claimed once and sent through official YouTube resumable upload. The worker rechecks provenance and optional Sentinel policy.
9. YouTube video IDs and public view/like/comment counters persist for outcome evaluation.

## State and failure semantics

- Render: \`queued → running → completed|failed\`; explicit retries are bounded.
- Agent task: \`queued → running → completed|failed\`; queued tasks may be cancelled.
- Publish: \`pending_approval → queued → uploading → uploaded|failed\`.
- If a render is interrupted by a worker crash, startup recovery marks it failed so it can be inspected/retried.
- If a remote upload was interrupted while the provider may have accepted it, state becomes \`uncertain\`. No automatic retry is attempted because it could create a duplicate video. An operator reconciles provider state first.
- \`/ready\` checks database connectivity and FFmpeg availability, and in required-worker mode checks a heartbeat freshness window.

## Security and policy

- Write/API endpoints require Bearer token or X-API-Key outside development mode.
- The container runs as non-root, drops Linux capabilities, disables privilege escalation, and has explicit CPU/memory limits.
- FFmpeg and FFprobe use argument lists, never a shell with user text.
- Uploads have extension, size and path constraints; provider imports restrict media URLs to approved HTTPS provider domains.
- Provider exceptions are not returned raw in API responses; logs include error types and job references.
- Source text, transcripts, generated scripts and discovered pages are untrusted content, not system instructions.
- No database port is published. Secrets belong in Dokploy protected environment variables or mounted secret files.
- Publishing defaults to private, remains disabled unless explicitly configured, and requires a distinct approval step.

## Limits not inferred as complete

The code provides generic peer clients and a durable FRIDAY task contract, but the actual peer base URLs/routes/API keys, deployed Docker network name, OAuth/token validity, channel permissions, Inference model compatibility, and Sentinel response schema must be verified against live services. The Compose template targets the interim low-memory AMD host; the intended 2-OCPU/12-GB ARM instance is a separate target and must be tested on its own. Before sustained production operation, migrate SQLite schema management to Alembic and add automated backup/restore verification.
