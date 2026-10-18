# VyralX API

Interactive OpenAPI documentation: \`/docs\`. Health: \`/health\`. Readiness: \`/ready\`. Standard service port inside \`friday_mesh\`: \`8000\`.

Outside development mode, routes under \`/api/*\` accept either \`Authorization: Bearer <API_KEY>\` or \`X-API-Key: <API_KEY>\`.

## FRIDAY task API

| Method | Route | Purpose |
|---|---|---|
| POST | \`/api/v1/tasks\` | Submit a durable task envelope; returns HTTP 202 |
| GET | \`/api/v1/tasks/{task_id}\` | Poll state, correlation ID and result |
| GET | \`/api/v1/tasks\` | List recent task summaries |
| POST | \`/api/v1/tasks/{task_id}/cancel\` | Cancel only a queued task |
| GET | \`/api/agent/manifest\` | Machine-readable VyralX capability list |
| GET | \`/api/agents/health\` | Check configured FRIDAY peer reachability |

The request is \`{task_id?, task_type, input, correlation_id?}\`. A caller-generated \`task_id\` gives idempotent submission: the same ID and normalized payload returns the existing task; a different payload for that ID returns HTTP 409. Task state is stored in the database so a service restart does not erase queued tasks.

Task types:
- \`discover.youtube\`: \`{query, max_results?, order?}\`
- \`discover.pexels\`: \`{query, max_results?, orientation?}\`
- \`content.generate\`: \`{topic, video_format?, audience?, tone?, target_seconds?}\`
- \`content.voiceover\`: \`{content_pack_id}\`
- \`render.create\`: \`{asset_id, preset, trim_start_seconds?, trim_end_seconds?, fit_mode?, subtitle_segments?, content_pack_id?}\`
- \`publish.request\`: \`{asset_id, render_job_id, title, description?, tags?, privacy_status?, scheduled_at?, confirm_rights}\`

Discovery results are leads only. A task can create a pending publish request, but cannot auto-approve or bypass the explicit publish approval route. The authenticated `GET /api/publish` response includes the exact final description (including appended stock credits) and tags. The dashboard shows these details on pending jobs and keeps the approval button disabled until the operator opens the description and checks the review acknowledgement.

## Catalog and production API

| Method | Route | Purpose |
|---|---|---|
| POST | \`/api/discover\` | Search YouTube public metadata and compute heuristic trends |
| POST | \`/api/discover/pexels\` | Search Pexels through its official API |
| POST | \`/api/sources\` | Register source provenance and rights evidence |
| GET | \`/api/sources\` | List the source catalog |
| POST | \`/api/assets/upload\` | Import a local video file and probe it with FFprobe |
| POST | \`/api/assets/import/pexels\` | Download an official Pexels result after license confirmation |
| GET | \`/api/assets\` | List assets |
| POST | \`/api/render\` | Queue trim/layout/caption/voiceover render |
| GET | \`/api/render\` | List render jobs and states |
| POST | \`/api/content/generate\` | Generate an original editable script and scene plan using Inference |
| GET | \`/api/content\` | List stored content packs |
| POST | \`/api/content/{content_id}/voiceover\` | Generate a narration audio file using configured Inference TTS |
| POST | \`/api/thumbnails\` | Extract a thumbnail from a completed render |
| GET | \`/api/thumbnails/{job_id}\` | Download the extracted thumbnail |
| POST | \`/api/publish\` | Create a pending publish request for a completed render; validates YouTube title, description and tag limits before queueing |
| POST | \`/api/publish/{job_id}/execute\` | Approve a reviewed request; worker then uploads if enabled |
| GET | \`/api/publish\` | List publish jobs, including final description and tags for operator review |
| POST | \`/api/jobs/render/{job_id}/retry\` | Requeue a failed render within configured retry limits |
| POST | \`/api/jobs/publish/{job_id}/retry\` | Return a failed upload to pending approval for review |
| POST | \`/api/jobs/publish/{job_id}/resolve\` | Reconcile an upload interrupted in an uncertain state |
| POST | \`/api/analytics/refresh\` | Save public view/like/comment snapshots for VyralX videos |
| GET | \`/api/analytics\` | List stored video performance snapshots |

## End-to-end projects

| Method | Route | Purpose |
|---|---|---|
| POST | \`/api/projects\` | Queue an entire topic-to-video project |
| GET | \`/api/projects\` | List project jobs |
| GET | \`/api/projects/{project_id}\` | Poll project progress and result references |
| POST | \`/api/projects/{project_id}/retry\` | Retry a failed project within the configured attempt limit |
| GET | \`/api/projects/{project_id}/thumbnail\` | Download a generated thumbnail |
| GET | \`/api/render/{job_id}/download\` | Download a completed MP4 |

Project creation asks for a topic, format, duration, scene count (2–4), audience/tone, whether narration is wanted, and explicit Pexels-license confirmation. With `auto_discover_trend=true`, it uses the configured YouTube Data API to choose a public-metadata trend from `trend_query`/`trend_max_results`, stores the seed video provenance, and uses only its title as a prompt topic—never its downloaded media or transcript. It queues the work; it does not keep the API request open. The worker uses Inference for the script, official Pexels APIs for scene sourcing, local eSpeak or configured external TTS for narration, generated SRT captions, FFmpeg montage rendering and thumbnail extraction. Before marking a project complete it verifies duration, dimensions, thumbnail output and the requested audio stream.

Project list/detail responses also return `content_preview.production_qa` after a project render. Its checks cover duration, dimensions, narration presence, caption word coverage and timing, thumbnail output, and scene provenance; warnings are shown in the operator dashboard and never grant automatic publish approval. They also return `scene_sources` for retained scenes, including creator, source URL, license reference, file availability and a server-derived `rights_evidence_check`. Project generation revalidates the official Pexels host/path and license URL before a scene is used in a montage. This is a provenance safeguard only; the operator must still review the actual license and intended-use scope.

On completion, the project response supplies \`primary_asset_id\`, \`asset_ids\`, \`content_pack_id\`, \`render_job_id\` and authenticated download paths. The render's saved \`montage_asset_ids\` are checked individually for rights evidence both when a publish request is created and again immediately before upload. Pexels creator/source attribution is appended to the YouTube description.

Successful topic-to-video projects retain their generated SRT file and expose it through the authenticated `GET /api/projects/{project_id}/captions` endpoint and `captions_download_path` review field. Failed-attempt temporary subtitle files are cleaned up.

## Integration configuration

`GET /api/integrations` reports only whether required provider settings and OAuth files are present for Inference, Pexels, YouTube Data API/upload, TTS, IntelX, Memora, Sentinel, worker and media tools. It never returns credential values and explicitly does not claim that provider connectivity, quota or upload permission has been verified.

## Main API flow

1. Register or discover source metadata.
2. For local media, upload a permitted file with \`source_id\`; for stock footage, review Pexels license and call import with \`confirm_license=true\`.
3. Generate content and optional voiceover if desired.
4. Queue a render. The API returns a job ID immediately; the worker renders, probes the output, persists the path/status and exposes errors.
5. Create a publish request with both the asset and the exact completed render IDs. Confirm rights in the payload.
6. Review the rendered output and metadata; call the approval route. The worker checks rights again and, if configured, calls the Sentinel policy gate before upload.
7. Use job status and analytics endpoints to verify outcomes.

## Important settings

- \`API_KEY\`: strong high-entropy secret in production.
- \`WORKER_REQUIRED=true\`: readiness checks worker heartbeat in Compose.
- \`YOUTUBE_UPLOAD_ENABLED=false\`: explicitly enable only after OAuth is verified and a private test upload succeeds.
- \`YOUTUBE_DEFAULT_PRIVACY=private\`: default privacy; scheduled uploads must use private privacy and a future timezone-aware timestamp.
- \`YOUTUBE_ANALYTICS_ENABLED=false\`: explicitly enable public Data API snapshots after configuring a key.
- \`PEXELS_API_KEY\`: optional official stock-footage adapter.
- \`INFERENCE_URL\`, \`INFERENCE_API_KEY\`, \`INFERENCE_MODEL\`: script generation via an OpenAI-compatible chat endpoint.
- \`INFERENCE_TTS_MODEL\`: separate TTS model; API must support compatible audio output.

Use \`docker compose config\` to validate the Compose file after setting environment variables. The Compose stack assumes the external \`friday_mesh\` network already exists.

## Privacy and rights

No secret belongs in the request body, log or Git history. Public discovery never changes \`rights_verified\`. Pexels import requires an explicit operator license confirmation and retains creator/source metadata. VyralX does not implement unauthorized downloads of YouTube, Instagram, TikTok or other creators' work.

## Provider documentation

- [Pexels API documentation](https://www.pexels.com/api/documentation/)
- [YouTube Data API video upload guide](https://developers.google.com/youtube/v3/guides/uploading_a_video)
- [YouTube resumable uploads](https://developers.google.com/youtube/v3/guides/using_resumable_upload_protocol)
