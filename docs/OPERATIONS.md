# VyralX Operations Runbook

This runbook describes the repository implementation; it does not claim that live Oracle Cloud or Dokploy settings have been inspected.

## Local verification

    python -m pip install -e ".[dev]"
    ruff check app tests scripts
    pytest
    docker build -t vyralx:local .
    API_KEY=ci-only-not-a-real-secret docker compose config --quiet

CI repeats Ruff, pytest and the Docker build. Verify the run for the latest commit rather than relying on an earlier run.

## Deployment topology

The Compose file starts three services: vyralx-init runs additive schema setup once, vyralx serves FastAPI on port 8000, and vyralx-worker consumes durable queues. API and worker wait for successful initialization. They share the SQLite database, media, renders and secrets volumes, and join the pre-existing external friday_mesh network. No host port is published. Configure Dokploy's reverse proxy for the intended private ingress and do not expose SQLite or internal APIs publicly.

The interim ~1 GB AMD VM has limited capacity. The stack caps schema init at 96 MB, API RAM at 192 MB and worker RAM at 384 MB, uses one worker process and caps FFmpeg resources. Monitor container memory, queue depth, and render duration before raising limits. Do not use these limits as proof that an untested VM can sustain simultaneous heavy jobs.

## Required production configuration

- APP_ENV=production.
- A unique high-entropy API_KEY.
- Persistent DATABASE_URL, DATA_DIR, MEDIA_DIR and RENDER_DIR.
- WORKER_REQUIRED=true, and worker/data volume shared between API and worker.
- Keep YOUTUBE_UPLOAD_ENABLED=false until OAuth and a private test upload are confirmed.
- YOUTUBE_DEFAULT_PRIVACY=private.
- Mount OAuth client and refreshable token at the exact paths set by YOUTUBE_CLIENT_SECRETS_FILE and YOUTUBE_TOKEN_FILE; store those files in the protected secrets volume.
- Set YOUTUBE_DATA_API_KEY only if YouTube discovery or public statistics are required.
- Set PEXELS_API_KEY only if official Pexels search/import is wanted.
- Set `INFERENCE_URL` and `INFERENCE_API_KEY` for script generation through the verified `/v1/task/execute` contract. Local eSpeak is the default narration provider; external TTS is optional and requires a separately verified compatible service.
- Configure peer URLs and API keys only after verifying each deployed agent's real route and auth convention.
- If Sentinel is made mandatory, configure and integration-test the policy endpoint/response schema first; an unrecognized/deny response blocks upload.

Never paste tokens into GitHub issues/PRs or chat. The Docker build context excludes .env and private secrets via .dockerignore. Rotate credentials if leaked.

## API workflows

### FRIDAY asynchronous tasks
1. Submit an envelope to POST /api/v1/tasks with a stable unique task_id, task_type, input and optional correlation_id.
2. Poll the returned status_url until completed or failed.
3. Reuse the same ID only with the same task type/input to get an idempotent replay. A different payload with the same ID returns HTTP 409.
4. A queued task may be cancelled before the worker claims it.

### Video production and publishing
1. Discover leads with the YouTube or Pexels route. A discovery result never grants reuse rights.
2. Register provenance, or import an authorized local media file. For Pexels, review the provider license and explicitly confirm it during import.
3. Generate an original content pack through Inference and optionally synthesize a voiceover. Store output files on the shared media volume.
4. Queue a render; poll render-job state. A render is only considered complete after FFmpeg exits successfully and FFprobe inspects the output. Project renders also run a bounded FFmpeg black-frame/silence-gap scan; scan failures and detections are surfaced in production QA for operator review.
5. Create a publish request bound to the source asset and its exact render job. In the pending-approval dashboard card, expand and review the final description with appended stock credits, open and inspect the production-QA report when present, verify tags/privacy and the rendered MP4, then check the review acknowledgement before approving. QA warnings do not block publishing automatically, but must be reviewed by the operator; external provider acceptance still requires separate verification.
6. Approve via POST /api/publish/{job_id}/execute. The API and worker revalidate every source before upload; if attribution changes after the review, the job returns to pending approval with a refreshed description and must be reviewed again. Upload only occurs if YOUTUBE_UPLOAD_ENABLED=true, OAuth is valid and the optional Sentinel gate allows it.
7. Refresh public performance snapshots when enabled.

### Topic-to-video projects

1. Confirm the current Pexels license and submit \`POST /api/projects\` with \`confirm_pexels_license=true\`.
2. Poll \`GET /api/projects/{project_id}\`. The worker uses Inference for original content, official Pexels APIs for scenes, local eSpeak with target-aware speed by default for narration, captions from the spoken text, SRT output and FFmpeg montage rendering.
3. A completed project response contains the asset IDs, render-job ID, thumbnail path and MP4 download path. Watch worker memory/disk usage on the small VM and keep stock clip limits conservative.
4. Prepare a publish request using the project primary asset ID and completed render ID. The API and worker verify every montage source and attach Pexels credits; inspect the generated script, fact-check notes, final MP4 and description, then explicitly approve the upload. The dashboard shows whether IntelX was used, not configured, unavailable, returned an error envelope, or had no topic-relevant reports; report IDs remain available for provenance.
5. A failed project can be retried within the attempt limit. Existing valid content-pack/scene records are reused; inspect the error first. The worker marks projects interrupted by a restart as failed rather than claiming an incomplete render succeeded.

Optional Memora read/write is controlled separately by `MEMORA_READ_ENABLED` and `MEMORA_WRITE_ENABLED`; both are off by default. Read-back normalizes list and common JSON-envelope responses, rejects error/malformed responses, and discards records explicitly tagged with another namespace. It is used for continuity, not as verified factual evidence. Write-back validates successful receipts (including common nested envelopes) and never treats a provider error with an ID field as success. Write-back is controlled by `MEMORA_WRITE_ENABLED` and is off by default. Only enable it after configuring and testing a VyralX-scoped `MEMORA_API_KEY`; it writes compact completion summaries to `memora://vyralx/private`, not full scripts. Inspect `memora_memory_status` and use `POST /api/projects/{project_id}/sync-memory` to retry a failed or interrupted write.

Local eSpeak is the default zero-key narration provider in the container. External narration requires \`TTS_PROVIDER=external\` and a tested \`INFERENCE_TTS_URL\` plus model/key configuration. The standard Inference task API does not provide a TTS route.

## State recovery

- /health only confirms the API process is responding.
- /ready checks DB connectivity and FFmpeg; with WORKER_REQUIRED=true, it also verifies fresh worker heartbeat.
- RenderJob left in running after a worker restart becomes failed. Inspect logs/output and use a bounded retry if safe.
- PublishJob left in uploading becomes uncertain. The provider may have accepted the upload. Check YouTube Studio/API state and then call the resolve endpoint with uploaded plus a video ID, or not_uploaded only after confirming no video exists. Never blindly repeat an uncertain upload.
- A task left running after restart becomes failed; submit a new task after checking possible side effects.
- Failed render/upload jobs retain an error description and attempt count.

## Validation before claiming production complete

- Latest PR/head CI green (Ruff, pytest and Docker build).
- docker compose config succeeds with deployment environment variables set.
- Actual friday_mesh network, volume ownership, secrets mounts and reverse-proxy route confirmed in Dokploy.
- /ready returns 200 with the worker running.
- Inference script and TTS endpoints verified against the deployed Inference implementation.
- A private YouTube test upload succeeds and the returned video ID can be read back.
- FRIDAY task envelope works through the actual FRIDAY service with expected auth, request shape and status polling.
- Sentinel policy behavior and Memora integration tested against their actual deployed contracts (not guessed).
- Persistence survives container recreation and a backup restore has been demonstrated.

Repository CI cannot prove live credentials, external APIs, Oracle resources, real channel permissions, live FRIDAY mesh connectivity, or backup restoration.
