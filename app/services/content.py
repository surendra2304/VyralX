"""Original content generation through FRIDAY's Inference task API."""
from __future__ import annotations

import json
from typing import Any, Literal
from uuid import uuid4

import httpx

from app.config import get_settings

VideoFormat = Literal["shorts", "long"]


def _extract_json(raw: str) -> dict[str, Any]:
    candidate = raw.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    try:
        value = json.loads(candidate)
    except json.JSONDecodeError:
        # Some models add a short preamble despite the JSON-only instruction.
        # Extract one object, then validate every required field below.
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Inference output did not contain a JSON object") from None
        value = json.loads(candidate[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("Inference output must be one JSON object")
    required = {
        "hook", "script", "scene_plan", "voiceover", "caption",
        "title_options", "description", "tags", "thumbnail_brief",
    }
    missing = required.difference(value)
    if missing:
        raise ValueError("Inference output missing fields: " + ", ".join(sorted(missing)))
    if not isinstance(value["scene_plan"], list) or not isinstance(value["title_options"], list):
        raise ValueError("scene_plan and title_options must be arrays")
    if not isinstance(value["tags"], list):
        raise ValueError("tags must be an array")
    value["tags"] = [str(tag).strip()[:100] for tag in value["tags"][:30] if str(tag).strip()]
    value["title_options"] = [str(title).strip()[:100] for title in value["title_options"][:8] if str(title).strip()]
    value.setdefault("fact_check_notes", [])
    value.setdefault("rights_notes", "Review licensing for each third-party asset before publishing.")
    return value


def generate_content_pack(
    topic: str,
    *,
    video_format: VideoFormat = "shorts",
    audience: str = "general audience",
    tone: str = "clear, energetic and factual",
    target_seconds: int = 45,
) -> dict[str, Any]:
    """Use Inference /v1/task/execute to generate original scripts and scene plans."""
    settings = get_settings()
    if not settings.inference_url or not settings.inference_api_key:
        raise RuntimeError("INFERENCE_URL and INFERENCE_API_KEY must be configured")
    if video_format not in ("shorts", "long"):
        raise ValueError("video_format must be shorts or long")
    if not 15 <= target_seconds <= 1800:
        raise ValueError("target_seconds must be between 15 and 1800")

    schema = {
        "hook": "opening hook, one or two sentences",
        "script": "complete original spoken script",
        "scene_plan": [{"timecode": "00:00-00:05", "visual": "visual direction", "on_screen_text": "brief text"}],
        "voiceover": "clean original voiceover text",
        "caption": "caption/subtitle text, plain text",
        "title_options": ["title one", "title two"],
        "description": "YouTube description; no fabricated links or claims",
        "tags": ["topic tag"],
        "thumbnail_brief": "original thumbnail composition brief",
        "fact_check_notes": ["claims the operator should verify"],
        "rights_notes": "reminders about third-party assets and music",
    }
    context = {
        "topic": topic.strip()[:500],
        "format": video_format,
        "target_duration_seconds": target_seconds,
        "audience": audience[:200],
        "tone": tone[:200],
    }
    prompt = (
        "You are VyralX, an original video producer. Create a new script and production plan "
        "for the topic and constraints in the context. Never copy or closely imitate a named "
        "creator's script, copyrighted transcript, lyrics, or an existing video. Do not invent "
        "statistics or factual claims; list uncertain claims in fact_check_notes. Do not assume "
        "that any third-party footage, music, images or clips can be reused. Prefer stock, owned "
        "or explicitly permitted media. Build a compelling hook, clear progression and worthwhile "
        "ending. Fit the target duration and audience. Return one valid JSON object, with no "
        "extra text outside the JSON:\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\nContext:\n"
        + json.dumps(context, ensure_ascii=False)
    )
    url = settings.inference_url.rstrip("/") + settings.inference_generation_path
    envelope = {
        "task_id": "vyralx-content-" + uuid4().hex[:16],
        "source_agent": "vyralx",
        "target_agent": "inference",
        "action": "vyralx.content.generate",
        "payload": {"prompt": prompt, "context": context},
        "priority": "normal",
        "trace_id": "vyralx-" + uuid4().hex[:12],
    }
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.inference_api_key}",
                "X-FRIDAY-API-Key": settings.inference_api_key,
                "X-API-Key": settings.inference_api_key,
                "Content-Type": "application/json",
            },
            json=envelope,
            timeout=settings.inference_timeout_seconds,
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Inference task API returned HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise RuntimeError(f"Inference request failed ({type(exc).__name__})") from None
    except ValueError:
        raise RuntimeError("Inference returned an invalid JSON task response") from None

    status = str(payload.get("status", "")).upper()
    if status not in {"SUCCESS", "COMPLETED"}:
        detail = payload.get("error") or f"Inference task status was {status or 'missing'}"
        raise RuntimeError(str(detail)[:300])
    result = payload.get("result")
    raw_content = result.get("response") if isinstance(result, dict) else None
    if not raw_content and isinstance(payload.get("choices"), list) and payload["choices"]:
        try:
            raw_content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raw_content = None
    if not isinstance(raw_content, str) or not raw_content.strip():
        raise RuntimeError("Inference task succeeded without returning textual JSON content")
    try:
        pack = _extract_json(raw_content)
    except (ValueError, TypeError) as exc:
        raise RuntimeError(f"Inference content did not satisfy the VyralX schema ({type(exc).__name__})") from None

    pack["topic"] = topic.strip()
    pack["format"] = video_format
    pack["target_seconds"] = target_seconds
    pack["provider_model"] = (
        str(result.get("model_used") or settings.inference_model or "auto")
        if isinstance(result, dict) else (settings.inference_model or "auto")
    )
    pack["generated_by"] = "inference"
    pack["requires_editor_review"] = True
    pack["fact_check_passed"] = False
    return pack
