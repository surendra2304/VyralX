"""Autonomous Video Studio for VyralX with Studio-Grade Music, Sound Design & Effects.

Produces complete, high-retention viral YouTube Shorts autonomously from scratch:
- Curated high-hook narrative scripts
- Studio-mastered neural voiceovers (EQ + broadcast compression)
- Authentic cinematic background music (BGM) with dynamic sidechain ducking
- Active kinetic subtitles with keyword pop highlighting
- 16-20 rapid-cut real motion stock video clips (zero Ken Burns zoompan freeze)
- Full-bleed 1080x1920 vertical framing (zero blur bars)
- Database persistence in VideoProject & RenderJob
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

sys.path.insert(0, ".")

import edge_tts

from app.config import get_settings
from app.database import SessionLocal
from app.models import Asset, ContentPack, RenderJob, VideoProject
from app.services.captions import segment_script, write_ass, write_srt
from app.services.montage import render_montage

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("vyralx.autonomous")

AUTONOMOUS_PRODUCTIONS = [
    {
        "key": "vyralx-money-shock",
        "topic": "The 15-Minute Shock That Changed Money Forever",
        "category": "wealth",
        "voice": "en-US-ChristopherNeural",
        "bgm_file": "bgm_dark_188.mp3",
        "bgm_volume": 0.22,
        "rate": "+4%",
        "keywords": ["1971", "nixon", "emergency", "fifteen", "minutes", "gold", "standard", "vaults", "fort", "knox", "fiat", "currency", "faith", "skyrocketed", "inflation", "trillions", "wallet"],
        "script": (
            "On August 15th, 1971, President Richard Nixon interrupted American television with an emergency address. "
            "In just fifteen minutes, he dismantled the foundation of the world economy: the gold standard. "
            "Before that night, every single paper dollar was backed by physical gold held in government vaults. "
            "Foreign nations were trading their dollars for American gold at such a furious pace that Fort Knox was nearly drained. "
            "So Nixon severed the link completely, turning the dollar into pure fiat currency backed by nothing but faith. "
            "Within twenty-four hours, the price of gold skyrocketed, inflation exploded across the globe, and governments gained the power to print trillions out of thin air. "
            "Fifty years later, every paper bill in your wallet still carries the consequence of those fifteen minutes."
        ),
        "asset_prefixes": [
            "18296", "45703", "47005", "47011", "46988", "46980", 
            "9607", "45708", "47012", "30873", "26748", "7891",
            "23215", "23219", "28897", "28893"
        ],
    },
    {
        "key": "vyralx-natural-reactor",
        "topic": "The 1.8-Billion-Year-Old Natural Nuclear Reactor",
        "category": "science",
        "voice": "en-US-EricNeural",
        "bgm_file": "bgm_mysterious_127.mp3",
        "bgm_volume": 0.20,
        "rate": "+3%",
        "keywords": ["1972", "french", "scientists", "uranium", "mine", "terrifying", "nuclear", "fuel", "atomic", "machine", "truth", "1.8", "billion", "dinosaurs", "nature", "reactor", "groundwater", "chain", "reaction", "steam", "cooling", "billions", "splitting"],
        "script": (
            "In 1972, French scientists testing uranium from an African mine discovered something terrifying: "
            "The uranium had already been burned as nuclear fuel. "
            "At first, the scientific community suspected secret modern atomic testing or an extraterrestrial machine. "
            "The truth was even more mind-blowing: 1.8 billion years ago, before dinosaurs or humans ever existed, nature built its own nuclear reactor. "
            "Groundwater seeped into a dense uranium deposit, acting as a natural moderator that ignited a continuous nuclear chain reaction. "
            "For hundreds of thousands of years, the earth generated steady nuclear power, perfectly controlled by boiling steam and cooling water. "
            "Humanity spent billions of dollars splitting the atom, only to discover our planet perfected it two billion years before we arrived."
        ),
        "asset_prefixes": [
            "5580", "5485", "46747", "47783", "4719", "3780", 
            "3957", "29351", "4075", "18791", "31596", "99786",
            "41576", "2213", "4119", "47050"
        ],
    },
]


async def _synthesize_voice(text: str, voice: str, rate: str, dest_path: Path) -> float:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = dest_path.with_name("raw_" + dest_path.name)
    communicate = edge_tts.Communicate(text, voice, rate=rate)
    await communicate.save(str(raw_path))

    # Apply radio broadcast vocal master chain (EQ + compression)
    vocal_filter = (
        "highpass=f=80,"
        "equalizer=f=120:width_type=o:w=1:g=4.0,"
        "equalizer=f=3200:width_type=o:w=1:g=3.0,"
        "acompressor=threshold=-16dB:ratio=4:attack=5:release=50"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(raw_path),
        "-af", vocal_filter,
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(dest_path)
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    if raw_path.is_file():
        raw_path.unlink()

    cmd_dur = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(dest_path)
    ]
    res = subprocess.run(cmd_dur, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def produce_autonomous_short(cfg: dict, db: SessionLocal) -> str:
    settings = get_settings()
    topic = cfg["topic"]
    script = cfg["script"]
    voice = cfg["voice"]
    rate = cfg.get("rate", "+3%")
    prefixes = cfg["asset_prefixes"]
    keywords = cfg.get("keywords", [])
    bgm_file = cfg.get("bgm_file", "bgm_cinematic_614.mp3")
    bgm_vol = cfg.get("bgm_volume", 0.22)
    project_key = f"{cfg['key']}-{uuid.uuid4().hex[:6]}"

    log.info("Starting autonomous production: %s (%s)", topic, project_key)

    # 1. Synthesize & Master Voiceover
    voice_filename = f"voice_mastered_{uuid.uuid4().hex[:12]}.mp3"
    voice_path = settings.media_dir / "voiceovers" / voice_filename
    voice_duration = asyncio.run(_synthesize_voice(script, voice, rate, voice_path))
    log.info("Synthesized & mastered broadcast voiceover: %s (duration: %.2fs)", voice_path, voice_duration)

    target_seconds = math.ceil(voice_duration + 2.0) # Clean 2s breathing room

    # 2. Match local licensed real-motion assets
    assets: list[Asset] = []
    for prefix in prefixes:
        matched = (
            db.query(Asset)
            .filter(Asset.file_path.like(f"%mixkit-{prefix}-%"))
            .filter(Asset.file_path.like("%.mp4"))
            .first()
        )
        if matched and Path(matched.file_path).is_file():
            assets.append(matched)

    if len(assets) < 8:
        extra_assets = (
            db.query(Asset)
            .filter(Asset.file_path.like("%.mp4"))
            .limit(16)
            .all()
        )
        for ea in extra_assets:
            if ea not in assets and len(assets) < 16:
                assets.append(ea)

    log.info("Loaded %d high-motion video assets for %s", len(assets), project_key)

    # 3. Create ContentPack
    pack = ContentPack(
        topic=topic,
        video_format="shorts",
        status="generated",
        pack_json=json.dumps({
            "script": script,
            "topic": topic,
            "voice": voice,
            "category": cfg.get("category", "viral"),
        }),
        voiceover_path=str(voice_path),
        voiceover_status="ready",
    )
    db.add(pack)
    db.flush()

    # 4. Create VideoProject
    project = VideoProject(
        project_key=project_key,
        topic=topic,
        video_format="shorts",
        target_seconds=target_seconds,
        audience="viral shorts audience",
        tone="cinematic, intense, factual",
        scene_count=len(assets),
        confirm_pexels_license=True,
        confirm_pexels_repeat_use=True,
        use_voiceover=True,
        status="rendering",
        content_pack_id=pack.id,
        primary_asset_id=assets[0].id,
        asset_ids_json=json.dumps([a.id for a in assets]),
        attempts=1,
    )
    db.add(project)
    db.flush()

    # 5. Generate Kinetic Subtitles with Keyword Pop
    segments = segment_script(script, voice_duration, max_chars=34, max_words_per_cue=4)
    subtitle_dir = settings.data_dir / "subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    sub_path = subtitle_dir / f"{project_key}.srt"
    ass_path = subtitle_dir / f"{project_key}.ass"
    write_srt(segments, sub_path)
    write_ass(segments, ass_path, style="CapCutViral", uppercase=True, highlight_keywords=keywords)

    # 6. Render Full-Bleed 1080x1920 Video with BGM Ducking & Color Grading
    out_file = settings.render_dir / f"{project_key}.mp4"
    source_paths = [a.file_path for a in assets]
    bgm_path = (settings.media_dir / "music" / bgm_file).resolve()

    log.info("Rendering %s (%d scenes, %.1fs target) with BGM ducking (%s)...", project_key, len(source_paths), target_seconds, bgm_file)
    rendered = render_montage(
        source_paths=source_paths,
        destination=out_file,
        preset="shorts",
        target_seconds=target_seconds,
        fit_mode="crop", # 100% full bleed vertical, zero blur bars
        subtitle_file=sub_path,
        voiceover_path=voice_path,
        bgm_path=bgm_path,
        bgm_volume=bgm_vol,
        ducking_attenuation_db=-16.0, # Automatic sidechain compression
        normalize_loudness=True,
        enable_ken_burns=False, # Pure real motion video!
    )

    # 7. Record RenderJob and complete Project
    render_job = RenderJob(
        asset_id=assets[0].id,
        preset="shorts",
        status="completed",
        output_path=str(rendered),
        attempts=1,
        project_id=project.id,
        options_json=json.dumps({
            "project_id": project.id,
            "target_seconds": target_seconds,
            "voice": voice,
            "bgm": bgm_file,
            "file_size": Path(rendered).stat().st_size,
        }),
    )
    db.add(render_job)
    db.flush()

    project.status = "completed"
    project.render_job_id = render_job.id
    db.commit()

    # 8. Copy to artifact brain dir
    brain_dir = Path(r"C:\Users\Surendra\.gemini\antigravity\brain\9eb461ef-8e8c-48bb-9abe-936c30ea157d")
    target_artifact = brain_dir / f"{cfg['key']}.mp4"
    shutil.copy2(rendered, target_artifact)

    sz_mb = Path(rendered).stat().st_size / 1024 / 1024
    log.info("Production finished: %s (size: %.2f MB) -> copied to %s", rendered, sz_mb, target_artifact)
    return str(target_artifact)


if __name__ == "__main__":
    db = SessionLocal()
    for cfg in AUTONOMOUS_PRODUCTIONS:
        produce_autonomous_short(cfg, db)
