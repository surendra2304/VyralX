# Task 3 checkpoint — VyralX

- Date: 2026-10-21 (Asia/Kolkata)
- Branch: `fix/task-3-pexels-path-traversal`
- Code commits: `bd5015f3c28f23e1c418e8b7e68d9d93b3484690`, `ba4f8ab0f57f47c0dd207db19ab586e98573a85f`
- Checkpoint update commit before this: `6617bf425197da29803346b70ff7d9e17b6daa79`
- Changed: `app/services/rights.py`, `tests/test_pexels_path_validation.py`
- Tests: not run. Laptop runner returned HTTP 404; no CI result is available.
- PR: not created; create-pull-request tool was blocked by OpenAI safety checks.
- Main had advanced by one commit since the branch base at last comparison; reconcile without force-pushing.

The media path validator now performs bounded URL decoding and rejects dot segments, single backslashes, control characters, and over-nested encodings before checking Pexels media/license paths. Regression tests cover normal and traversal-shaped paths. This validates metadata only; it does not grant reuse permission.
