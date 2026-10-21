# FRIDAY Universe Integration Contract Review

**Reviewed:** 2026-10-18  
**Scope:** Source-code contract review only. A matching route in a repository does not prove the deployed service, secret values, DNS/network path, model/provider, namespace grants, or live account is configured correctly.

## Source revisions reviewed

| Service | Repository revision |
|---|---|
| VyralX | [`bcaafa9d92c887f7a0b01b15a26039d41a795c30`](https://github.com/surendra2304/VyralX/commit/bcaafa9d92c887f7a0b01b15a26039d41a795c30) |
| Inference | [`5f02062b4822871eea2ab9463c4bf26989d79bd9`](https://github.com/surendra2304/Inference/commit/5f02062b4822871eea2ab9463c4bf26989d79bd9) |
| IntelX | [`c236a6bbef8a9d4fa090968ec941fab865d2491d`](https://github.com/surendra2304/IntelX/commit/c236a6bbef8a9d4fa090968ec941fab865d2491d) |
| Memora | [`4e744cdf9ae6f4756c51a36bffbbc86ab14684a2`](https://github.com/surendra2304/Memora/commit/4e744cdf9ae6f4756c51a36bffbbc86ab14684a2) |
| Sentinel | [`a710963424b43589f89bdf75776b3b6027d4ca1c`](https://github.com/surendra2304/Sentinel/commit/a710963424b43589f89bdf75776b3b6027d4ca1c) |

## Verified source contracts

### Inference — source contract matches

- **Route:** `POST /v1/task/execute`, declared in Inference's `app/api/universal_task_routes.py` and mounted at the application root.
- **Authentication:** The route is mounted with `require_inference_api_key`. That dependency accepts `X-INFERENCE-API-KEY`, `X-API-Key`, `X-FRIDAY-API-Key`, or `Authorization: Bearer <key>`. VyralX sends bearer, `X-API-Key`, and `X-FRIDAY-API-Key` values.
- **Request:** Universal Task Envelope fields include `task_id`, `source_agent`, `target_agent`, `action`, and `payload`. VyralX sends its prompt/context inside `payload`.
- **Response:** Inference returns `TaskResultModel`. Successful responses use `status: "SUCCESS"` and put generated text in `result.response`, with `result.model_used`. Degraded/error statuses are not successful content.
- **Still unverified:** Whether the deployed URL/key reaches the same revision, whether a production model/provider returns usable JSON, and whether the configured TTS route/model is compatible. VyralX's TTS option is separate from this task endpoint.

References: [Inference task route](https://github.com/surendra2304/Inference/blob/5f02062b4822871eea2ab9463c4bf26989d79bd9/app/api/universal_task_routes.py), [VyralX client](https://github.com/surendra2304/VyralX/blob/bcaafa9d92c887f7a0b01b15a26039d41a795c30/app/services/content.py).

### IntelX — source contract matches

- **Route:** `GET /api/v1/research/query`, formed by IntelX's `/api/v1` router plus `research_query_router`.
- **Query:** `sector`, optional `start`/`end`, and `limit` (1–50). VyralX sends the project topic as `sector` and requests up to five reports.
- **Authentication:** IntelX's research endpoint uses `get_current_api_key`, accepting `Authorization: Bearer <key>` or `X-API-Key`; the key must exist, be unrevoked, and be seeded/registered in IntelX's key store. Merely setting VyralX's env var is not sufficient by itself.
- **Response:** A list of reports containing `report_id`, `asset_or_sector`, `published_at`, `summary`, `key_findings`, `sentiment_score`, `volatility_impact_factor`, and `tags`. VyralX normalizes and relevance-filters these records before passing bounded context to Inference.
- **Still unverified:** Runtime key provisioning, service reachability, database-backed report availability, and whether any result is relevant to a live topic.

References: [IntelX route](https://github.com/surendra2304/IntelX/blob/c236a6bbef8a9d4fa090968ec941fab865d2491d/intelx/api/v1/futuris.py), [IntelX auth](https://github.com/surendra2304/IntelX/blob/c236a6bbef8a9d4fa090968ec941fab865d2491d/intelx/core/auth.py), [VyralX research client](https://github.com/surendra2304/VyralX/blob/bcaafa9d92c887f7a0b01b15a26039d41a795c30/app/services/project_pipeline.py).

### Memora — source contract matches; production provisioning is separate

- **Search:** `GET /v1/memories/search` with `q`, `namespace_path=memora://vyralx/private`, `limit`, and `min_score`. The source route returns a list of hybrid-search result objects.
- **Write:** `POST /v1/memories` with `content_text`, `target_namespace_path`, an idempotency key, and bounded project-completion metadata. Memora consumes provenance fields from nested `provenance`; VyralX sends `source_type`, `trust_level`, and `evidence_refs` at both the top level and inside `provenance`.
- **Identity and credentials:** Memora now maps `X-Agent-Name: vyralx` to `VYRALX_API_KEY`. Its API requires the agent name and a matching `X-API-Key` or bearer credential. Configure the same secret value as `VYRALX_API_KEY` in Memora and `MEMORA_API_KEY` in VyralX. No secret value belongs in Git.
- **Namespace:** The `vyralx` service identity and `memora://vyralx/private` namespace must exist in the live database. Code seeding does not automatically mutate the running deployment.
- **Still unverified:** The production secret is configured on both services, the identity/namespace is provisioned, ACL policy permits the caller, and a live authenticated read/write round trip succeeds. Read/write features remain off by default.

References: [Memora router](https://github.com/surendra2304/Memora/blob/4e744cdf9ae6f4756c51a36bffbbc86ab14684a2/apps/api/routers/v1_memories.py), [Memora authentication](https://github.com/surendra2304/Memora/blob/4e744cdf9ae6f4756c51a36bffbbc86ab14684a2/apps/api/dependencies.py), [VyralX peer client](https://github.com/surendra2304/VyralX/blob/bcaafa9d92c887f7a0b01b15a26039d41a795c30/app/services/peers.py).

## Sentinel publish gate — source contract wired; live rollout pending

When enabled, VyralX calls `POST /api/v1/vyralx/publish-policy` and expects an explicit `allowed: true` or `decision: "allow"/"approved"`. It sends the policy request fields required by the dedicated Sentinel contract: `job_id`, `asset_id`, `title`, `privacy_status`, `scheduled_at`, `operator_review_acknowledged`, and `rights_verified`. The approval assertion is derived from the recorded `approved_at` timestamp; the rights assertion is true only after the primary source and every source in the render have verified rights evidence and repeat-use checks passed. Missing approval or source-rights evidence must deny publication.

The dedicated authenticated, default-deny endpoint is under [Sentinel PR #4](https://github.com/surendra2304/Sentinel/pull/4), which is **open and not merged** as of this revision. Sentinel's current `main` still exposes `POST /api/v1/friday/gate/review`, a software delivery/review gate; do not point VyralX at that incompatible endpoint. VyralX defaults to the dedicated path but leaves `SENTINEL_REQUIRED_FOR_PUBLISH=false`. Keep the gate disabled until Sentinel PR #4 is accepted and deployed, shared credentials are configured in the secret store, and authenticated default-deny/allow contract tests pass against the live private network.

Sentinel's `rights_verified` field is an assertion from VyralX after its local checks; Sentinel does not independently establish media licensing or human review. The Sentinel policy endpoint returns a decision only and never uploads media.

References: [VyralX publish worker](https://github.com/surendra2304/VyralX/blob/feat/mesh-preflight/app/worker.py), [Sentinel publish policy contract](https://github.com/surendra2304/Sentinel/blob/feat/vyralx-publish-policy-endpoint/docs/VYRALX_PUBLISH_POLICY.md).

### Echo — Notification and Event Dispatch
- **Route:** `POST /v1/notifications`
- **Authentication:** `Authorization: Bearer <ECHO_API_KEY>`, `X-API-Key: <ECHO_API_KEY>`, `X-Agent-Name: vyralx`.
- **Events:** `video.rendered`, `video.published`, `video.publish_pending`, `video.failed`.
- **Payload:** `source_agent`, `event_type`, `title`, `severity`, `timestamp`, `correlation_id`, `details`.
- **Graceful Degradation:** When Echo is unconfigured or unreachable, notifications are safely logged without interrupting render or publish pipelines.

### MediaX — Central Asset Catalog & Registration
- **Route:** `POST /v1/assets/register`
- **Authentication:** `Authorization: Bearer <MEDIAX_API_KEY>`, `X-API-Key: <MEDIAX_API_KEY>`, `X-Agent-Name: vyralx`.
- **Payload:** `source_agent`, `internal_asset_id`, `file_path`, `file_size_bytes`, `media_category` (e.g. `video_render`), `metadata` (duration, format, sha256).
- **Graceful Degradation:** When unconfigured, local asset storage functions independently.

### DataX — Operational Telemetry & Analytics Hub
- **Route:** `POST /v1/telemetry/ingest`
- **Authentication:** `Authorization: Bearer <DATAX_API_KEY>`, `X-API-Key: <DATAX_API_KEY>`, `X-Agent-Name: vyralx`.
- **Payload:** `source_agent`, `metric_type` (e.g. `render_benchmark`, `publish_success`, `audio_loudness`), `measurements`, `project_id`, `correlation_id`.
- **Graceful Degradation:** Bypassed safely if DataX telemetry is disabled.

### Gatekeeper — Perimeter Authorization & Gateway
- **Route:** `POST /v1/auth/verify`
- **Authentication:** Cross-agent mutual authentication and capability verification.
- **Graceful Degradation:** If Gatekeeper is unconfigured, permits local operation with internal token verification fallback.

### Peer Health Discovery (`GET /api/peers`)
- Reports live configuration and connectivity status across all 9 FRIDAY Universe agents:
  `friday`, `inference`, `intelx`, `memora`, `sentinel`, `echo`, `mediax`, `datax`, `gatekeeper`.

## Deployment acceptance checklist

- [ ] Verify private-network DNS/port connectivity for the actual Compose/Dokploy services.
- [ ] Confirm each deployed image/commit matches the revisions tested above.
- [ ] Configure production credentials in the appropriate secret store; never paste or commit key values.
- [ ] Run authenticated smoke tests for Inference, IntelX, and Memora from the deployed VyralX network. Verify Memora search and idempotent write/readback in the private namespace.
- [ ] Before enabling Sentinel gating, implement and test a purpose-built `youtube.publish` policy endpoint and its deny/error behavior.
- [ ] Test the real YouTube OAuth client with a private test upload and manually reconcile upload uncertainty.
- [ ] Verify health/readiness, worker heartbeat, restart persistence, and backup/restore on the deployed VM.

A green CI pipeline proves source-level tests and container build only. It does not satisfy these live deployment gates.
