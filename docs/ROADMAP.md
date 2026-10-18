# VyralX Roadmap and Acceptance Gates

This file distinguishes implemented repository capability from external production evidence. Do not mark a milestone complete based solely on code existence.

## Track A — Core service and controls

- [x] FastAPI API, dashboard, health and readiness.
- [x] Source, rights evidence, asset, render, publish and content-pack persistence.
- [x] Additive migrations for new fields on existing volumes.
- [x] API key/Bearer authentication with development-only placeholder bypass.
- [x] Media upload cap, UUID filenames, FFprobe inspection and provenance validation.
- [x] Pydantic request validation for schedule timezone, trim duration and subtitle ranges.

## Track B — Discovery and content

- [x] YouTube Data API search and engagement metadata.
- [x] Deterministic trend heuristic that never turns candidates into authorized assets.
- [x] Official Pexels API search, file metadata, rights confirmation gate, size-limited import and creator provenance.
- [x] Original script, hook, scene plan, title, description, tags and thumbnail brief via configured Inference.
- [x] Optional topic-matched IntelX research query with bounded evidence context passed to Inference; graceful degradation when IntelX is not configured/reachable.
- [x] Opt-in private Memora context retrieval for continuity plus compact completion summaries with idempotency key, receipt/status, and manual retry endpoint; both are disabled by default pending live credential/namespace validation.
- [x] Optional voiceover synthesis through a compatible configured TTS endpoint.
- [x] Verify the source-level Inference task route, Universal Task Envelope, successful result fields, IntelX query route, and Memora search/write/auth contracts against the current peer repositories (see `docs/INTEGRATIONS.md`).
- [ ] Validate live Inference runtime credentials/model/provider output and the configured TTS model on the deployed FRIDAY mesh.
- [ ] Add source-specific repeat-use license checks and operator-configurable channel strategy.

## Track C — Editing and publish pipeline

- [x] Durable render queue and separate single-worker process.
- [x] Durable topic-to-video projects: optional YouTube trend seed, Inference script, Pexels scene search/import, local narration, timed captions, montage, thumbnail and project polling/retry.
- [x] Shorts, long-form and square presets, pad/crop, trim, SRT captions and optional voiceover.
- [x] Thumbnail extraction and persisted paths.
- [x] Explicit publish request and separate approval before upload.
- [x] Revalidate every montage asset's license evidence at request creation and immediately before upload; append Pexels creator/source credits.
- [x] Official YouTube OAuth token loading and resumable upload path.
- [x] Restart recovery that marks interrupted external uploads uncertain instead of blindly retrying.
- [x] Public views/likes/comments snapshot history.
- [ ] Verify OAuth scope/client, channel permission, quota, private test upload and scheduled publish in the real account.
- [x] Add deterministic project QA for output duration/dimensions, requested audio, narration file/duration, caption file/word coverage/cue timing, thumbnail presence and scene provenance; QA warnings require operator review and never auto-approve.
- [x] Add FFmpeg signal-level scans for sustained black frames and long silence gaps; analysis failures become operator-QA warnings and never auto-approve.
- [x] Add FFmpeg integrated loudness, true-peak, and clipping-sample metrics to production QA; incomplete measurements remain review warnings.
- [x] Add measured phrase/chunk-level caption-to-speech timing for local eSpeak narration; estimated external/cached timings trigger a QA warning.
- [x] Add an optional authenticated word-level forced-alignment adapter with transcript/timing validation and a QA-visible safe fallback; live aligner remains unverified.
- [ ] Add phoneme-level alignment and confirm a channel-specific loudness standard against real rendered samples.
- [ ] Add upload session checkpoint/idempotency support to narrow the uncertain state window further.

## Track D — FRIDAY Universe mesh

- [x] Standard specialist port 8000 and private \`friday_mesh\` Compose topology.
- [x] Durable, idempotent task envelope; polling, cancellation, correlation IDs and machine-readable capability manifest.
- [x] Timeout-bounded generic peer client and peer health probes.
- [x] Optional fail-closed Sentinel policy hook before YouTube upload (disabled by default; the existing Sentinel software-review route is not compatible with the `youtube.publish` request/response contract yet; see `docs/INTEGRATIONS.md`).
- [x] Verify source-level Inference, IntelX, and Memora endpoints and request/response shapes against their current repository revisions (see `docs/INTEGRATIONS.md`).
- [ ] Verify deployed service revisions, private-network reachability, and production credentials for all peers.
- [x] Implement the Memora private search/write client, `vyralx` authentication identity, idempotent completion summaries, nested provenance metadata, and request-shape regression tests.
- [ ] Run the live authenticated Memora search/write/readback test after provisioning the production key and private namespace/ACL.
- [ ] Register VyralX in FRIDAY's live agent manifest only after authenticated contract tests pass.

## Track E — CI, deployment and operations

- [x] Containerized API and worker with non-root user, dropped capabilities, resource caps and heartbeat health.
- [x] CI workflow for Ruff, pytest and Docker build.
- [x] Example environment file and API/architecture/operations documentation.
- [x] Run and fix all CI checks on the latest branch head (Ruff, pytest, Docker image build, and Compose validation passed for the verified head; rerun after subsequent changes).
- [x] Add a strict resolved-Python dependency vulnerability audit to CI; the first green run is required before merge.
- [ ] Add a full-history repository secret scan and HIGH/CRITICAL fixed-vulnerability container scan to CI; keep the gate green on the final release candidate.
- [ ] Pin the container base image by immutable digest and lock resolved application dependencies before immutable production release; investigate and rotate any historical credentials surfaced by secret scanning.
- [ ] Validate the actual external Docker network and Dokploy stack before deploy.
- [ ] Test persistence across recreation, encrypted backup and a successful restore.
- [ ] Profile memory/CPU on the current AMD interim VM and separately on the target ARM VM.

## Production completion definition

Production is verified only when all of the following are evidenced: green CI on the final commit, a successful Docker build, configured secret mounts, readiness healthy with the worker present, provider credentials validated, successful private YouTube test upload, live mesh integration tests, and backup/restore proof. Those environment-dependent gates remain unverified from repository source alone.
