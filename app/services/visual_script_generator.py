"""VyralX Frame-Grounded Multimodal Vision Script Generator.

Extracts representative keyframes from a video clip and leverages
multimodal LLM vision to analyze exact physical actions, props, people,
and environments before synthesizing an accurate, tightly-synchronized
commentary script.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("vyralx.vision")


@dataclass
class VisualAnalysisResult:
    visual_summary: str
    script: str
    title: str
    cyan_keywords: set[str]
    debate_question: str
    tags: list[str]


def extract_clip_keyframes(video_path: Path, num_frames: int = 4) -> tuple[float, list[Path]]:
    """Extracts evenly spaced keyframes across the video duration using ffmpeg."""
    probe_cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    raw_dur = subprocess.check_output(probe_cmd).decode().strip()
    duration = float(raw_dur)

    # Calculate timestamps (e.g. 15%, 40%, 65%, 88%)
    fractions = [0.15, 0.40, 0.65, 0.88] if num_frames == 4 else [i / (num_frames + 1) for i in range(1, num_frames + 1)]
    timestamps = [duration * f for f in fractions]

    temp_dir = Path(tempfile.gettempdir()) / f"vyralx_frames_{video_path.stem}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    extracted = []
    for idx, ts in enumerate(timestamps):
        out_frame = temp_dir / f"frame_{idx:02d}.jpg"
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-ss", f"{ts:.2f}",
            "-i", str(video_path),
            "-vframes", "1",
            "-q:v", "2",
            str(out_frame)
        ]
        subprocess.run(cmd, check=True)
        if out_frame.exists() and out_frame.stat().st_size > 0:
            extracted.append(out_frame)

    log.info("Extracted %d keyframes for %s (Duration: %.2fs)", len(extracted), video_path.name, duration)
    return duration, extracted


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
        return json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start >= 0 and end > start:
            return json.loads(candidate[start : end + 1])
        raise


def get_inference_config() -> tuple[str, str]:
    """Retrieves Inference gateway URL and API key from settings or environment."""
    url = os.environ.get("INFERENCE_URL", "").strip()
    key = os.environ.get("INFERENCE_API_KEY", "").strip()

    if not url or not key:
        try:
            from app.config import get_settings
            settings = get_settings()
            if not url and hasattr(settings, "inference_url"):
                url = str(settings.inference_url or "").strip()
            if not key and hasattr(settings, "inference_api_key"):
                key = str(settings.inference_api_key or "").strip()
        except Exception:
            pass

    if not key or not url:
        for env_path in [Path(".env"), Path("/opt/friday_universe/VyralX/.env"), Path("/etc/default/friday_universe.env")]:
            if env_path.exists():
                try:
                    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
                        if line.startswith("INFERENCE_API_KEY=") and not key:
                            key = line.split("=", 1)[1].strip().strip('"').strip("'")
                        elif line.startswith("INFERENCE_URL=") and not url:
                            url = line.split("=", 1)[1].strip().strip('"').strip("'")
                except Exception:
                    pass

    return url or "http://10.0.0.121:8001", key


def analyze_video_frames(video_path: Path, num_frames: int = 4) -> VisualAnalysisResult:
    """Synthesizes high-retention viral commentary via the sovereign Inference gateway.

    Routes all model execution through Inference (http://10.0.0.121:8001) to leverage
    centralized provider failover without storing raw provider keys in VyralX.
    """
    probe_cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    raw_dur = subprocess.check_output(probe_cmd).decode().strip()
    duration = float(raw_dur)

    # Check for accompanying metadata JSON from discovery
    meta_json = video_path.with_suffix(".json")
    title_context = ""
    if meta_json.exists():
        try:
            mdata = json.loads(meta_json.read_text(encoding="utf-8", errors="ignore"))
            title_context = mdata.get("title", "")
        except Exception:
            pass

    if not title_context:
        # Fallback to humanized video stem
        title_context = video_path.stem.replace("-", " ").replace("_", " ").title()

    prompt = (
        f"Video Title / Action: {title_context}\n"
        f"Clip Duration: {duration:.1f} seconds.\n"
        "TASK:\n"
        "1. Write an energetic, witty, high-retention commentary voiceover script (35 to 55 words, ~18-22 seconds) "
        "that describes, reacts to, and highlights this exact visual action second-by-second.\n"
        "MANDATORY INVARIANTS:\n"
        "- ZERO GENERIC FILLER: Never say 'Wait till the end', 'You won't believe this', 'Watch what happens next'.\n"
        "- STRICT RELEVANCE: Speak specifically about the action, physical movement, and tension on screen.\n"
        "- VOICE: Natural, charismatic, confident (no corporate speak, zero 'sir').\n"
        "- START DIRECTLY WITH '{' AND END WITH '}'. NO THINKING. NO MARKDOWN. NO PREAMBLE.\n"
        "{\n"
        f'  "visual_summary": "One sentence describing the exact scene and action for {title_context}",\n'
        '  "script": "Complete spoken voiceover narration perfectly matching the visual events (around 40 words)",\n'
        f'  "title": "{title_context} #Shorts",\n'
        '  "cyan_keywords": ["KEYWORD1", "KEYWORD2", "KEYWORD3", "KEYWORD4"],\n'
        '  "debate_question": "Provocative question directly related to the video action for comments",\n'
        '  "tags": ["shorts", "viral", "trending"]\n'
        "}"
    )

    inf_url, inf_key = get_inference_config()
    headers = {"Content-Type": "application/json"}
    if inf_key:
        headers["X-INFERENCE-API-KEY"] = inf_key
        headers["X-API-Key"] = inf_key
        headers["Authorization"] = f"Bearer {inf_key}"

    # Route 1: Direct OpenAI-compatible chat completion via Inference
    completions_url = f"{inf_url.rstrip('/')}/v1/chat/completions"
    payload = {
        "model": "groq",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.6,
        "max_tokens": 1000
    }

    parsed = None
    try:
        log.info("Requesting viral script from Inference gateway (%s)...", inf_url)
        res = requests.post(completions_url, headers=headers, json=payload, timeout=30)
        if res.status_code == 200:
            data = res.json()
            content = data["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
            log.info("Inference returned valid script via model '%s'", data.get("model", "auto"))
        else:
            log.warning("Inference chat/completions returned HTTP %d: %s", res.status_code, res.text[:150])
    except Exception as exc:
        log.warning("Inference chat/completions route failed (%s). Attempting Universal Task route...", exc)

    # Route 2: Fallback to Universal Task Execution on Inference (/v1/task/execute)
    if not parsed:
        try:
            task_url = f"{inf_url.rstrip('/')}/v1/task/execute"
            task_payload = {
                "source_agent": "vyralx",
                "action": "scriptwriting",
                "payload": {
                    "prompt": prompt,
                    "topic": title_context,
                    "target_audience": "Viral short viewers"
                }
            }
            res = requests.post(task_url, headers=headers, json=task_payload, timeout=30)
            if res.status_code == 200:
                tdata = res.json()
                result = tdata.get("result", {})
                script_text = result.get("script_text") or result.get("hook", "")
                parsed = {
                    "visual_summary": f"Viral visual event: {title_context}",
                    "script": script_text,
                    "title": f"{title_context} #Shorts",
                    "cyan_keywords": ["VIRAL", "INSANE", "UNREAL", "SHOCKING"],
                    "debate_question": "What would you do in this situation? 👇",
                    "tags": ["shorts", "viral", "trending"]
                }
                log.info("Inference Universal Task execution succeeded for VyralX")
        except Exception as exc:
            log.error("Both Inference routes failed: %s", exc)

    if not parsed:
        raise RuntimeError(f"Failed to generate viral script from Inference gateway ({inf_url})")

    # Clean cyan keywords to uppercase alphanumeric
    raw_cyan = parsed.get("cyan_keywords", [])
    cyan_set = {re.sub(r"[^A-Z0-9]", "", str(w).upper()) for w in raw_cyan if str(w).strip()}
    if not cyan_set:
        cyan_set = {"VIRAL", "WATCH", "REAL", "INSANE"}

    return VisualAnalysisResult(
        visual_summary=parsed.get("visual_summary", f"Visual event: {title_context}"),
        script=parsed.get("script", "").strip(),
        title=parsed.get("title", f"{title_context} #Shorts"),
        cyan_keywords=cyan_set,
        debate_question=parsed.get("debate_question", "What would you do in this situation? 👇"),
        tags=parsed.get("tags", ["shorts", "viral"])
    )
