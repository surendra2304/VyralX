# VyralX interruption recovery

This runbook is the durable handoff point when a ChatGPT session, browser, network connection, or implementation run stops unexpectedly. GitHub is the source of truth; do not assume that an interrupted chat will resume itself.

## Automated recovery signals

- .github/workflows/ci.yml runs lint, tests, container build, Compose validation and dependency audit.
- .github/workflows/recovery-watch.yml reconciles the latest completed main CI run when CI completes, hourly, and on manual dispatch.
- If the latest completed main CI run failed or was cancelled, the watcher opens or updates one incident issue with the run link and recovery checklist.
- Once a later main CI run succeeds, the watcher comments on and closes the incident automatically.
- The watcher does not deploy, alter secrets, push code, or blindly rerun a failing workflow. A test or build failure usually needs diagnosis and a code fix.
- GitHub issue notifications depend on repository watch/subscription settings. Watch the repository with an appropriate notification level if you want GitHub to alert you.

## Resume implementation after a chat interruption

1. Open the repository main branch and inspect the latest commit.
2. Check open pull requests and Actions runs. Identify the branch/PR and exact commit last touched.
3. Read the PR description, changed files, latest workflow run, and its first failing step. Do not duplicate work already committed.
4. Continue from the existing feature branch when safe; otherwise create a new branch from current main and bring over only the needed changes.
5. Work in coherent milestones. Commit related implementation, tests, docs and configuration together; avoid opening a PR for a trivial isolated edit.
6. Before merge, verify the PR head SHA has not changed, review the full diff, and require green CI. Merge only when the feature is coherent and safe.
7. Record the resulting commit/PR, test results, unresolved risks and next concrete task in the PR or issue so another session can continue without relying on chat history.

## Recovery safety rules

- Never commit credentials, OAuth tokens, .env files, private user data or cloud secrets.
- Never assume that a green GitHub workflow proves Oracle Cloud, Dokploy, YouTube OAuth or FRIDAY peer services are healthy; those require live checks.
- Do not blindly retry uncertain external side effects, especially YouTube uploads. Follow the upload recovery instructions in Operations. A publish job in the internal `resumable` state keeps its attempt count and provider session; the worker waits out its 30-second cooldown, then probes YouTube for the authoritative byte offset before sending more data. Jobs in `uncertain` still require manual provider reconciliation.
- A scheduled workflow is an independent monitor, not an always-running AI coding agent. It cannot restart a stopped ChatGPT response or continue unfinished reasoning. A separate persistent worker would need an explicit task queue, durable checkpoints, bounded retries and safe authorization.


## Task 3 engineering checkpoint — 2026-10-20

### Completed source changes
- `app/services/rights.py`: Pexels provenance validates official HTTPS URL authority, rejecting non-official hosts, user-info, non-default TLS ports, malformed ports, and empty paths.
- `app/main.py` and `app/worker.py`: repeat-use history messages now state permission must be currently approved; the worker rechecks that state immediately before upload.
- `tests/test_production_hardening.py`: regression coverage includes invalid Pexels ports/paths and repeat-use history detection.
- `tests/test_app.py`: API coverage proves prior-upload history is blocked until an explicit review is recorded. A new integrated regression approves a publish, revokes its repeat-use permission through the API, and verifies the worker fails the job without invoking the mocked upload provider.
- `tests/test_agent_services.py`: worker regression confirms an approved queued publish is stopped when repeat-use history has no current permission review; upload is mocked to fail if called.
- Work branch: `automation/friday-universe-task-3`; head before current uncommitted changes: `c8c2de6`.

### Verification status
- `.venv/bin/pytest tests/test_app.py::test_revoking_repeat_use_after_publish_approval_blocks_worker_upload -q` passed (1 test; one Starlette/httpx deprecation warning).
- `.venv/bin/ruff check app tests scripts` passed; `git diff --check` passed.
- `.venv/bin/pytest -o addopts= --disable-warnings` passed (153 tests, 1 warning, 1.49s).
- `uv` is unavailable in the current runtime; prepared `.venv` executables were used.
- `gh auth status` failed because no GitHub host is authenticated. No PR/Actions status is available; separate publisher must obtain review/CI. No real YouTube upload was performed.

### Exact next actions
1. Trace resumable/uncertain upload retry reconciliation in `app/worker.py` and provider adapters; implement a focused safe improvement and regression ensuring ambiguous provider responses cannot duplicate an upload.
2. Keep provider behavior mocked; test timeout, cancellation, retry, and reconciliation behavior relevant to the change. Never initiate a real YouTube upload.
3. Run `.venv/bin/ruff check app tests scripts`, focused tests, `.venv/bin/pytest -o addopts= --disable-warnings`, and `git diff --check`.
4. Have the separate publisher obtain PR/CI results; do not create or push a PR from this worker.
5. Rewrite `.github/friday-continuation/task-3-checkpoint.md`, `.github/friday-continuation/task-3-next-run.md`, and this section with exact results and the next action.
