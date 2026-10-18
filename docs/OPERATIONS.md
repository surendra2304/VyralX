# VyralX Operations Runbook

This runbook describes the repository implementation; it does not claim that live Oracle Cloud or Dokploy settings have been inspected.

## Local verification

    python -m pip install "uv==0.12.18"
    uv sync --frozen --extra dev --no-editable
    uv run --frozen --extra dev ruff check app tests scripts
    uv run --frozen --extra dev pytest
    docker build -t vyralx:local .
    API_KEY=ci-only-not-a-real-secret docker compose config --quiet

CI runs Ruff, pytest, the Docker build, Compose validation, a strict Python dependency audit, a full-history Gitleaks secret scan, and a Trivy scan of OS and Python-library vulnerabilities in the built image. Trivy gates known fixed HIGH/CRITICAL vulnerabilities and leaves unfixed advisories visible in the scan output; the image must still be assessed before a production release. The container installs the application and then removes packaging-only `setuptools` and `wheel` so vulnerable build tooling is not shipped in the runtime image. GitHub Actions used by CI are pinned to commit SHAs, with version comments for review. Keep those pins current through reviewed dependency update PRs. Scan output and status are available in the latest GitHub Actions run. A clean scan does not prove that historical secrets were never exposed elsewhere; any confirmed credential exposure still requires revocation/rotation.

## Base-image pin and remaining dependency-lock gate

The Dockerfile pins the multi-platform index digest for the Official Python 3.11.17 slim-bookworm image instead of relying on the moving `3.11-slim` tag. See the [Official Python image tag details](https://hub.docker.com/layers/library/python/3.11-slim-bookworm/). Refresh the digest only through a reviewed change followed by the full container vulnerability scan and CI. The multi-platform index lets the runtime select the matching architecture, including x86-64 and ARM64.

Resolved application and development dependencies are recorded in `uv.lock`. CI verifies the lock and runs tests against `uv sync --frozen`; Docker installs the production project from that lock without the dev extra. The lock/sync/image workflows pin uv to `0.12.18` because the strict audit found an advisory against `0.12.10`. The Python base image is pinned by digest and APT uses the immutable Debian Snapshot timestamp `20261017T000000Z` for both Bookworm and its security archive; update that snapshot only through a reviewed change and a clean Trivy scan. Snapshot entries set `Check-Valid-Until: no` because historic archive metadata expires; package signature validation still uses Debian's archive keyring. The image is not yet bit-for-bit reproducible: PEP 517 build-isolation requirements (`setuptools` and `wheel`) are constrained in `pyproject.toml` but are not separately version-locked by `uv.lock`.

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

## Operator-configurable channel strategy

VyralX can apply channel editorial settings to newly generated content without changing the API request. Configure these optional variables in Dokploy:

- `CHANNEL_NAME`: channel/brand name supplied as context.
- `CHANNEL_NICHE`: the channel's focus and positioning.
- `CHANNEL_CONTENT_PILLARS`: comma-separated recurring topics (up to 10 unique values).
- `CHANNEL_AVOID_TOPICS`: comma-separated subjects/approaches to avoid (up to 10 unique values).
- `CHANNEL_BRAND_VOICE`: preferred writing style and personality.
- `CHANNEL_CALL_TO_ACTION`: preferred call to action.
- `CHANNEL_LANGUAGE`: language for user-facing generated content; defaults to English.

Keep settings concise. Text is normalized and bounded before entering model context; list entries are deduplicated and capped. The selected strategy is saved with each generated content pack for auditability. Strategy settings influence editorial generation only: they do not validate facts, confer footage/music rights, bypass editor review or enable publishing. Request-level audience and tone still apply. Existing content packs are not rewritten when settings change.

## Repeat-use source safeguards

Repeat-use is tracked separately from the initial right to use a source. New source records and Pexels imports default to `repeat_use_allowed=false`. The first use follows the existing rights-evidence gate. If the same normalized source URL/source identity appears in a previous VyralX publish job with status `uploaded`, a new publish request is blocked until an operator records a separate repeat-use decision.

For an existing source, use the dashboard's **Review repeat-use permission for an existing source** panel or call `POST /api/sources/{source_id}/repeat-use-review` with `repeat_use_allowed` and an evidence-based `review_notes` of at least 10 characters. The decision is also available when registering/importing a source, and VyralX records a timestamp. If evidence does not allow repeat use, record `repeat_use_allowed=false`; do not check the repeat-use box merely to bypass a block. A changed decision is enforced at publish request time and rechecked by the worker immediately before upload.

The automated check detects prior uploads recorded by VyralX only, after deployment of this feature. It cannot enumerate older videos published outside VyralX or establish what a license legally permits. Operators must inspect the actual license/permission scope; the stored flag and notes are an auditable decision, not legal advice.

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
4. Queue a render; poll render-job state. A render is only considered complete after FFmpeg exits successfully and FFprobe inspects the output. Project renders also run a bounded FFmpeg black-frame/silence-gap scan; scan failures and detections are surfaced in production QA for operator review. The same scan now reports integrated loudness (LUFS), true peak (dBFS), and clipped-sample count when FFmpeg returns complete metrics; missing measurements or values outside the broad review band (-24 to -10 LUFS, true peak at or below -1 dBFS, zero clipped samples) trigger warnings and never auto-approve. Local eSpeak project narration is synthesized in caption-sized chunks so SRT cue boundaries follow measured chunk durations. For more precise timing, VyralX supports an optional authenticated word-level alignment service; when configured, its timestamps are validated against the exact transcript and measured audio duration. External TTS or cached narration can use this service too. If the aligner is unavailable or returns unsafe timestamps, VyralX keeps safe fallback cues and marks QA for operator review. Phrase-level timing is not word-level forced alignment. Confirm channel/platform-specific delivery targets and listen to a real sample before release.
5. Create a publish request bound to the source asset and its exact render job. In the pending-approval dashboard card, expand and review the final description with appended stock credits, open and inspect the production-QA report when present, verify tags/privacy and the rendered MP4, then check the review acknowledgement before approving. QA warnings do not block publishing automatically, but must be reviewed by the operator; external provider acceptance still requires separate verification.
6. Approve via POST /api/publish/{job_id}/execute with JSON body {confirm_review: true} only after reviewing the final render, attribution, privacy/tags, rights and available QA. The API and worker revalidate every source before upload; if attribution changes after the review, the job returns to pending approval with a refreshed description and must be reviewed again. Upload only occurs if YOUTUBE_UPLOAD_ENABLED=true, OAuth is valid and the optional Sentinel gate allows it.
7. Refresh public performance snapshots when enabled.

### Topic-to-video projects

1. Confirm the current Pexels license and submit \`POST /api/projects\` with \`confirm_pexels_license=true\`.
2. Poll \`GET /api/projects/{project_id}\`. The worker uses Inference for original content, official Pexels APIs for scenes, local eSpeak with target-aware speed by default for narration, captions from the spoken text, SRT output and FFmpeg montage rendering.
3. A completed project response contains the asset IDs, render-job ID, thumbnail path and MP4 download path. Watch worker memory/disk usage on the small VM and keep stock clip limits conservative.
4. Prepare a publish request using the project primary asset ID and completed render ID. The API and worker verify every montage source and attach Pexels credits; inspect the generated script, fact-check notes, final MP4 and description, then explicitly approve the upload. The dashboard shows whether IntelX was used, not configured, unavailable, returned an error envelope, or had no topic-relevant reports; report IDs remain available for provenance.
5. A failed project can be retried within the attempt limit. Existing valid content-pack/scene records are reused; inspect the error first. The worker marks projects interrupted by a restart as failed rather than claiming an incomplete render succeeded.

Optional Memora read/write is controlled separately by `MEMORA_READ_ENABLED` and `MEMORA_WRITE_ENABLED`; both are off by default. Memora must register the `vyralx` service identity and configure `VYRALX_API_KEY`; set VyralX's `MEMORA_API_KEY` to the same secret value in the VyralX deployment. VyralX completion writes include `source_type`, `trust_level` and `evidence_refs` both at the request top level and in nested `provenance`, because the Memora write adapter persists those fields from `provenance`. Read-back normalizes list and common JSON-envelope responses, rejects error/malformed responses, and discards records explicitly tagged with another namespace. It is used for continuity, not as verified factual evidence. Write-back validates successful receipts (including common nested envelopes) and never treats a provider error with an ID field as success. Write-back is controlled by `MEMORA_WRITE_ENABLED` and is off by default. Only enable it after configuring and testing a VyralX-scoped `MEMORA_API_KEY`; it writes compact completion summaries to `memora://vyralx/private`, not full scripts. Inspect `memora_memory_status` and use `POST /api/projects/{project_id}/sync-memory` to retry a failed or interrupted write.

Local eSpeak is the default zero-key narration provider in the container. External narration requires \`TTS_PROVIDER=external\` and a tested \`INFERENCE_TTS_URL\` plus model/key configuration. The standard Inference task API does not provide a TTS route.

### Optional word-level caption alignment

Set CAPTION_ALIGNMENT_URL to the base URL of a trusted private alignment service and CAPTION_ALIGNMENT_API_KEY to its high-entropy key. CAPTION_ALIGNMENT_PATH defaults to /v1/align, CAPTION_ALIGNMENT_TIMEOUT_SECONDS defaults to 90 (allowed range 1–300), and CAPTION_ALIGNMENT_LANGUAGE defaults to en. Keep the service reachable only from the VyralX private network where possible; credentials belong in the deployment secret store, never in Git.

VyralX sends a multipart POST with audio_file, text, and language fields, authenticated with Bearer and X-API-Key headers. The service should return JSON containing words as a list of objects with word (or text), start, and end in seconds. A response shaped as segments[].words[] is also accepted. One timestamp row per transcript word is required. VyralX verifies word count/order, finite non-overlapping timestamps, and audio bounds, then groups validated word timings into phrase-sized SRT cues.

The adapter does not install or host a speech-alignment model by itself. Keep these settings empty to use existing eSpeak chunk timing; successful word-level alignment appears as word_forced in project QA. Failure is non-fatal but becomes an alignment QA warning. Before production use, test the exact deployed aligner, language/model, timeout and authentication, inspect several rendered SRT/video samples, and confirm that the service does not retain uploaded narration longer than intended.


## State recovery

- /health only confirms the API process is responding.
- /ready checks DB connectivity and FFmpeg; with WORKER_REQUIRED=true, it also verifies fresh worker heartbeat.
- RenderJob left in running after a worker restart becomes failed. Inspect logs/output and use a bounded retry if safe.
- If YouTube returned a video ID but the worker stopped before committing the job state, the private success receipt scoped to the publish-job ID and attempt lets startup recovery finalize that confirmed success.
- If the worker stopped during transfer, a valid private session receipt records the session URI, render-file hash, metadata fingerprint, and last server-confirmed byte offset. Startup recovery moves that job to `resumable`; the worker sends an empty status-probe request, follows YouTube's `Range` header, and continues the same upload attempt from the provider-confirmed offset. The session URI is treated as sensitive and stored with owner-only permissions. Recoverable transport failures retain the session and schedule another attempt after a 30-second cooldown so a stuck provider/network does not hot-loop or starve other jobs.
- An invalid/mismatched checkpoint, changed render/metadata, or unresolved provider outcome remains `uncertain` and requires a check in YouTube Studio/API before resolution. If YouTube returns 404 for an expired session, VyralX starts a new session from byte zero; the official protocol returns the original final response for a completed session.
- Both success and session receipts are removed after the database result is committed or an operator resolves the ambiguous job. Never blindly retry an uncertain upload.
- Protocol reference: [YouTube Data API resumable uploads](https://developers.google.com/youtube/data/guides/using_resumable_upload_protocol).
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


## Interrupted implementation sessions

Use the [interruption recovery runbook](RECOVERY.md) to resume safely from the latest GitHub commit, inspect CI failures, and continue from an existing branch without duplicating work. The scheduled Recovery Watch workflow creates or updates one incident when main CI fails and closes it after a later green run; it does not resume ChatGPT execution or deploy code.

## Read-only mesh preflight

Run `python scripts/mesh_preflight.py` from the repository root before a deployment. The default invocation validates partial/invalid peer configuration and checks `/health` for each configured FRIDAY, Inference, IntelX, Memora, and Sentinel peer. Optional unconfigured peers are reported as skipped; configured optional peers that are unhealthy are warnings. Use `--require-peer NAME` for peers that must be available, and repeat it for multiple peers.

Use active checks only when ready to contact the live service:

```powershell
python scripts/mesh_preflight.py --require-peer intelx --probe intelx
python scripts/mesh_preflight.py --require-peer memora --probe memora
python scripts/mesh_preflight.py --require-peer inference --probe-inference
python scripts/mesh_preflight.py --json
```

The IntelX and Memora probes make authenticated reads only. Memora is queried in `memora://vyralx/private`; this preflight never writes a memory or modifies provider state. When Memora read or write is enabled in VyralX, Memora is automatically treated as required. `--probe-inference` actively generates a short test content pack and discards it, and may consume model/provider quota; it is deliberately opt-in. The report excludes keys, base URLs, response bodies and generated content. Exit code `1` means at least one required/configuration/active-contract check failed; optional peer health warnings do not fail the run.

If `SENTINEL_REQUIRED_FOR_PUBLISH=true`, preflight fails because the currently documented Sentinel software-review endpoint does not satisfy VyralX's `youtube.publish` authorization contract. Keep this flag disabled until a dedicated publish-policy endpoint and its explicit deny/allow responses are implemented and verified. A successful preflight proves only the checks it ran at that time; it does not prove YouTube OAuth/upload permission, deploy correctness, database backup/restore, or end-to-end mesh behavior not explicitly probed.
