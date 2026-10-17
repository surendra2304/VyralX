# VyralX Architecture

## Mission
VyralX is the FRIDAY Universe video workflow agent: discover candidates, track provenance and rights, ingest authorized media, inspect media, render platform-specific variants, publish to YouTube with explicit controls, and record results.

## Service boundaries
- VyralX owns the source catalog, rights evidence references, media assets, render jobs, publish jobs, YouTube video IDs, and workflow status.
- FRIDAY may delegate work to VyralX after authenticated mesh integration.
- IntelX can supply research and source discovery metadata. Discovery never implies permission to download or republish.
- Inference can assist with scripts, hooks, descriptions, captions and title variants when configured.
- Memora is the long-term memory authority; VyralX should store references/outcomes there through approved APIs, not create parallel ecosystem memory.
- Sentinel should review privileged operations once the mesh contract is integrated.
- Dokploy remains the deployment controller.

## Initial data flow
1. Register a source URL and provenance metadata.
2. Verify a license or permission reference.
3. Import an authorized local media file.
4. Probe duration/dimensions using FFprobe.
5. Render a Shorts (9:16), landscape (16:9), or square version using FFmpeg.
6. Create a publish job. Publishing defaults to private and is disabled until explicitly enabled.
7. Upload through the official YouTube Data API with OAuth and resumable upload.
8. Persist YouTube video ID and status for later analytics.

## Security
- All write endpoints require X-API-Key outside development mode.
- Secrets belong in Dokploy environment variables or protected mounted secret files.
- Database, media, and render volumes are persistent; never expose database ports publicly.
- Do not execute shell text from user-controlled fields. FFmpeg is invoked with an argument array.
- Source text and transcripts are untrusted content, never system instructions.
- Rights evidence is required before rendering/publishing. A source URL alone is not proof of rights.
- Public publishing is opt-in; private is the default.
- Keep render concurrency low on small Oracle instances.

## Initial limitations
This is a foundation, not a claim of 100% production readiness. Automated third-party social scraping/downloading adapters, caption generation, music licensing, a durable asynchronous queue, channel analytics, and live FRIDAY/Memora/Sentinel contracts are subsequent milestones. Do not bypass platform access controls or copyright enforcement.
