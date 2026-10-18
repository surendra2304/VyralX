"""Bounded normalization for optional IntelX research results."""
from __future__ import annotations

import re
from typing import Any


def _terms(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "from", "that", "this", "how", "work", "works", "report", "research", "summary"}
    return {word for word in re.findall(r"[a-z0-9]{3,}", text.casefold()) if word not in stop}


def normalize_intelx_reports(data: Any, topic: str) -> list[dict[str, Any]]:
    """Normalize bounded reports; mutate list inputs so stored research matches model context."""
    if isinstance(data, list):
        candidates = data
    elif isinstance(data, dict):
        candidates = next((data[k] for k in ("items", "reports", "results", "data") if isinstance(data.get(k), list)), [])
    else:
        return []
    topic_terms = _terms(topic)
    reports = []
    for item in candidates[:30]:
        if not isinstance(item, dict):
            continue
        report_id = str(item.get("report_id") or item.get("id") or item.get("document_id") or "").strip()[:120]
        title = str(item.get("title") or item.get("headline") or item.get("name") or "").strip()[:300]
        summary = str(item.get("summary") or item.get("abstract") or item.get("description") or "").strip()[:1200]
        findings = item.get("key_findings", [])
        findings = [findings] if isinstance(findings, str) else findings
        findings = [str(v).strip()[:500] for v in findings[:5] if str(v).strip()] if isinstance(findings, list) else []
        tags = item.get("tags", [])
        tags = [tags] if isinstance(tags, str) else tags
        tags = [str(v).strip()[:100] for v in tags[:10] if str(v).strip()] if isinstance(tags, list) else []
        if not report_id or not (title or summary or findings):
            continue
        terms = _terms(" ".join([title, summary, *findings, *tags]))
        if topic_terms and terms and not (topic_terms & terms) and (title or len(terms) >= 2):
            continue
        reports.append({
            "report_id": report_id, "title": title,
            "published_at": str(item.get("published_at") or item.get("created_at") or item.get("date") or "")[:80],
            "summary": summary, "key_findings": findings, "tags": tags,
            "source_url": str(item.get("source_url") or item.get("url") or item.get("link") or "")[:2048],
        })
        if len(reports) == 5:
            break
    if isinstance(data, list):
        data[:] = reports
    return reports
