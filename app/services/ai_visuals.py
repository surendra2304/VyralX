"""Generative AI visual creation service for tailored scene graphics."""
from __future__ import annotations

import logging
from urllib.parse import quote
from uuid import uuid4

import httpx

from app.config import get_settings
from app.services.probe import probe_media

log = logging.getLogger(__name__)

POLLINATIONS_ENDPOINT = "https://image.pollinations.ai/prompt"


def generate_scene_visual(
    prompt: str,
    *,
    width: int = 720,
    height: int = 1280,
    timeout_seconds: float = 35.0,
) -> dict:
    """Generate a custom, photorealistic 720x1280 (9:16) AI visual tailored to the scene script."""
    settings = get_settings()
    dest_dir = settings.media_dir / "ai_scenes"
    dest_dir.mkdir(parents=True, exist_ok=True)
    visual_id = uuid4().hex[:12]
    file_path = (dest_dir / f"ai-visual-{visual_id}.jpg").resolve()

    if dest_dir.resolve() not in file_path.parents:
        raise RuntimeError("Invalid visual destination path")

    clean_prompt = " ".join(prompt.strip().split())
    if not clean_prompt:
        clean_prompt = "futuristic technology cyber network glowing neon"

    enhanced_prompt = f"cinematic 8k photorealistic vertical {clean_prompt}"
    encoded = quote(enhanced_prompt)
    url = f"{POLLINATIONS_ENDPOINT}/{encoded}?width={width}&height={height}&nologo=true&seed=42"

    try:
        with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
            resp = client.get(url)
            if resp.status_code == 402:
                import re
                import time
                match = re.search(r"Retry after (\d+)s", resp.text)
                if match:
                    wait_sec = min(int(match.group(1)) + 1, 15)
                    log.info("Pollinations rate limit cooldown: waiting %ds before retry...", wait_sec)
                    time.sleep(wait_sec)
                    resp = client.get(url)
            if resp.status_code != 200 or len(resp.content) < 1000:
                raise RuntimeError(f"Generative image API returned HTTP {resp.status_code}")
            file_path.write_bytes(resp.content)
    except Exception as exc:
        file_path.unlink(missing_ok=True)
        log.warning("AI visual generation failed for prompt %r: %s", clean_prompt[:60], exc)
        raise RuntimeError(f"Could not generate AI scene visual: {exc}") from exc

    try:
        metadata = probe_media(file_path)
    except Exception as probe_exc:
        file_path.unlink(missing_ok=True)
        raise RuntimeError(f"Generated AI visual failed media probe: {probe_exc}") from probe_exc

    return {
        "visual_id": visual_id,
        "file_path": str(file_path),
        "title": f"AI Visual: {clean_prompt[:80]}",
        "creator": "VyralX Generative Visual Engine",
        "creator_url": "https://vyralx.ai",
        "source_url": f"urn:vyralx:ai-visual:{visual_id}",
        "metadata": {
            "duration_seconds": float(metadata.get("duration_seconds") or 0.04),
            "width": int(metadata.get("width") or width),
            "height": int(metadata.get("height") or height),
        },
    }
