"""Attach visible, clearly unverified research provenance to operator review notes."""
from __future__ import annotations

from typing import Any


def attach_research_review_notes(pack: dict[str, Any], reports: list[dict[str, Any]]) -> dict[str, Any]:
    notes = pack.get("fact_check_notes", [])
    if not isinstance(notes, list):
        notes = []
    evidence = []
    for item in reports:
        if not item.get("report_id"):
            continue
        line = (
            "IntelX source (unverified): " + str(item.get("report_id"))
            + " — " + str(item.get("title") or "Untitled report")
            + " — " + str(item.get("summary") or "")
            + (" — " + str(item.get("source_url")) if item.get("source_url") else "")
        )
        evidence.append(line[:500])
    pack["fact_check_notes"] = (
        evidence + [str(note).strip()[:500] for note in notes if str(note).strip()]
    )[:20]
    return pack
