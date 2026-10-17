# VyralX Operations Runbook

This runbook covers the current repository implementation. It does not claim that the live Oracle Cloud or Dokploy environment has been inspected.

## Local verification

```bash
python -m pip install -e ".[dev]"
ruff check app tests scripts
pytest
docker build -t vyralx:local .
docker compose config
```

Before deploying, confirm that the Docker host has the external `friday_mesh` network expected by `docker-compose.yml`, and that the four named persistent volumes are retained across container replacement.

## Required production configuration

- `APP_ENV=production`
- A long, unique `API_KEY`
- `DATABASE_URL`, `DATA_DIR`, `MEDIA_DIR`, and `RENDER_DIR` pointing to persistent storage
- `YOUTUBE_UPLOAD_ENABLED=false` until OAuth has been validated with a private test upload
- `YOUTUBE_DEFAULT_PRIVACY=private`
- `YOUTUBE_DATA_API_KEY` only if discovery is needed
- OAuth client and token files mounted into the protected secrets directory; never store them in Git

Do not expose port 8010 directly to the public internet. Route requests through the existing authenticated HTTPS ingress. Send `X-API-Key` on protected API routes. Rotate any credential that was accidentally committed or shared.

## API workflow

1. `POST /api/sources` — register a source and its license or permission reference.
2. `POST /api/assets/upload` — upload media you own, are licensed to use, or have explicit permission to republish; pass the registered `source_id`.
3. `POST /api/render` — render an authorized asset with `shorts`, `long`, or `square`.
4. `POST /api/publish` — queue a publish job using both the asset ID and completed render job ID, explicitly confirming rights.
5. `POST /api/publish/{job_id}/execute` — execute the queued upload when publishing is enabled and OAuth is valid.
6. `GET /api/publish` — review job status and the returned YouTube video ID.

`POST /api/discover` returns YouTube discovery leads only. It neither downloads source videos nor verifies that they may be republished. A rights flag without a license name or permission reference is rejected.

## Health and troubleshooting

- `GET /health` checks that the API process responds.
- `GET /ready` reports the service readiness summary and FFmpeg availability.
- `GET /docs` shows the generated OpenAPI documentation.
- For a failed job, inspect service logs and the job record. API errors intentionally avoid returning provider exception details to callers.
- Check GitHub Actions for Ruff, pytest and Docker image build results before deployment.

## Known implementation boundaries

- Persistence currently defaults to SQLite; back up the database and media volumes together. For concurrent multi-instance operation, move to PostgreSQL and add migrations before scaling replicas.
- Rendering runs synchronously in the API process with bounded concurrency. A durable worker queue is a follow-up before high-volume use.
- Peer calls to FRIDAY, IntelX, Inference, Memora and Sentinel are configuration placeholders; authenticated integration contracts, timeout/retry behavior, and integration tests remain follow-up work.
- No live Oracle/Dokploy, OAuth, channel upload, restore drill, or FRIDAY mesh connectivity is asserted by repository CI alone.
