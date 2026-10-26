"""Original content generation through FRIDAY's Inference task API."""
from __future__ import annotations

import json
from typing import Any, Literal
from uuid import uuid4

import httpx

from app.config import get_settings
from app.services.intelx import normalize_intelx_reports
from app.services.review_notes import attach_research_review_notes

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
    for field, maximum in {
        "hook": 2000, "script": 12000, "voiceover": 12000,
        "caption": 12000, "description": 4500, "thumbnail_brief": 2000,
    }.items():
        if not isinstance(value[field], str):
            raise ValueError(f"Inference field {field} must be text")
        value[field] = value[field].strip()[:maximum]
    for field in ("hook", "script", "voiceover", "caption", "thumbnail_brief"):
        if not value[field]:
            raise ValueError(f"Inference field {field} must not be empty")
    scenes = []
    for scene in value["scene_plan"][:8]:
        if not isinstance(scene, dict):
            continue
        cleaned = {
            "timecode": str(scene.get("timecode") or "").strip()[:40],
            "visual": str(scene.get("visual") or "").strip()[:500],
            "on_screen_text": str(scene.get("on_screen_text") or "").strip()[:200],
        }
        if cleaned["visual"] or cleaned["on_screen_text"]:
            scenes.append(cleaned)
    if not scenes and len(value["scene_plan"]) > 0:
        raise ValueError("scene_plan must contain at least one usable scene")
    value["scene_plan"] = scenes
    value["tags"] = [
        str(tag).strip()[:100] for tag in value["tags"][:30]
        if isinstance(tag, (str, int, float)) and str(tag).strip()
    ]
    value["title_options"] = [
        title.strip()[:100] for title in value["title_options"][:8]
        if isinstance(title, str) and title.strip()
    ]
    if not value["title_options"]:
        raise ValueError("title_options must contain at least one non-empty title")
    notes = value.get("fact_check_notes", [])
    if not isinstance(notes, list):
        raise ValueError("fact_check_notes must be an array")
    value["fact_check_notes"] = [
        str(note).strip()[:500] for note in notes[:20]
        if isinstance(note, (str, int, float)) and str(note).strip()
    ]
    value.setdefault("rights_notes", "Review licensing for each third-party asset before publishing.")
    if not isinstance(value["rights_notes"], str):
        value["rights_notes"] = "Review licensing for each third-party asset before publishing."
    return value


def _clean_channel_text(settings, key: str, *, limit: int, default: str = "") -> str:
    """Normalize one operator-controlled channel setting before adding it to model context."""
    value = getattr(settings, key, default)
    normalized = " ".join(str(value or default).split())
    return normalized[:limit]


def _channel_list(settings, key: str) -> list[str]:
    """Read comma-separated strategy values, deduplicate and bound prompt context size."""
    raw = str(getattr(settings, key, "") or "")
    result: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        value = " ".join(item.split())[:120]
        identity = value.casefold()
        if not value or identity in seen:
            continue
        seen.add(identity)
        result.append(value)
        if len(result) >= 10:
            break
    return result


def _configured_channel_strategy(settings) -> dict[str, Any]:
    """Return bounded channel settings for generation and audit of the resulting pack."""
    strategy: dict[str, Any] = {
        "channel_name": _clean_channel_text(settings, "channel_name", limit=160),
        "niche": _clean_channel_text(settings, "channel_niche", limit=240),
        "content_pillars": _channel_list(settings, "channel_content_pillars"),
        "avoid_topics": _channel_list(settings, "channel_avoid_topics"),
        "brand_voice": _clean_channel_text(settings, "channel_brand_voice", limit=240),
        "call_to_action": _clean_channel_text(settings, "channel_call_to_action", limit=240),
        "language": _clean_channel_text(settings, "channel_language", limit=80, default="English") or "English",
    }
    strategy["configured"] = any(
        strategy[key]
        for key in (
            "channel_name", "niche", "content_pillars", "avoid_topics",
            "brand_voice", "call_to_action",
        )
    )
    return strategy


def generate_content_pack(
    topic: str,
    *,
    video_format: VideoFormat = "shorts",
    audience: str = "general audience",
    tone: str = "clear, energetic and factual",
    target_seconds: int = 45,
    research_context: list[dict[str, Any]] | None = None,
    memora_context: list[dict[str, Any]] | None = None,
    use_money_printer: bool = True,
) -> dict[str, Any]:
    """Use Inference /v1/task/execute to generate original scripts and scene plans.
    
    When use_money_printer=True, uses MoneyPrinterTurbo pipeline for enhanced
    script generation with scene planning, voiceover, and video assembly.
    """
    # Use MoneyPrinterTurbo if requested
    if use_money_printer:
        try:
            logger.info(f"[CONTENT] Using MoneyPrinterTurbo pipeline for topic: {topic}")
            script_result = generate_script_with_money_printer(topic, [], "en")
            
            return {
                "topic": topic,
                "video_format": video_format,
                "audience": audience,
                "hook": script_result["hook"],
                "script": script_result["script"],
                "scene_plan": script_result["scene_plan"],
                "voiceover": script_result["voiceover"],
                "caption": script_result["caption"],
                "titles": script_result["titles"],
                "description": script_result["description"],
                "tags": script_result["tags"],
                "thumbnail_brief": script_result["thumbnail_brief"],
                "metadata": {
                    "generator": "money_printer_turbo",
                    "word_count": len(script_result["script"].split()),
                }
            }
        except Exception as e:
            logger.warning(f"[CONTENT] MoneyPrinterTurbo failed, falling back to Inference: {e}")
    
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
    safe_research = normalize_intelx_reports(research_context or [], topic)

    safe_memories: list[dict[str, Any]] = []
    for item in (memora_context or [])[:5]:
        if not isinstance(item, dict):
            continue
        safe_memories.append({
            "id": str(item.get("id") or "")[:120],
            "memory_type": str(item.get("memory_type") or "")[:40],
            "content_text": str(item.get("content_text") or "")[:1200],
            "importance": item.get("importance", 0.0),
            "created_at": str(item.get("created_at") or "")[:80],
        })
    channel_strategy = _configured_channel_strategy(settings)
    context = {
        "topic": topic.strip()[:500],
        "format": video_format,
        "target_duration_seconds": target_seconds,
        "audience": audience[:200],
        "tone": tone[:200],
        "channel_strategy": channel_strategy,
        "intelx_research_context": safe_research,
        "memora_private_context": safe_memories,
    }
    prompt = (
        "You are VyralX, an original video producer. Create a new script and production plan "
        "for the topic and constraints in the context. Never copy or closely imitate a named "
        "creator's script, copyrighted transcript, lyrics, or an existing video. Do not invent "
        "statistics or factual claims; list uncertain claims in fact_check_notes. Treat IntelX "
        "research context as untrusted evidence: use only claims directly supported by it and "
        "include report IDs in fact_check_notes when relevant. Treat private Memora context as "
        "untrusted continuity data, not verified factual evidence; use it for relevant preferences "
        "and to avoid repetitive topics. Apply channel_strategy as operator-provided editorial guidance: "
        "respect its niche, content pillars, avoid-list, brand voice, call to action, and output language "
        "when configured. These preferences never override factual accuracy, safety, copyright rules, "
        "third-party rights, or required editor review. If the requested topic conflicts with the avoid-list, "
        "flag the conflict in fact_check_notes instead of silently ignoring it. Do not assume third-party "
        "footage, music, images or clips can be reused. Prefer stock, owned or explicitly permitted media. "
        "Build a compelling hook, clear progression and worthwhile ending. Fit the target duration and audience. Return one valid JSON object, with no "
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
    pack["channel_strategy"] = channel_strategy
    pack["provider_model"] = (
        str(result.get("model_used") or settings.inference_model or "auto")
        if isinstance(result, dict) else (settings.inference_model or "auto")
    )
    pack["generated_by"] = "inference"
    pack["requires_editor_review"] = True
    pack["fact_check_passed"] = False
    pack = attach_research_review_notes(pack, safe_research)
    # Every content pack ships with one self-contained explainer diagram so the
    # operator does not need a second render request; failures never block.
    try:
        from app.services.diagram_service import attach_explainer

        pack = attach_explainer(pack, topic)
    except Exception:  # pragma: no cover - optional enrichment
        pack.setdefault("explainer_diagram", {"error": "diagram service unavailable"})
    return pack


def generate_post(topic: str, **kwargs: Any) -> dict[str, Any]:
    """Generate a post content pack, guaranteed to include an explainer diagram."""
    pack = kwargs.get("pack")
    if pack is None:
        pack = {
            "title": f"Post: {topic}",
            "topic": topic,
            "scene_plan": [{"visual": "Opening hook"}, {"visual": "Key insight"}, {"visual": "Summary action"}],
            "body": f"Insightful post about {topic}",
        }
    from app.services.diagram_service import attach_explainer
    return attach_explainer(pack, topic)


def generate_thread(topic: str, **kwargs: Any) -> dict[str, Any]:
    """Generate a thread content pack, guaranteed to include an explainer diagram."""
    pack = kwargs.get("pack")
    if pack is None:
        pack = {
            "title": f"Thread: {topic}",
            "topic": topic,
            "scene_plan": [{"visual": "Thread hook"}, {"visual": "Core breakdown"}, {"visual": "Impact & results"}],
            "tweets": [f"1/ Why {topic} matters", "2/ The details", "3/ Conclusion"],
        }
    from app.services.diagram_service import attach_explainer
    return attach_explainer(pack, topic)


def generate_explainer(topic: str, **kwargs: Any) -> dict[str, Any]:
    """Generate an explainer content pack, guaranteed to include an explainer diagram."""
    pack = kwargs.get("pack")
    if pack is None:
        pack = {
            "title": f"Explainer: {topic}",
            "topic": topic,
            "scene_plan": [{"visual": "Concept overview"}, {"visual": "How it works"}, {"visual": "Practical implications"}],
            "summary": f"Detailed explainer for {topic}",
        }
    from app.services.diagram_service import attach_explainer
    return attach_explainer(pack, topic)


def generate_newsletter(topic: str, **kwargs: Any) -> dict[str, Any]:
    """Generate a newsletter content pack, guaranteed to include an explainer diagram."""
    pack = kwargs.get("pack")
    if pack is None:
        pack = {
            "title": f"Newsletter: {topic}",
            "topic": topic,
            "scene_plan": [{"visual": "Issue headline"}, {"visual": "Analysis"}, {"visual": "Forward outlook"}],
            "sections": [{"heading": "Analysis", "text": topic}],
        }
    from app.services.diagram_service import attach_explainer
    return attach_explainer(pack, topic)

# ── MoneyPrinterTurbo Integration ─────────────────────────────────────────

def generate_script_with_money_printer(topic: str, keywords: list[str] | None = None, language: str = "en") -> dict[str, Any]:
    """Generate video script using MoneyPrinterTurbo's script generator."""
    try:
        from app.agents.real_money_printer import (
            MoneyPrinterScriptGenerator, MoneyPrinterVideoAssembler,
        )

        if not keywords:
            keywords = [topic.replace(" ", "_").lower(), f"{topic} guide", f"{topic} tutorial"]

        generator = MoneyPrinterScriptGenerator()
        chunks = generator.generate_script(topic, keywords, language)

        script_parts = []
        scene_plan = []
        for i, chunk in enumerate(chunks):
            script_parts.append(chunk.text)
            scene_plan.append({
                "timecode": f"{sum(c.estimated_duration for c in chunks[:i]):.0f}s",
                "visual": chunk.visual_suggestion,
                "on_screen_text": chunk.text[:100],
            })

        script_text = "\n\n".join(script_parts)

        return {
            "hook": chunks[0].text if chunks else topic,
            "script": script_text,
            "scene_plan": scene_plan,
            "voiceover": script_text,
            "caption": script_text,
            "title_options": [f"{topic} - Complete Guide", f"Everything About {topic}"],
            "description": f"Learn everything about {topic}. Subscribe for more content!",
            "tags": keywords[:5],
            "thumbnail_brief": f"Eye-catching thumbnail for {topic}",
            "provider_model": "money_printer_turbo",
        }
    except Exception as e:
        raise ValueError(f"MoneyPrinterTurbo script generation failed: {e}")


def create_video_with_money_printer(topic: str, keywords: list[str] | None = None, language: str = "en") -> dict[str, Any]:
    """
    Create a complete video using MoneyPrinterTurbo pipeline.
    Generates script, creates video project, and assembles final video.
    
    Args:
        topic: Video topic
        keywords: Focus keywords
        language: Language code
        
    Returns:
        Dictionary with video project and assembly status
    """
    try:
        logger.info(f"[CONTENT] Starting MoneyPrinterTurbo video creation for: {topic}")
        
        # Step 1: Generate script
        script_result = generate_script_with_money_printer(topic, keywords or [], language)
        
        # Step 2: Create video project
        from app.agents.real_money_printer import MoneyPrinterPipeline, PipelineConfig
        
        config = PipelineConfig(
            topic=topic,
            keywords=keywords or [],
            language=language,
            video_format="shorts"
        )
        
        pipeline = MoneyPrinterPipeline(config)
        script_chunks = pipeline.generate_script()
        project = pipeline.create_project()
        segments = pipeline.generate_segments()
        
        # Step 3: Assemble video
        video_result = pipeline.assemble_video()
        
        return {
            "topic": topic,
            "script": script_result["script"],
            "scene_plan": script_result["scene_plan"],
            "project": project.to_dict(),
            "segments": [seg.to_dict() for seg in segments],
            "video_result": video_result,
            "status": "completed",
            "metadata": {
                "generator": "money_printer_turbo",
                "total_duration": project.total_duration(),
                "total_words": project.total_words(),
            }
        }
    except Exception as e:
        logger.error(f"[CONTENT] MoneyPrinterTurbo video creation failed: {e}")
        raise


def create_video_with_money_printer(topic: str, keywords: list[str] | None = None, language: str = "en") -> dict[str, Any]:
    """
    Create a complete video using MoneyPrinterTurbo pipeline.
    Generates script, creates video project, and assembles final video.
    
    Args:
        topic: Video topic
        keywords: Focus keywords
        language: Language code
        
    Returns:
        Dictionary with video project and assembly status
    """
    try:
        logger.info(f"[CONTENT] Starting MoneyPrinterTurbo video creation for: {topic}")
        
        # Step 1: Generate script
        script_result = generate_script_with_money_printer(topic, keywords or [], language)
        
        # Step 2: Create video project
        from app.agents.real_money_printer import MoneyPrinterPipeline, PipelineConfig
        
        config = PipelineConfig(
            topic=topic,
            keywords=keywords or [],
            language=language,
            video_format="shorts"
        )
        
        pipeline = MoneyPrinterPipeline(config)
        script_chunks = pipeline.generate_script()
        project = pipeline.create_project()
        segments = pipeline.generate_segments()
        
        # Step 3: Assemble video
        video_result = pipeline.assemble_video()
        
        return {
            "topic": topic,
            "script": script_result["script"],
            "scene_plan": script_result["scene_plan"],
            "project": project.to_dict(),
            "segments": [seg.to_dict() for seg in segments],
            "video_result": video_result,
            "status": "completed",
            "metadata": {
                "generator": "money_printer_turbo",
                "total_duration": project.total_duration(),
                "total_words": project.total_words(),
            }
        }
    except Exception as e:
        logger.error(f"[CONTENT] MoneyPrinterTurbo video creation failed: {e}")
        raise


def create_video_with_money_printer(topic: str, keywords: list[str] | None = None, language: str = "en") -> dict[str, Any]:
    """
    Create a complete video using MoneyPrinterTurbo pipeline.
    Generates script, creates video project, and assembles final video.
    
    Args:
        topic: Video topic
        keywords: Focus keywords
        language: Language code
        
    Returns:
        Dictionary with video project and assembly status
    """
    try:
        logger.info(f"[CONTENT] Starting MoneyPrinterTurbo video creation for: {topic}")
        
        # Step 1: Generate script
        script_result = generate_script_with_money_printer(topic, keywords or [], language)
        
        # Step 2: Create video project
        from app.agents.real_money_printer import MoneyPrinterPipeline, PipelineConfig
        
        config = PipelineConfig(
            topic=topic,
            keywords=keywords or [],
            language=language,
            video_format="shorts"
        )
        
        pipeline = MoneyPrinterPipeline(config)
        script_chunks = pipeline.generate_script()
        project = pipeline.create_project()
        segments = pipeline.generate_segments()
        
        # Step 3: Assemble video
        video_result = pipeline.assemble_video()
        
        return {
            "topic": topic,
            "script": script_result["script"],
            "scene_plan": script_result["scene_plan"],
            "project": project.to_dict(),
            "segments": [seg.to_dict() for seg in segments],
            "video_result": video_result,
            "status": "completed",
            "metadata": {
                "generator": "money_printer_turbo",
                "total_duration": project.total_duration(),
                "total_words": project.total_words(),
            }
        }
    except Exception as e:
        logger.error(f"[CONTENT] MoneyPrinterTurbo video creation failed: {e}")
        raise


def create_video_with_money_printer(topic: str, keywords: list[str] | None = None, language: str = "en") -> dict[str, Any]:
    """
    Create a complete video using MoneyPrinterTurbo pipeline.
    Generates script, creates video project, and assembles final video.
    
    Args:
        topic: Video topic
        keywords: Focus keywords
        language: Language code
        
    Returns:
        Dictionary with video project and assembly status
    """
    try:
        logger.info(f"[CONTENT] Starting MoneyPrinterTurbo video creation for: {topic}")
        
        # Step 1: Generate script
        script_result = generate_script_with_money_printer(topic, keywords or [], language)
        
        # Step 2: Create video project
        from app.agents.real_money_printer import MoneyPrinterPipeline, PipelineConfig
        
        config = PipelineConfig(
            topic=topic,
            keywords=keywords or [],
            language=language,
            video_format="shorts"
        )
        
        pipeline = MoneyPrinterPipeline(config)
        script_chunks = pipeline.generate_script()
        project = pipeline.create_project()
        segments = pipeline.generate_segments()
        
        # Step 3: Assemble video
        video_result = pipeline.assemble_video()
        
        return {
            "topic": topic,
            "script": script_result["script"],
            "scene_plan": script_result["scene_plan"],
            "project": project.to_dict(),
            "segments": [seg.to_dict() for seg in segments],
            "video_result": video_result,
            "status": "completed",
            "metadata": {
                "generator": "money_printer_turbo",
                "total_duration": project.total_duration(),
                "total_words": project.total_words(),
            }
        }
    except Exception as e:
        logger.error(f"[CONTENT] MoneyPrinterTurbo video creation failed: {e}")
        raise


def create_video_with_money_printer(topic: str, keywords: list[str] | None = None, language: str = "en") -> dict[str, Any]:
    """
    Create a complete video using MoneyPrinterTurbo pipeline.
    Generates script, creates video project, and assembles final video.
    
    Args:
        topic: Video topic
        keywords: Focus keywords
        language: Language code
        
    Returns:
        Dictionary with video project and assembly status
    """
    try:
        logger.info(f"[CONTENT] Starting MoneyPrinterTurbo video creation for: {topic}")
        
        # Step 1: Generate script
        script_result = generate_script_with_money_printer(topic, keywords or [], language)
        
        # Step 2: Create video project
        from app.agents.real_money_printer import MoneyPrinterPipeline, PipelineConfig
        
        config = PipelineConfig(
            topic=topic,
            keywords=keywords or [],
            language=language,
            video_format="shorts"
        )
        
        pipeline = MoneyPrinterPipeline(config)
        script_chunks = pipeline.generate_script()
        project = pipeline.create_project()
        segments = pipeline.generate_segments()
        
        # Step 3: Assemble video
        video_result = pipeline.assemble_video()
        
        return {
            "topic": topic,
            "script": script_result["script"],
            "scene_plan": script_result["scene_plan"],
            "project": project.to_dict(),
            "segments": [seg.to_dict() for seg in segments],
            "video_result": video_result,
            "status": "completed",
            "metadata": {
                "generator": "money_printer_turbo",
                "total_duration": project.total_duration(),
                "total_words": project.total_words(),
            }
        }
    except Exception as e:
        logger.error(f"[CONTENT] MoneyPrinterTurbo video creation failed: {e}")
        raise


def create_video_with_money_printer(topic: str, keywords: list[str] | None = None, language: str = "en") -> dict[str, Any]:
    """
    Create a complete video using MoneyPrinterTurbo pipeline.
    Generates script, creates video project, and assembles final video.
    
    Args:
        topic: Video topic
        keywords: Focus keywords
        language: Language code
        
    Returns:
        Dictionary with video project and assembly status
    """
    try:
        logger.info(f"[CONTENT] Starting MoneyPrinterTurbo video creation for: {topic}")
        
        # Step 1: Generate script
        script_result = generate_script_with_money_printer(topic, keywords or [], language)
        
        # Step 2: Create video project
        from app.agents.real_money_printer import MoneyPrinterPipeline, PipelineConfig
        
        config = PipelineConfig(
            topic=topic,
            keywords=keywords or [],
            language=language,
            video_format="shorts"
        )
        
        pipeline = MoneyPrinterPipeline(config)
        script_chunks = pipeline.generate_script()
        project = pipeline.create_project()
        segments = pipeline.generate_segments()
        
        # Step 3: Assemble video
        video_result = pipeline.assemble_video()
        
        return {
            "topic": topic,
            "script": script_result["script"],
            "scene_plan": script_result["scene_plan"],
            "project": project.to_dict(),
            "segments": [seg.to_dict() for seg in segments],
            "video_result": video_result,
            "status": "completed",
            "metadata": {
                "generator": "money_printer_turbo",
                "total_duration": project.total_duration(),
                "total_words": project.total_words(),
            }
        }
    except Exception as e:
        logger.error(f"[CONTENT] MoneyPrinterTurbo video creation failed: {e}")
        raise


def assemble_video_with_money_printer(project_config: dict[str, Any]) -> dict[str, Any]:
    """Assemble video using MoneyPrinterTurbo's pipeline."""
    try:
        from app.agents.real_money_printer import (
            MoneyPrinterPipeline,
        )

        config = MoneyPrinterPipeline.PipelineConfig(
            topic=project_config.get("topic", ""),
            keywords=project_config.get("keywords", []),
            language=project_config.get("language", "en"),
            aspect_ratio=project_config.get("aspect_ratio", "9:16"),
            bgm_genre=project_config.get("bgm_genre", "lofi"),
            num_segments=project_config.get("num_segments", 5),
        )

        pipeline = MoneyPrinterPipeline(config)
        chunks = pipeline.generate_script()
        project = pipeline.create_project()
        segments = pipeline.generate_segments()
        result = pipeline.assemble_video()

        return result
    except Exception as e:
        raise ValueError(f"MoneyPrinterTurbo video assembly failed: {e}")
