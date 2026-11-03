"""VyralX viral short editor.

Turns a discovered, reuse-licensed source clip into the channel's established
format:

* 1080x1920 vertical framing with a punchy colour grade
* Fast impact-font subtitles in the lower third, the same style the existing
  uploads use
* If the source has **no narration**: a neural commentary voice-over
  (edge-tts, Guy/Christopher) ducked over the original audio, with subtitles
  word-synced to that commentary
* If the source **already has narration**: no voice-over at all, the original
  audio stays at full volume and the subtitles come from a real transcript, so
  two voices never overlap
* A genre thumbnail, a rights record with the Creative Commons licence URL, and
  an unlisted publish job ready for the worker
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import subprocess
import uuid
import zlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import edge_tts
import httpx
import yt_dlp
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Asset, PublishJob, RenderJob, Source, VideoProject, utcnow
from app.services.source_analysis import (
    SpeechReport,
    detect_speech,
    download_audio_only,
    probe_media,
)
from app.services.scene_analysis import describe_scene
log = logging.getLogger("vyralx.viral_remix")

# One voice for the whole channel: the first four uploads all use Guy, so a
# category-dependent voice would break the format on exactly the clips that are
# not tagged COMEDY.
VOICE_BY_CATEGORY = {
    "COMEDY": "en-US-GuyNeural",
    "VIRAL": "en-US-GuyNeural",
    "SPORTS": "en-US-GuyNeural",
}
DEFAULT_VOICE = "en-US-GuyNeural"

COMMENTARY_TEMPLATES = {
    "VIRAL": (
        "Watch this closely. Everyone expects the obvious outcome, and then the whole moment "
        "flips in a way absolutely nobody saw coming. That single second is exactly why this "
        "clip keeps getting replayed.",
        "Everything looks normal for about three seconds. Then the one thing nobody is watching "
        "becomes the only thing that matters. Stay on it, because the payoff is in the last beat.",
    ),
    "COMEDY": (
        "You already know somebody exactly like this. Watch the confidence going in, then watch "
        "the exact second it all falls apart. The reaction at the end is the reason this one "
        "went viral.",
        "The confidence is loud, the plan is simple, and absolutely none of it survives contact "
        "with reality. Watch the exact moment the whole thing turns, then watch who reacts first.",
        "Nobody in this clip is ready for what happens next. The build is slow, the timing is "
        "perfect, and the reaction at the end does all the work. Watch it twice.",
    ),
    "SPORTS": (
        "One tiny mistake here and it is all over. Watch how much control goes into a moment "
        "that looks completely effortless on camera.",
        "Everything about this looks impossible until you watch the footwork. Zero margin, no "
        "second try, and the landing says it all.",
    ),
}


def _fallback_commentary(category: str, source_title: str) -> str:
    options = COMMENTARY_TEMPLATES.get(category.upper(), COMMENTARY_TEMPLATES["VIRAL"])
    digest = zlib.crc32((source_title or "").casefold().encode("utf-8"))
    return options[digest % len(options)]

QUESTION_BY_CATEGORY = {
    "VIRAL": "Did you see that coming? Be honest!",
    "COMEDY": "Would you have kept a straight face?",
    "SPORTS": "Rate that execution from 1 to 10!",
}

HASHTAGS_BY_CATEGORY = {
    "VIRAL": "#Shorts #Viral #Trending #WaitForIt #VyralX",
    "COMEDY": "#Shorts #Comedy #Relatable #Viral #VyralX",
    "SPORTS": "#Shorts #Sports #Respect #Viral #VyralX",
}


# --------------------------------------------------------------------------- #
# helper wrappers
# --------------------------------------------------------------------------- #
def _run(cmd: list[str], *, timeout: int = 600) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr[-600:]}")
    return proc


def _fmt_timecode(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def download_source_video(video_id: str, destination_dir: Path) -> Path:
    """Download the best available MP4 for a source clip."""
    destination_dir.mkdir(parents=True, exist_ok=True)
    expected = destination_dir / f"{video_id}.mp4"
    if expected.is_file() and expected.stat().st_size > 100_000:
        return expected
    opts = {
        "format": "bestvideo[ext=mp4][height<=1920]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "outtmpl": str(destination_dir / f"{video_id}.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "merge_output_format": "mp4",
        "noplaylist": True,
    }
    from app.services.ytdlp_support import apply_defaults

    with yt_dlp.YoutubeDL(apply_defaults(opts)) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={video_id}"])
    if expected.is_file():
        return expected
    for candidate in destination_dir.glob(f"{video_id}.*"):
        if candidate.suffix.lower() == ".mp4":
            return candidate
    raise RuntimeError(f"Source download produced no playable file for {video_id}")


def _json_objects(text: str) -> list[dict[str, Any]]:
    """Pull every balanced JSON object out of a possibly noisy model reply."""
    objects: list[dict[str, Any]] = []
    depth = 0
    start = -1
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    parsed = json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    objects.append(parsed)
    return objects


DESCRIPTION_EXAMPLES = (
    "He dressed up in a luxury tuxedo for a 5-star Michelin dinner... but the waitress served him "
    "literal soap bubbles and blasted him with a bubble gun!\n\n"
    "The final bill for this soap dinner? Exactly $9,999,999!\n\n"
    "👉 Would you pay the bill or run out of the restaurant? Drop your answer below! 💬\n\n"
    "#Shorts #Comedy #Funny #MichelinStar #FineDining #Viral #Humor #Relatable #Trending #Memes",
    "When your friends try to roast you in the hallway, but you have 1000% main character energy! 💅✨\n\n"
    "She delivered the cleanest, most unimpressed eye-roll on the internet and turned the hallway "
    "into Paris Fashion Week. 0% hesitation, 100% unbothered.\n\n"
    "👉 On a scale of 1-10, how savage was that eye-roll? Tag that one friend who has this exact "
    "energy! 😂\n\n"
    "#Shorts #MainCharacter #SchoolHumor #Attitude #Relatable #Viral #Trending #Funny #Savage",
)

# The real voice-over scripts from the channel's own uploads. The TTS voice is
# already identical (en-US-GuyNeural); what makes the old videos sound different
# is this writing: a hook in the first six words, a build, a turn, a payoff.
COMMENTARY_EXAMPLES = (
    "1 inch to the left, and this would have been an absolute catastrophe. Watch the insane "
    "level of millimeter precision as the stunt is executed with zero margin for error. That is "
    "pure raw talent and nerves of steel.",
    "He dressed up in a luxury tuxedo for a five-star Michelin dinner, but the menu had other "
    "plans. Instead of gourmet food, the waitress serves him a plate of literal soap bubbles. "
    "And just when he thinks it cannot get any more ridiculous, she brings out a toy bubble gun "
    "and blasts his head with foam. The final bill for this soap dinner? Exactly 9 million, "
    "999 thousand.",
    "When your friends try to roast you in the school hallway, but you have maximum main "
    "character energy. While the entire squad is laughing and waiting for her to break, she just "
    "hits them with the coldest, most unimpressed eye roll on the entire internet. And instead of "
    "wasting a single second arguing back, she turns around and struts down the hallway like it "
    "is her personal high fashion runway. Zero words, zero hesitation, pure unbothered "
    "confidence.",
)


def _trim_to_sentence(text: str) -> str:
    """Drop a trailing fragment so the voice-over never ends mid-sentence."""
    text = " ".join(str(text or "").split())
    if not text or text[-1] in ".!?":
        return text
    cut = max(text.rfind("."), text.rfind("!"), text.rfind("?"))
    return text[: cut + 1] if cut >= 20 else text


_SCENE_STOPWORDS = {
    "that", "this", "with", "from", "into", "over", "then", "they", "them",
    "their", "while", "when", "what", "have", "been", "were", "will", "your",
    "about", "after", "before", "because", "there", "here", "just", "like",
    "more", "most", "some", "very", "also", "onto", "than", "only", "even",
    "still", "much", "many", "such", "each", "other", "both", "same", "does",
    "doing", "make", "made", "gets", "goes", "going", "come", "comes", "says",
    "said", "looks", "looking", "shows", "showing", "starts", "started",
}


def _mentions_scene(commentary: str, scene: str) -> bool:
    """True when the script names real things from the footage, not filler."""
    def content(text: str) -> set[str]:
        return {word for word in re.findall(r"[a-z]{4,}", text.lower())} - _SCENE_STOPWORDS

    return len(content(commentary) & content(scene)) >= 2


def _editorial_text(payload: Any) -> str:
    """Pull the model's text out of whichever envelope Inference returned.

    ``/v1/chat/completions`` answers with OpenAI ``choices[0].message.content``;
    the ``/v1/task/execute`` endpoint wraps the same text in
    ``result.response``. Accepting both means a routing change on the gateway
    cannot silently downgrade every upload to template copy.
    """
    if not isinstance(payload, dict):
        return ""
    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
    for key in ("result", "output", "response", "data"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
        if isinstance(value, dict):
            for inner_key in ("response", "content", "text", "output", "message"):
                inner = value.get(inner_key)
                if isinstance(inner, str) and inner.strip():
                    return inner
    for key in ("content", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def generate_editorial(
    category: str,
    source_title: str,
    channel: str,
    transcript: str,
    target_seconds: float,
    taken_titles: set[str] | None = None,
    scene: str = "",
    _strict: bool = False,
) -> dict[str, str]:
    """Write title, commentary and description in the channel's exact style.

    The four live uploads are the reference: one punchy claim plus 1-2 emojis and
    ``#Shorts`` for the title, a two-paragraph hook with a question CTA and ten
    hashtags for the description, and 2-3 sentences of tense present-tense
    narration for the voice-over. Titles must never repeat an existing upload.
    """
    settings = get_settings()
    taken = {title.casefold().strip() for title in (taken_titles or set())}
    words = max(30, min(85, int(max(10.0, min(target_seconds, 55.0)) * 2.2)))
    prompt = (
        "You write for a viral Shorts channel. These four titles define the style exactly:\n"
        + "\n".join(f"- {example}" for example in TITLE_EXAMPLES)
        + "\n\nThese two descriptions define the description style exactly:\n"
        + "\n\n".join(f"---\n{example}" for example in DESCRIPTION_EXAMPLES)
        + "\n\nThese are the real voice-over scripts from the channel. Copy their rhythm, "
        "sentence length and energy - this is what the voice must sound like:\n"
        + "\n\n".join(f"---\n{example}" for example in COMMENTARY_EXAMPLES)
        + "\n\n"
        f"Source clip title: \"{source_title[:160]}\"\n"
        f"Source channel: {channel[:80]}\n"
        f"Category: {category}\n"
        f"Spoken transcript (empty means the clip is music only): \"{(transcript or '')[:400]}\"\n\n"
        "What the clip actually shows (frame analysis - the only source of truth for the "
        f"action): \"{(scene or 'not available')[:700]}\"\n\n"
        "Reply with the JSON object only - no reasoning, no markdown, no text before or after.\n"
        "Keys: title, commentary, description.\n"
        "title: 5-11 words in the same style as the four examples, 1-2 emojis, then ' #Shorts'. "
        "It must name the specific thing that happens in this clip - never a generic phrase that "
        "could fit any video - and it must be totally new: never reuse any of the examples.\n"
        f"commentary: {words} words of spoken voice-over, written exactly like the scripts above. "
        "Open with a hook in the first six words, then the setup, then the turn that makes it "
        "funny, then the payoff, then one short closing line. "
        "Use only what the frame analysis says happens; it is the only source of truth. Never "
        "invent characters, objects, dialogue or events that are not in it. If the frame analysis "
        "is unavailable, stay generic and name no specific objects. "
        "Every sentence must name something concrete from the frame analysis - a person, an "
        "object or an action. If a line could describe any other video, cut it. "
        "Never narrate frame by frame, never write 'the video shows' or 'in this clip'. "
        "No hashtags, no emojis, no quotes, no stage directions.\n"
        "description: two short sentences describing the joke or twist, then a blank line, then a "
        "one-line question starting with an emoji and ending with 'Drop your answer below!', then a "
        "blank line, then ten hashtags starting with #Shorts."
    )
    if taken:
        prompt += (
            "\n\nThese titles are already on the channel and must NOT be reused, echoed or "
            "paraphrased closely:\n" + "\n".join(f"- {title}" for title in sorted(taken)[:60])
        )
    if _strict:
        prompt += (
            "\n\nYour previous narration was too generic. Rewrite the commentary so every "
            "sentence names a specific person, object or action from the frame analysis. A line "
            "that could describe a different video is not acceptable."
        )
    try:
        url = settings.inference_url.rstrip("/") + settings.inference_generation_path
        model = (settings.inference_model or "").strip()
        if not model or model.lower() == "auto":
            # "auto" routes to the gateway's fast lane, which clamps the reply
            # to 60 tokens and replaces the system prompt with "answer in 1-2
            # sentences". That cannot carry title + commentary + description.
            model = "llama-3.3-70b-versatile"
        body = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a short-form video editor. Output one compact JSON object with "
                        "the keys title, commentary and description. Never explain your reasoning."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.95,
            "max_tokens": 1600,
            "response_format": {"type": "json_object"},
            "stream": False,
        }
        response = httpx.post(
            url,
            headers={
                "Authorization": f"Bearer {settings.inference_api_key}",
                "X-API-Key": settings.inference_api_key,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=120,
        )
        response.raise_for_status()
        raw = _editorial_text(response.json())
        for payload in reversed(_json_objects(str(raw))):
            title = " ".join(str(payload.get("title") or "").split())
            if not title or title.casefold() in taken:
                continue
            # A reasoning model can echo the key spec back as {"title": "..."},
            # which would otherwise be accepted as a real title.
            if len(title.split()) < 4 or not title.strip(" ."):
                continue
            commentary = _trim_to_sentence(payload.get("commentary") or "")
            if scene and not _strict and not _mentions_scene(commentary, scene):
                # A generic script over the wrong footage is exactly what the
                # channel must never publish; ask once more, grounded.
                log.info("Editorial narration did not match the footage; retrying once")
                return generate_editorial(
                    category, source_title, channel, transcript, target_seconds,
                    taken_titles, scene=scene, _strict=True,
                )
            return {
                "title": title,
                "commentary": commentary,
                "description": str(payload.get("description") or "").strip(),
            }
        log.warning("Editorial reply had no usable new title: %s", str(raw)[:400])
    except Exception as exc:
        log.info(
            "Editorial generation unavailable (%s: %s); using template",
            type(exc).__name__, str(exc)[:200],
        )

    return {
        "title": _fallback_title(category, source_title, taken),
        "commentary": _fallback_commentary(category, source_title),
        "description": "",
    }


# Words that must never end a caption row: breaking after "the" leaves the
# viewer reading a dangling article while the picture moves on.
_ASS_BREAK_STOPWORDS = {
    "A", "AN", "THE", "OF", "TO", "AND", "IN", "ON", "AT", "WITH", "FOR",
    "HIS", "HER", "THEIR", "MY", "YOUR", "OUR", "IS", "WAS", "ARE", "WERE",
    "AS", "THAT", "THIS", "HE", "SHE", "THEY", "IT", "BUT", "OR", "SO",
    "INTO", "ONTO", "FROM", "BY", "THEN", "WHEN", "WHILE",
}


def _phrase_chunks(
    words: list[str], target: int = 3, max_words: int = 4, max_chars: int = 26
) -> list[list[str]]:
    """Split a sentence into caption rows that end on a real word.

    Rows aim for ``target`` words, never end on a stopword and stay inside
    ``max_chars`` so a 104pt row fills most of the frame without spilling off it.
    """
    chunks: list[list[str]] = []
    current: list[str] = []
    for word in words:
        clean = re.sub(r"[^A-Z0-9']", "", word.upper())
        would_be = " ".join(current + [word])
        if current and (len(would_be) > max_chars or len(current) >= max_words):
            chunks.append(current)
            current = []
        current.append(word)
        if len(current) >= target and clean not in _ASS_BREAK_STOPWORDS:
            chunks.append(current)
            current = []
    if current:
        # A lone trailing word looks like a glitch: fold it into the row before,
        # or borrow one word so the last row is not a single flash.
        if len(current) == 1 and chunks:
            merged = " ".join(chunks[-1] + current)
            if len(chunks[-1]) < max_words and len(merged) <= max_chars:
                chunks[-1].extend(current)
                current = []
            elif len(chunks[-1]) > 2:
                current.insert(0, chunks[-1].pop())
        if current:
            chunks.append(current)
    return chunks


async def _synthesize_commentary(script: str, voice: str, output_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    # Same synthesis call as the first four uploads: default rate, en-US-GuyNeural.
    communicate = edge_tts.Communicate(script, voice)
    audio = bytearray()
    cues: list[dict[str, Any]] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "SentenceBoundary":
            start = chunk["offset"] / 10_000_000.0
            duration = chunk["duration"] / 10_000_000.0
            text = str(chunk["text"]).strip()
            words = text.split()
            if not words:
                continue
            total = len(words)
            consumed = 0
            for part in _phrase_chunks(words):
                start_word = consumed
                consumed += len(part)
                cues.append({
                    "start": round(start + duration * (start_word / total), 2),
                    "end": round(start + duration * (consumed / total), 2),
                    "text": " ".join(part),
                })
    if not audio:
        raise RuntimeError("edge-tts returned no audio")
    output_path.write_bytes(bytes(audio))
    return output_path, cues


def synthesize_commentary(script: str, voice: str, output_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    return asyncio.run(_synthesize_commentary(script, voice, output_path))


_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: AntonBold,Anton,120,&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,0,0,0,0,100,100,1.2,0,1,10.0,4.5,2,50,50,400,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

# &HAABBGGRR. Rotated per cue so consecutive captions change colour while every
# single caption stays legible against the video.
_ASS_PALETTE = (
    r"{\c&H00E5FF&}",   # yellow  #FFE500
    r"{\c&H00FFE5&}",   # cyan    #00E5FF
    r"{\c&H00952DFF&}", # pink    #FF2D95
    r"{\c&H0000FF7C&}", # lime    #7CFF00
    r"{\c&H00007AFF&}", # orange  #FF7A00
)
_ASS_WHITE = r"{\c&H00FFFFFF&}"
# Emphasis: the accent colour plus a short pop so the key word lands.
_ASS_POP = r"{\fscx115\fscy115}"

_HIGHLIGHT_WORDS = {
    "WAIT", "NEVER", "NOBODY", "EVERYTHING", "WORST", "BEST", "INSANE",
    "IMPOSSIBLE", "UNEXPECTED", "MOST", "SHOCKED", "MILLIONS", "PERFECT",
    "MILLIMETER", "CRAZY", "SAVAGE", "UNBOTHERED", "SHUT", "DOWN", "PLOT",
    "TWIST", "REGRET", "INSTANTLY", "MONEY", "BILL", "EXPENSIVE", "FREE",
}


def _ass_time(seconds: float) -> str:
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = total % 60
    return f"{hours}:{minutes:02d}:{secs:05.2f}"


def _write_ass(cues: list[dict[str, Any]], ass_path: Path) -> Path:
    """Anton 104pt uppercase captions, one solid accent colour per row.

    104pt reads as big captioning on a phone without spilling off the 1080px
    frame (64pt looked tiny, 96pt with full-width rows looked oversized). Each
    row takes the next colour in the palette, and numbers / payoff words punch
    through in white at 110% for contrast.
    """
    events: list[str] = []
    for cue_index, cue in enumerate(cues):
        text = " ".join(str(cue.get("text") or "").split()).upper()
        if not text:
            continue
        start = float(cue["start"])
        end = float(cue["end"]) if float(cue["end"]) > start else start + 0.6
        accent = _ASS_PALETTE[cue_index % len(_ASS_PALETTE)]
        styled: list[str] = [accent]
        for word in text.split():
            clean = re.sub(r"[^A-Z0-9]", "", word)
            emphasis = clean in _HIGHLIGHT_WORDS or any(char.isdigit() for char in clean)
            if emphasis:
                styled.append(f"{_ASS_WHITE}{_ASS_POP}{word}{accent}")
            else:
                styled.append(word)
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},AntonBold,,0,0,0,,"
            + " ".join(styled)
        )
    ass_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path.write_text(_ASS_HEADER + "\n".join(events), encoding="utf-8")
    return ass_path


def _escape_filter_path(path: Path) -> str:
    text = str(path.resolve()).replace("\\", "/")
    if ":" in text:
        drive, rest = text.split(":", 1)
        return f"{drive}\\:{rest}"
    return text


def _base_video_filter(cues: list[dict[str, Any]], category: str, ass_path: Path) -> str:
    fonts_dir = _escape_filter_path(Path("data/fonts"))
    ass_filter = _escape_filter_path(ass_path)
    return (
        "scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,eq=contrast=1.06:saturation=1.12,"
        f"subtitles='{ass_filter}':fontsdir='{fonts_dir}'"
    )


def _fallback_beats(duration: float, hook: str, category: str) -> list[dict[str, Any]]:
    beats = [
        (0.0, min(3.6, duration), hook),
        (min(4.0, duration), min(10.0, duration), "NOBODY EXPECTED THIS"),
        (min(11.0, duration), max(11.5, duration - 0.5), "WATCH IT AGAIN"),
    ]
    return [
        {"start": round(start, 2), "end": round(end, 2), "text": text}
        for start, end, text in beats
        if end > start
    ]


# --------------------------------------------------------------------------- #
# renderers
# --------------------------------------------------------------------------- #
def render_with_commentary(
    source_path: Path,
    narration_path: Path,
    output_path: Path,
    cues: list[dict[str, Any]],
    category: str,
    source_has_audio: bool = True,
    duration: float = 0.0,
) -> Path:
    """Commentary over a silent/music-only clip; original audio ducked to 20%.

    The clip is never cut short to match the voice-over: the narration is padded
    with silence when it finishes early and the output keeps the source length,
    so the payoff at the end of the clip always survives the edit.
    """
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path = _write_ass(cues, output_path.with_suffix(".ass"))
    video_chain = _base_video_filter(cues, category, ass_path)
    if source_has_audio:
        # ``duration=first`` pins the mix to the source audio, which is the same
        # length as the picture, so the output is never longer than the clip.
        audio_chain = (
            "[0:a]volume=0.20[orig];"
            "[1:a]volume=1.0,apad[voice];"
            "[orig][voice]amix=inputs=2:duration=first:dropout_transition=2,"
            "loudnorm=I=-14:LRA=9:TP=-1.5[a]"
        )
    else:
        # A silent source has no first stream to pin the mix to; padding the
        # voice means ``-shortest`` cuts at the end of the picture instead of
        # the end of the narration.
        audio_chain = "[1:a]apad,loudnorm=I=-14:LRA=9:TP=-1.5[a]"
    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
        "-i", str(source_path),
        "-i", str(narration_path),
        "-filter_complex", f"[0:v]{video_chain}[v];{audio_chain}",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
    ]
    cmd.append(str(output_path))
    # 1080x1920 with a burned-in ASS track is the slowest step in the pipeline;
    # on the shared 2-vCPU host a 60s clip can take well over ten minutes.
    _run(cmd, timeout=2400)
    return output_path


def render_with_original_audio(
    source_path: Path,
    output_path: Path,
    cues: list[dict[str, Any]],
    category: str,
    duration: float,
    source_has_audio: bool = True,
) -> Path:
    """Keep the source's own narration; subtitles transcribe what is actually said."""
    settings = get_settings()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ass_path = _write_ass(cues, output_path.with_suffix(".ass"))
    video_chain = _base_video_filter(cues, category, ass_path)
    if source_has_audio:
        audio_chain = "[0:a]loudnorm=I=-14:LRA=9:TP=-1.5[a]"
    else:
        audio_chain = "anullsrc=channel_layout=stereo:sample_rate=44100,atrim=0:%.2f,loudnorm=I=-14:LRA=9:TP=-1.5[a]" % duration
    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
        "-i", str(source_path),
        "-filter_complex", f"[0:v]{video_chain}[v];{audio_chain}",
        "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "faster", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-t", f"{duration:.2f}",
        str(output_path),
    ]
    _run(cmd)
    return output_path


# --------------------------------------------------------------------------- #
# copywriting
# --------------------------------------------------------------------------- #
TITLE_EXAMPLES = (
    "Wait For The Most Unexpected Plot Twist \U0001F631\U0001F92F #Shorts",
    "Millimeter-Perfect Extreme Stunt That Shocked Millions \U0001F631\U0001F525 #Shorts",
    "Maximum Main Character Energy In School \U0001F480\u2728 #Shorts",
    "The $9,999,999 Michelin Restaurant \U0001F480\U0001F9FC #Shorts",
)

TITLE_FALLBACKS = {
    "VIRAL": (
        "Wait For The Most Unexpected Plot Twist \U0001F631\U0001F92F #Shorts",
        "Nobody Saw That Ending Coming \U0001F631\U0001F480 #Shorts",
        "The Moment Everything Flipped \U0001F92F\U0001F525 #Shorts",
        "You Will Replay This Ending Twice \U0001F631\U0001F440 #Shorts",
    ),
    "COMEDY": (
        "Maximum Main Character Energy \U0001F480\U0001F602 #Shorts",
        "She Did NOT See That Coming \U0001F631\U0001F602 #Shorts",
        "The Confidence Was Real Until This \U0001F480\U0001F62D #Shorts",
        "His Reaction Says Everything \U0001F602\U0001F480 #Shorts",
    ),
    "SPORTS": (
        "Millimeter-Perfect Stunt That Shocked Millions \U0001F631\U0001F525 #Shorts",
        "The Control Here Is Insane \U0001F92F\U0001F3AF #Shorts",
        "He Made That Look Way Too Easy \U0001F631\U0001F525 #Shorts",
        "Do Not Try This At Home \U0001F480\U0001F3AF #Shorts",
    ),
    "LIFEHACKS": (
        "The Genius Hack Nobody Talks About \U0001F4A1 #Shorts",
        "Why Did Nobody Tell Me This Sooner \U0001F4A1\U0001F92F #Shorts",
    ),
}


def _fallback_title(
    category: str,
    source_title: str,
    taken: set[str] | None = None,
) -> str:
    """Deterministic but varied channel-style title, never one already used."""
    options = TITLE_FALLBACKS.get(category.upper(), TITLE_FALLBACKS["VIRAL"])
    used = {title.casefold().strip() for title in (taken or set())}
    digest = zlib.crc32((source_title or "").casefold().encode("utf-8"))
    for offset in range(len(options)):
        candidate = _clean_title(options[(digest + offset) % len(options)])
        if candidate.casefold() not in used:
            return candidate
    # Every template is spent: build one from the clip's own title instead.
    core = " ".join(re.sub(r"#\w+", "", source_title or "").split())[:48].strip(" -|:")
    core = core.title() or "This Viral Moment"
    return _clean_title(f"{core} 😱🔥 #Shorts")


def _clean_title(raw: str) -> str:
    title = " ".join(str(raw or "").split())
    title = re.sub(r"#\w+", "", title).strip(" -|:")
    if not title:
        return ""
    if "#shorts" not in title.casefold():
        title = f"{title} #Shorts"
    return title[:100]


def build_metadata(
    candidate: Any,
    speech: SpeechReport,
    hook: str,
    category: str,
    editorial: dict[str, str] | None = None,
    taken_titles: set[str] | None = None,
) -> dict[str, Any]:
    editorial = editorial or {}
    title_core = re.sub(r"#\w+", "", str(candidate.title or "")).strip(" |-—")
    title_core = " ".join(title_core.split())[:80] or hook.title()
    title = _clean_title(editorial.get("title") or "")
    if not title or title.casefold() in {t.casefold() for t in (taken_titles or set())}:
        title = _fallback_title(category, candidate.title, taken_titles)
    comment = " ".join(str(editorial.get("commentary") or "").split())

    question = QUESTION_BY_CATEGORY.get(category.upper(), QUESTION_BY_CATEGORY["VIRAL"])
    hashtags = HASHTAGS_BY_CATEGORY.get(category.upper(), HASHTAGS_BY_CATEGORY["VIRAL"])
    body = str(editorial.get("description") or "").strip()
    if not body:
        summary = comment or (
            "Watch what happens in this clip - one moment, and the whole thing flips."
            if not speech.has_speech
            else "The moment everyone replayed, with the audio left exactly as it was recorded."
        )
        body = f"{summary}\n\n👉 {question} Drop your answer below! 💬\n\n{hashtags}"
    description = (
        f"{body}\n\n"
        f'Credit: source clip "{title_core}" by {candidate.channel or "the original creator"} - '
        f"https://www.youtube.com/watch?v={candidate.video_id}\n"
        f"Commentary, subtitles and edit by VyralX."
    )
    tags = [
        "shorts", "comedy", "funny", "viral", "trending", category.lower(),
        "wait for it", "relatable", "vyralx", "shorts feed",
    ]
    return {
        "title": title,
        "description": description[:4800],
        "tags": tags,
        "hook": hook,
        "commentary": comment,
    }


def existing_upload_titles(db: Session) -> set[str]:
    """Every title already on the channel, from our DB and from YouTube itself."""
    from sqlalchemy import select

    from app.models import PublishJob

    titles = {
        str(title).strip()
        for title in db.scalars(select(PublishJob.title)).all()
        if title
    }
    try:
        from app.services.youtube import youtube_service

        service = youtube_service()
        channel = service.channels().list(part="contentDetails", mine=True).execute()
        uploads = channel["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        playlist = service.playlistItems().list(
            part="snippet", playlistId=uploads, maxResults=50
        ).execute()
        for item in playlist.get("items") or []:
            title = (item.get("snippet") or {}).get("title")
            if title:
                titles.add(str(title).strip())
    except Exception as exc:
        log.info("Live title lookup unavailable (%s); using local titles only", type(exc).__name__)
    return titles


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #
def produce_viral_short(
    candidate: Any,
    db: Session,
    *,
    publish: bool = True,
) -> dict[str, Any]:
    """Audition -> download -> edit -> register -> queue publish for one candidate."""
    settings = get_settings()
    category = str(candidate.category or "VIRAL").upper()
    settings.prepare_directories()
    settings.render_dir.mkdir(parents=True, exist_ok=True)
    settings.media_dir.mkdir(parents=True, exist_ok=True)

    # 1. Cheap audio audition: any voice in the source disqualifies it. The
    # first four uploads are music/ambience clips with our own narration, so a
    # source with speech would put two voices on top of each other.
    audio_dir = settings.media_dir / "viral_audio_probe"
    audio_path = download_audio_only(candidate.video_id, audio_dir)
    if audio_path is None:
        return {"status": "SKIPPED", "reason": "audio_unavailable", "video_id": candidate.video_id}
    speech = detect_speech(audio_path)
    if speech.has_speech:
        return {
            "status": "SKIPPED",
            "reason": "source_has_narration",
            "video_id": candidate.video_id,
            "speech_seconds": speech.speech_seconds,
        }

    # 2. Full download and probe
    source_path = download_source_video(candidate.video_id, settings.media_dir / "viral_sources")
    probe = probe_media(source_path)
    duration = max(6.0, probe.duration or float(candidate.duration or 20.0))
    project_key = f"viral-{candidate.video_id}-{uuid.uuid4().hex[:6]}"
    render_path = settings.render_dir / f"{project_key}.mp4"
    hook = str(candidate.hook or "WAIT FOR IT")

    # 3. Edit exactly like the first four: our voice-over over ducked source
    # audio, Anton captions, no second voice anywhere.
    taken_titles = existing_upload_titles(db)
    # Look at the clip before writing about it: without this the model invents
    # a plot from the title alone and the voice-over describes a different video.
    scene = describe_scene(source_path, duration)
    editorial = generate_editorial(
        category,
        str(getattr(candidate, "title", "")),
        str(getattr(candidate, "channel", "")),
        speech.text,
        duration,
        taken_titles,
        scene=scene,
    )
    voice = VOICE_BY_CATEGORY.get(category, DEFAULT_VOICE)
    voice_script = editorial.get("commentary") or _fallback_commentary(
        category, str(getattr(candidate, "title", ""))
    )
    narration_path = settings.media_dir / "voiceovers" / f"{project_key}.mp3"
    _, cues = synthesize_commentary(voice_script, voice, narration_path)
    if not cues:
        cues = _fallback_beats(duration, hook, category)
    render_with_commentary(
        source_path, narration_path, render_path, cues, category,
        probe.has_audio, duration,
    )
    mode = "commentary"

    thumbnail_path = settings.render_dir / f"{project_key}-thumb.jpg"
    try:
        from app.services.thumbnail_designer import generate_genre_thumbnail

        generate_genre_thumbnail(
            video_path=source_path,
            output_path=thumbnail_path,
            headline=hook,
            category=category,
        )
    except Exception as exc:  # thumbnail is a nice-to-have, never fatal
        log.warning("Thumbnail generation failed: %s", exc)
        thumbnail_path = Path("")

    meta = build_metadata(candidate, speech, hook, category, editorial, taken_titles)

    # 4. Persist rights record + render + queued publish job
    reuse_licensed = bool(str(getattr(candidate, "license", "")).strip()) and (
        "creative commons" in str(candidate.license).casefold()
    )
    if reuse_licensed:
        platform = "youtube_creative_commons"
        license_name = str(candidate.license)[:190]
        permission_reference = (
            f"https://www.youtube.com/watch?v={candidate.video_id} - licence: {candidate.license}"
        )[:2000]
        notes = "Reuse licence verified from the source metadata."
    else:
        platform = "youtube_transformative"
        license_name = "Transformative commentary - original creator credited (operator policy)"
        permission_reference = (
            f"https://www.youtube.com/watch?v={candidate.video_id} - operator-attested "
            "transformative commentary: original audio retained or new commentary added, "
            "subtitles and attribution on every upload"
        )[:2000]
        notes = "Operator-selected transformative commentary policy; original creator credited in the description."
    source = Source(
        title=f"Source: {candidate.title[:240]}",
        source_url=f"https://www.youtube.com/watch?v={candidate.video_id}",
        platform=platform,
        creator=str(candidate.channel or "")[:280],
        license_name=license_name,
        permission_reference=permission_reference,
        repeat_use_allowed=True,
        repeat_use_reviewed_at=utcnow(),
        # Oracle stores '' as NULL, and this column is NOT NULL, so the note has
        # to carry text or the whole source row is rejected.
        repeat_use_review_notes=(
            "Operator-attested transformative-commentary policy; no repeat-use "
            "review required."
        ),
        rights_verified=True,
        status="approved",
        notes=notes,
    )
    db.add(source)
    db.flush()
    asset = Asset(
        source_id=source.id,
        title=str(candidate.title)[:280],
        file_path=str(source_path),
        duration_seconds=float(duration),
        width=probe.width,
        height=probe.height,
        rights_verified=True,
    )
    db.add(asset)
    db.flush()

    project = VideoProject(
        project_key=project_key,
        topic=f"Repurposed: {str(candidate.title)[:120]}",
        video_format="shorts",
        target_seconds=int(round(duration)),
        audience="viral shorts audience",
        tone="high energy, deadpan funny",
        scene_count=1,
        confirm_pexels_license=False,
        confirm_pexels_repeat_use=False,
        use_voiceover=(mode == "commentary"),
        status="completed",
        primary_asset_id=asset.id,
        asset_ids_json=json.dumps([asset.id]),
        thumbnail_path=str(thumbnail_path) if thumbnail_path else "",
        completed_at=utcnow(),
        attempts=1,
    )
    db.add(project)
    db.flush()

    render_job = RenderJob(
        asset_id=asset.id,
        preset="shorts",
        status="completed",
        output_path=str(render_path),
        attempts=1,
        project_id=None,
        options_json=json.dumps({
            "montage_asset_ids": [asset.id],
            "source_video_id": candidate.video_id,
            "source_views": int(getattr(candidate, "view_count", 0) or 0),
            "edit_mode": mode,
        }),
        completed_at=utcnow(),
    )
    db.add(render_job)
    db.flush()
    project.render_job_id = render_job.id

    publish_job = None
    if publish:
        publish_job = PublishJob(
            asset_id=asset.id,
            render_job_id=render_job.id,
            title=meta["title"],
            description=meta["description"],
            tags_json=json.dumps(meta["tags"]),
            privacy_status=str(getattr(settings, "autonomous_publish_privacy", "unlisted")),
            status="queued",
            approved_at=utcnow(),
        )
        db.add(publish_job)
    db.commit()

    result = {
        "status": "QUEUED_FOR_PUBLISH" if publish else "RENDERED",
        "project_key": project_key,
        "project_id": project.id,
        "render_job_id": render_job.id,
        "publish_job_id": publish_job.id if publish_job else None,
        "edit_mode": mode,
        "source_video_id": candidate.video_id,
        "source_views": int(getattr(candidate, "view_count", 0) or 0),
        "source_license": candidate.license,
        "title": meta["title"],
        "duration": round(duration, 1),
        "narration": voice_script[:280],
        "render": str(render_path),
    }
    log.info("Viral short ready: %s", result)
    return result


def recency_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")
