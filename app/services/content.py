"""Original video package generation via the configured Inference gateway."""
from __future__ import annotations

import json
from typing import Any, Literal

import httpx

from app.config import get_settings

VideoFormat = Literal["shorts", "long"]


def _extract_json(raw: str) -> dict[str, Any]:
    value = json.loads(raw.strip())
    if not isinstance(value, dict):
        raise ValueError("Inference output must be one JSON object")
    required = {"hook", "script", "scene_plan", "voiceover", "caption", "title_options", "description", "tags", "thumbnail_brief"}
    missing = required.difference(value)
    if missing:
        raise ValueError("Inference output missing fields: " + ", ".join(sorted(missing)))
    if not isinstance(value["scene_plan"], list) or not isinstance(value["title_options"], list):
        raise ValueError("scene_plan and title_options must be arrays")
    if not isinstance(value["tags"], list):
        raise ValueError("tags must be an array")
    value["tags"] = [str(tag).strip()[:100] for tag in value["tags"][:30] if str(tag).strip()]
    value["title_options"] = [str(title).strip()[:100] for title in value["title_options"][:8] if str(title).strip()]
    return value


def generate_content_pack(
    topic: str,
    *,
    video_format: VideoFormat = "shorts",
    audience: str = "general audience",
    tone: str = "clear, energetic and factual",
    target_seconds: int = 45,
) -> dict[str, Any]:
    """Ask Inference for a new script and production plan, never copied source text."""
    settings = get_settings()
    if not settings.inference_url or not settings.inference_api_key:
        raise RuntimeError("INFERENCE_URL and INFERENCE_API_KEY must be configured")
    if not settings.inference_model:
        raise RuntimeError("INFERENCE_MODEL must be configured for content generation")
    if video_format not in ("shorts", "long"):
        raise ValueError("video_format must be shorts or long")
    if not 15 <= target_seconds <= 1800:
        raise ValueError("target_seconds must be between 15 and 1800")
    system_prompt = (
        "You are VyralX, a video producer. Create original content only. Do not reproduce "
        "or closely imitate a named creator, a copyrighted script, lyrics, or an existing "
        "video transcript. Do not invent factual claims; mark uncertain factual claims for "
        "editor verification. Return only valid JSON with the requested schema."
    )
    schema = {
        "hook": "opening hook, one or two sentences",
        "script": "complete original spoken script",
        "scene_plan": [{"timecode": "00:00-00:05", "visual": "visual direction", "on_screen_text": "brief text"}],
        "voiceover": "clean voiceover text",
        "caption": "caption/subtitle text, plain text",
        "title_options": ["title one", "title two"],
        "description": "YouTube description; no fabricated links or claims",
        "tags": ["topic tag"],
        "thumbnail_brief": "original thumbnail composition brief",
        "fact_check_notes": ["claims the editor should verify"],
        "rights_notes": "reminders about third-party assets and music",
    }
    user_prompt = {
        "topic": topic[:500],
        "format": video_format,
        "target_duration_seconds": target_seconds,
        "audience": audience[:200],
        "tone": tone[:200],
        "requirements": [
            "Make the treatment original and specific to the topic.",
            "Use a hook, clear progression and a concrete ending.",
            "Avoid deceptive engagement bait and unverified statistics.",
            "Scene plan must be feasible for a solo creator or an automated editor.",
            "Do not assume third-party media, music or footage can be reused.",
            "Return the following JSON shape, adapting detail to format.",
            json.dumps(schema),
        ],
    }
    url = settings.inference_url.rstrip("/") + settings.inference_generation_path
    try:
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.inference_api_key}",
                "X-API-Key": settings.inference_api_key,
                "Content-Type": "application/json",
            },
            json={
                "model": settings.inference_model,
                "temperature": 0.65,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": json.dumps(user_prompt, ensure_ascii=False)},
                ],
            },
            timeout=settings.inference_timeout_seconds,
            follow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Inference returned HTTP {exc.response.status_code}") from None
    except httpx.RequestError as exc:
        raise RuntimeError(f"Inference request failed ({type(exc).__name__})") from None
    except ValueError:
        raise RuntimeError("Inference returned an invalid JSON response") from None
    try:
        choices = payload.get("choices", [])
        raw_content = choices[0]["message"]["content"]
        pack = _extract_json(raw_content)
    except (AttributeError, IndexError, KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"Inference response did not match the content-pack contract ({type(exc).__name__})") from None
    pack["topic"] = topic.strip()
    pack["format"] = video_format
    pack["target_seconds"] = target_seconds
    pack["provider_model"] = payload.get("model", settings.inference_model)
    pack["generated_by"] = "inference"
    pack["requires_editor_review"] = True
    return pack
