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
- [x] Optional voiceover synthesis through a compatible configured TTS endpoint.
- [ ] Validate actual Inference gateway route/model/response format and TTS model on the deployed FRIDAY mesh.
- [ ] Add source-specific repeat-use license checks and operator-configurable channel strategy.

## Track C — Editing and publish pipeline

- [x] Durable render queue and separate single-worker process.
- [x] Durable topic-to-video projects: Inference script, Pexels scene search/import, local narration, timed captions, montage, thumbnail and project polling/retry.
- [x] Shorts, long-form and square presets, pad/crop, trim, SRT captions and optional voiceover.
- [x] Thumbnail extraction and persisted paths.
- [x] Explicit publish request and separate approval before upload.
- [x] Revalidate every montage asset's license evidence at request creation and immediately before upload; append Pexels creator/source credits.
- [x] Official YouTube OAuth token loading and resumable upload path.
- [x] Restart recovery that marks interrupted external uploads uncertain instead of blindly retrying.
- [x] Public views/likes/comments snapshot history.
- [ ] Verify OAuth scope/client, channel permission, quota, private test upload and scheduled publish in the real account.
- [ ] Add automatic output quality checks for black frames, silence, caption synchronization, aspect ratio and audio clipping.
- [ ] Add upload session checkpoint/idempotency support to narrow the uncertain state window further.

## Track D — FRIDAY Universe mesh

- [x] Standard specialist port 8000 and private \`friday_mesh\` Compose topology.
- [x] Durable, idempotent task envelope; polling, cancellation, correlation IDs and machine-readable capability manifest.
- [x] Timeout-bounded generic peer client and peer health probes.
- [x] Optional fail-closed Sentinel gate before YouTube upload.
- [ ] Validate actual endpoint contracts against deployed FRIDAY, Inference, IntelX, Memora and Sentinel code/configuration.
- [ ] Implement and integration-test a concrete Memora write/search contract; do not store cross-agent long-term memory locally.
- [ ] Register VyralX in FRIDAY's live agent manifest only after authenticated contract tests pass.

## Track E — CI, deployment and operations

- [x] Containerized API and worker with non-root user, dropped capabilities, resource caps and heartbeat health.
- [x] CI workflow for Ruff, pytest and Docker build.
- [x] Example environment file and API/architecture/operations documentation.
- [ ] Run and fix all CI checks on the latest branch head.
- [ ] Run dependency audit and secret scan; pin base image and dependencies before immutable production release.
- [ ] Validate the actual external Docker network and Dokploy stack before deploy.
- [ ] Test persistence across recreation, encrypted backup and a successful restore.
- [ ] Profile memory/CPU on the current AMD interim VM and separately on the target ARM VM.

## Production completion definition

Production is verified only when all of the following are evidenced: green CI on the final commit, a successful Docker build, configured secret mounts, readiness healthy with the worker present, provider credentials validated, successful private YouTube test upload, live mesh integration tests, and backup/restore proof. Those environment-dependent gates remain unverified from repository source alone.
