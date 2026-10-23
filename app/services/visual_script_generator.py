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


def analyze_video_frames(video_path: Path, num_frames: int = 4) -> VisualAnalysisResult:
    """Visually inspects extracted video frames with Gemini 3.8 Flash via OpenRouter."""
    duration, frame_paths = extract_clip_keyframes(video_path, num_frames=num_frames)
    if not frame_paths:
        raise RuntimeError(f"Failed to extract any keyframes from {video_path}")

    frame_parts = []
    for fp in frame_paths:
        b64 = base64.b64encode(fp.read_bytes()).decode("utf-8")
        frame_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })

    prompt = (
        f"You are VyralX, an expert viral commentary producer. You are reviewing {len(frame_paths)} sequential "
        f"keyframes extracted across a {duration:.1f}-second viral video clip.\n\n"
        "TASK:\n"
        "1. Visually identify what is physically happening in these frames: the exact people, actions, props, tools, "
        "clothing, gestures, environments, and outcomes visible on screen.\n"
        "2. Write an energetic, witty, high-retention commentary voiceover script (40 to 60 words, ~18-22 seconds) "
        "that describes, reacts to, and explains the EXACT visual progression on screen second-by-second.\n\n"
        "MANDATORY INVARIANTS:\n"
        "- ZERO GENERIC FILLER: Never say 'Wait till the end', 'You won't believe this', 'Watch what happens next'.\n"
        "- STRICT VISUAL RELEVANCE: You MUST mention the specific real-world objects, places, and actions seen in the frames.\n"
        "- VOICE: Natural, charismatic, confident (no corporate speak, no 'sir').\n"
        "- RETURN STRICT JSON ONLY with this exact schema:\n"
        "{\n"
        '  "visual_summary": "One sentence describing the exact scene and action",\n'
        '  "script": "Complete spoken voiceover narration perfectly describing the visual events",\n'
        '  "title": "High-CTR punchy YouTube Shorts title with relevant emojis and #Shorts",\n'
        '  "cyan_keywords": ["KEYWORD1", "KEYWORD2", "KEYWORD3", "KEYWORD4"],\n'
        '  "debate_question": "Provocative question directly related to the video action for comments",\n'
        '  "tags": ["shorts", "tag1", "tag2", "tag3", "tag4", "tag5"]\n'
        "}"
    )

    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": prompt}] + frame_parts
        }
    ]

    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        env_file = Path("/etc/default/friday_universe.env")
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.startswith("OPENROUTER_API_KEY="):
                    api_key = line.split("=", 1)[1].strip()
                    os.environ["OPENROUTER_API_KEY"] = api_key
                    break
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured in the environment or /etc/default/friday_universe.env")

    res = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "google/gemini-3.8-flash",
            "messages": messages,
            "max_tokens": 1500,
            "response_format": {"type": "json_object"}
        },
        timeout=45
    )
    if res.status_code == 200:
        data = res.json()
        content = data["choices"][0]["message"]["content"]
        parsed = _extract_json(content)

        # Clean cyan keywords to uppercase alphanumeric
        raw_cyan = parsed.get("cyan_keywords", [])
        cyan_set = {re.sub(r"[^A-Z0-9]", "", str(w).upper()) for w in raw_cyan if str(w).strip()}

        # Cleanup temp frames
        for fp in frame_paths:
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            frame_paths[0].parent.rmdir()
        except Exception:
            pass

        return VisualAnalysisResult(
            visual_summary=parsed.get("visual_summary", ""),
            script=parsed.get("script", "").strip(),
            title=parsed.get("title", f"Insane Moment #{video_path.stem} #Shorts"),
            cyan_keywords=cyan_set,
            debate_question=parsed.get("debate_question", "What would you do in this situation? 👇"),
            tags=parsed.get("tags", ["shorts", "viral"])
        )
    else:
        raise RuntimeError(f"OpenRouter vision API returned HTTP {res.status_code}: {res.text[:200]}")
