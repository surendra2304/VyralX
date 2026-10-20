# Task 3 next-run instructions — VyralX

1. Read this checkpoint and `docs/RECOVERY.md`; inspect the latest branch head.
2. Obtain CI for the current branch. Run `uv run --frozen --extra dev ruff check app tests scripts` and `uv run --frozen --extra dev pytest tests/test_production_hardening.py`; fix failures without weakening rights validation.
3. Trace `find_repeat_use_blockers` through the final publish gate. Add a regression proving that a previously published source cannot be reused without an explicit reviewed repeat-use decision.
4. Run the full CI suite when practical and update both handoff files with exact run links, test counts, unresolved issues, and the next concrete coding action.
5. Never initiate a real YouTube upload while testing.
