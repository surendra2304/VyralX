# VyralX Roadmap

## Milestone 1 — Foundation
- FastAPI service, SQLite persistence, health/readiness endpoints and operator dashboard.
- Source/rights catalog, media import, FFprobe metadata inspection.
- FFmpeg output presets and persistent render/publish job records.
- YouTube OAuth credential loading and resumable upload implementation, disabled by default.
- Container image, Dokploy-friendly Compose, CI and regression tests.

## Milestone 2 — Local verification and operator setup
- Run CI and fix all test/lint/container-build failures.
- Verify Oracle VM architecture, available RAM/disk, Docker networks and mounted volumes.
- Configure Dokploy environment secrets without committing credentials.
- Complete OAuth consent and verify a private/unlisted test upload.
- Confirm deployment branch so feature pushes cannot unexpectedly replace production.

## Milestone 3 — Agent integrations
- Authenticated, timeout-bounded clients for FRIDAY, IntelX, Inference, Memora and Sentinel.
- Define typed capability contracts and register VyralX in FRIDAY only after health, auth and integration tests pass.
- Use Memora as memory authority; Sentinel policy checks precede privileged publishing actions.
- Add retry/idempotency rules and a durable worker queue.

## Milestone 4 — Content intelligence
- Discover public video metadata and trend signals via permitted APIs/connectors.
- Rank candidates by relevance, freshness, engagement and channel strategy.
- Generate original scripts, voiceovers, captions, titles, descriptions and thumbnail briefs.
- Support source files the operator owns, has licensed, or has explicit permission to republish.
- Keep a provenance ledger and rights status per source/asset.

## Milestone 5 — Production workflow
- Bounded background render workers, cancellation, retries, duplicate detection and upload idempotency.
- YouTube Analytics API reporting and outcome-driven scheduling.
- Backup/restore, metrics, structured logs, rate limits and dependency/security scanning.
- Validate memory and CPU use on the actual Oracle instance before increasing concurrency.

## Completion definition
A codebase is not 100% merely because files exist or CI is configured. Foundation completion requires green CI, a successful container build, API tests, documented configuration, and no known critical security defects. Production completion additionally requires verified OAuth, successful test upload, deployment health, durable storage/backup, and verified FRIDAY mesh integration. Those external conditions cannot be marked complete from source code alone.
