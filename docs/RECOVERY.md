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
- Do not blindly retry uncertain external side effects, especially YouTube uploads. Follow the upload recovery instructions in Operations.
- A scheduled workflow is an independent monitor, not an always-running AI coding agent. It cannot restart a stopped ChatGPT response or continue unfinished reasoning. A separate persistent worker would need an explicit task queue, durable checkpoints, bounded retries and safe authorization.
