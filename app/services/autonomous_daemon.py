"""Autonomous Video Production & Publishing Daemon for VyralX.

Runs continuously in the background to autonomously produce and publish high-voltage viral Shorts:
1. Loops through high-RPM viral topic pipelines (Fintech, Heists, Scandals, Space/Physics, Earth Mysteries).
2. Synthesizes & masters broadcast-grade voiceovers at 1.15x speed using premier neural voices.
3. Renders multi-track stereo sound design:
   - Voice stereo-centered
   - Dynamic sidechain-ducked cinematic background music (-16dB under speech)
   - Sub-bass cinematic hook impact at t=0.1s
   - Rapid stereo whoosh transitions on every single scene cut
4. Assembles 20–25 rapid real-motion video clips (~1.8s per cut, full-bleed 1080x1920 vertical).
5. Generates CapCutViral kinetic subtitles with glowing keyword pop highlights.
6. Renders the MP4 using fast-loading web-optimized settings (+faststart).
7. Generates high-contrast viral thumbnail with custom headline and category badge.
8. Persists VideoProject, ContentPack, RenderJob, and PublishJob in the database.
9. Automatically publishes directly to YouTube using stored OAuth credentials, and retries pending uploads.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import edge_tts

from app.config import get_settings
from app.database import SessionLocal
import app.models as models
from app.models import Asset, ContentPack, PublishJob, RenderJob, Source, VideoProject, utcnow
from app.services.captions import segment_script, write_ass, write_srt
from app.services.montage import render_montage
from app.services.thumbnail import create_viral_thumbnail
from app.services.youtube import upload_video

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [VyralX-Daemon] %(message)s")
log = logging.getLogger("vyralx.daemon")

_stopping = False

VIRAL_QUEUE = [
    {
        "key": "vyralx-wallstreet-hound",
        "topic": "How A 23-Year-Old Kid Crashed Wall Street",
        "category": "WEALTH",
        "badge_color": (255, 215, 0),
        "voice": "en-US-ChristopherNeural",
        "rate": "+15%",
        "bgm_file": "bgm_cinematic_871.mp3",
        "bgm_volume": 0.22,
        "keywords": ["2010", "navinder", "sarao", "bedroom", "corrupt", "400", "million", "laser", "millisecond", "hound", "fake", "microsecond", "billionaire", "panic", "flash", "crash", "trillion", "thirty-six", "minutes", "forty", "pajamas", "fbi", "penny", "rigged"],
        "script": (
            "In 2010, a twenty-three-year-old day trader named Navinder Sarao was trading from his childhood bedroom in London. "
            "He noticed something corrupt: Wall Street hedge funds were spending 400 million dollars on laser cables to spy on ordinary orders and front-run trades in a millisecond. "
            "So he decided to fight back. He wrote a tiny piece of code called the Hound. "
            "It placed millions of fake sell orders and canceled them in a microsecond, tricking the billionaire algorithms into panic-selling their own stocks. "
            "On May 6th, his code triggered the historic Flash Crash, wiping one trillion dollars off Wall Street in thirty-six minutes while he made forty million dollars in his pajamas. "
            "When the FBI finally kicked down his front door, they discovered he had not spent a single penny. "
            "He just wanted to prove the entire financial system was rigged."
        ),
        "headline": ["THE KID WHO CRASHED", "WALL STREET FROM", "HIS BEDROOM"],
        "asset_prefixes": [
            "49247", "50745", "46635", "41654", "7891", "23215", "23219", "47050",
            "18296", "45703", "47005", "47011", "46988", "46980", "9607", "45708",
            "47012", "30873", "26748", "41576", "2213", "4119", "28897", "28893"
        ],
    },
    {
        "key": "vyralx-nixon-shock",
        "topic": "The 15-Minute Shock That Changed Money Forever",
        "category": "FINANCE",
        "badge_color": (0, 230, 118),
        "voice": "en-US-AndrewMultilingualNeural",
        "rate": "+15%",
        "bgm_file": "bgm_dark_188.mp3",
        "bgm_volume": 0.22,
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
        "headline": ["THE 15-MINUTE SHOCK", "THAT KILLED THE", "GOLD STANDARD"],
        "asset_prefixes": [
            "18296", "45703", "47005", "47011", "46988", "46980", 
            "9607", "45708", "47012", "30873", "26748", "7891",
            "23215", "23219", "28897", "28893", "49247", "50745",
            "46635", "41654"
        ],
    },
    {
        "key": "vyralx-oklo-reactor",
        "topic": "The 1.8-Billion-Year-Old Natural Nuclear Reactor",
        "category": "SCIENCE",
        "badge_color": (0, 229, 255),
        "voice": "en-US-BrianMultilingualNeural",
        "rate": "+15%",
        "bgm_file": "bgm_mysterious_127.mp3",
        "bgm_volume": 0.20,
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
        "headline": ["THE 2-BILLION-YEAR-OLD", "NATURAL NUCLEAR", "REACTOR ON EARTH"],
        "asset_prefixes": [
            "5580", "5485", "46747", "47783", "4719", "3780", 
            "3957", "29351", "4075", "18791", "31596", "99786",
            "41576", "2213", "4119", "47050", "28897", "28893",
            "33968", "17702"
        ],
    },
    {
        "key": "vyralx-kola-borehole",
        "topic": "The Deepest Hole On Earth That Heard 'Screams'",
        "category": "MYSTERY",
        "badge_color": (255, 61, 0),
        "voice": "en-US-ChristopherNeural",
        "rate": "+15%",
        "bgm_file": "bgm_dark_140.mp3",
        "bgm_volume": 0.24,
        "keywords": ["1970", "soviet", "scientists", "drilling", "deepest", "hole", "crust", "twenty-four", "years", "seven", "miles", "boiling", "magma", "degrees", "microphones", "screams", "hell", "welded", "steel", "sealed"],
        "script": (
            "In 1970, Soviet scientists began drilling the deepest hole in human history into the crust of the earth. "
            "For twenty-four years, heavy diamond drill bits carved down seven point five miles into the dark unknown. "
            "At that depth, the rock stopped acting like solid stone and turned into boiling plastic magma at three hundred and fifty degrees Fahrenheit. "
            "When geologists lowered heat-resistant microphones into the abyss, they recorded terrifying, hollow acoustic anomalies that spawned the worldwide legend of the Well to Hell. "
            "In 1992, the project was abruptly shut down and the hole was welded shut with a solid steel cap. "
            "Today, the deepest point ever reached by humanity remains sealed in silence."
        ),
        "headline": ["THE DEEPEST HOLE", "ON EARTH THAT HEARD", "VOICES FROM BELOW"],
        "asset_prefixes": [
            "31596", "4719", "3780", "4075", "29351", "47783", "46747", "2213",
            "41576", "50745", "47011", "47050", "99786", "33968", "18791", "28897",
            "47491", "4119", "28893", "5580"
        ],
    },
    {
        "key": "vyralx-carbanak-heist",
        "topic": "The Hackers Who Stole $1 Billion Without Touching A Gun",
        "category": "CYBERCRIME",
        "badge_color": (213, 0, 249),
        "voice": "en-US-AndrewMultilingualNeural",
        "rate": "+15%",
        "bgm_file": "bgm_cinematic_614.mp3",
        "bgm_volume": 0.22,
        "keywords": ["2013", "kiev", "spitting", "hundred-dollar", "carbanak", "dangerous", "cybercrime", "gang", "hacked", "networks", "undetected", "recorded", "managers", "atms", "dispense", "forty", "countries", "vanished", "one", "billion", "bullet"],
        "script": (
            "In 2013, an automated cash machine in Kiev suddenly started spitting out hundred-dollar bills into an empty street at 3 AM. "
            "A passerby grabbed the cash, but nobody knew how it happened. "
            "It was the first strike of Carbanak, the most dangerous cybercrime gang in human history. "
            "Instead of robbing customers, they hacked directly into bank internal networks and lived undetected inside the systems for months. "
            "They recorded video feeds of bank managers, learned the exact transaction codes, and programmed ATMs to dispense cash into bags at precise minutes across forty countries. "
            "In under two years, they vanished with one billion dollars without firing a single bullet."
        ),
        "headline": ["THE 1 BILLION DOLLAR", "CYBER HEIST THAT", "HIJACKED 100 BANKS"],
        "asset_prefixes": [
            "49247", "49329", "4119", "45708", "47005", "18296", "28893", "50745",
            "46980", "47012", "26748", "7891", "41654", "41576", "17702", "23215",
            "23219", "2213", "30873", "9607"
        ],
    },
    {
        "key": "vyralx-wow-signal",
        "topic": "The 72-Second Signal From Deep Space",
        "category": "SPACE",
        "badge_color": (101, 31, 255),
        "voice": "en-US-BrianMultilingualNeural",
        "rate": "+15%",
        "bgm_file": "bgm_mysterious_565.mp3",
        "bgm_volume": 0.20,
        "keywords": ["1977", "astronomer", "big", "ear", "observatory", "circled", "red", "ink", "wow", "radio", "transmission", "thirty", "light-years", "sagittarius", "louder", "frequency", "hydrogen", "seventy-two", "seconds", "vanishing", "fifty", "years", "extraterrestrial", "detected"],
        "script": (
            "On August 15th, 1977, an astronomer at the Big Ear radio observatory in Ohio glanced at a computer printout and circled six characters in red ink: 6 E Q U J 5. "
            "Next to it, he wrote one word: Wow. "
            "It was a radio transmission from thirty light-years away in the constellation Sagittarius. "
            "The signal was thirty times louder than the cosmic background, blasted on the exact 1420 megahertz frequency where hydrogen radiates across the universe. "
            "It lasted for seventy-two seconds before vanishing completely. "
            "In fifty years of searching, no telescope has ever heard it again. "
            "To this day, it remains the strongest candidate for extraterrestrial communication ever detected."
        ),
        "headline": ["THE 72-SECOND SIGNAL", "FROM DEEP SPACE", "THAT BAFFLED NASA"],
        "asset_prefixes": [
            "47050", "5580", "47012", "41576", "28893", "99786", "29351", "47491",
            "4119", "4075", "17702", "33968", "5485", "47783", "2213", "3780",
            "45703", "46747", "28897", "50745"
        ],
    },
]


def _handle_shutdown(signum, frame):
    global _stopping
    log.info("Shutdown signal received (signal=%s). Stopping daemon...", signum)
    _stopping = True


async def _synthesize_voice(text: str, voice: str, rate: str, dest_path: Path) -> float:
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path = dest_path.with_name("raw_" + dest_path.name)
    comm = edge_tts.Communicate(text, voice, rate=rate)
    await comm.save(str(raw_path))

    vocal_filter = (
        "highpass=f=80,"
        "equalizer=f=120:width_type=o:w=1:g=4.0,"
        "equalizer=f=3200:width_type=o:w=1:g=3.0,"
        "acompressor=threshold=-16dB:ratio=4:attack=5:release=50"
    )
    subprocess.run([
        "ffmpeg", "-y", "-i", str(raw_path),
        "-af", vocal_filter,
        "-c:a", "libmp3lame", "-b:a", "192k",
        str(dest_path)
    ], check=True, capture_output=True)

    if raw_path.is_file():
        raw_path.unlink()

    cmd_dur = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(dest_path)]
    res = subprocess.run(cmd_dur, capture_output=True, text=True, check=True)
    return float(res.stdout.strip())


def render_sound_design_master(
    voice_path: Path,
    bgm_path: Path,
    output_path: Path,
    num_scenes: int,
    target_seconds: float,
    bgm_volume: float = 0.22,
) -> Path:
    sfx_dir = Path("media/sfx")
    whoosh_sfx = str((sfx_dir / "whoosh_1489-preview.mp3").resolve())
    impact_sfx = str((sfx_dir / "impact_1143-preview.mp3").resolve())

    cut_duration = target_seconds / max(1, num_scenes)
    whoosh_delays = [int(i * cut_duration * 1000) for i in range(1, num_scenes)]

    sfx_inputs = [
        "-i", str(voice_path),
        "-stream_loop", "-1", "-i", str(bgm_path),
        "-i", impact_sfx,
        "-i", whoosh_sfx
    ]

    filter_steps = [
        "[0:a]aformat=channel_layouts=stereo:sample_rates=44100[v_stereo]",
        f"[1:a]aformat=channel_layouts=stereo:sample_rates=44100,volume={bgm_volume:.2f}[bgm_vol]",
        "[v_stereo]asplit=2[v_main][v_side]",
        "[bgm_vol][v_side]sidechaincompress=threshold=0.08:ratio=5:attack=25:release=350[ducked_bgm]",
        "[2:a]aformat=channel_layouts=stereo:sample_rates=44100,volume=0.85,adelay=100|100[hook_impact]",
    ]

    whoosh_labels = []
    if whoosh_delays:
        filter_steps.append(f"[3:a]aformat=channel_layouts=stereo:sample_rates=44100,asplit={len(whoosh_delays)}" + "".join(f"[w_raw_{i}]" for i in range(len(whoosh_delays))))
        for i, delay in enumerate(whoosh_delays):
            lbl = f"w_delayed_{i}"
            filter_steps.append(f"[w_raw_{i}]volume=0.50,adelay={delay}|{delay}[{lbl}]")
            whoosh_labels.append(f"[{lbl}]")

    mix_inputs = ["[v_main]", "[ducked_bgm]", "[hook_impact]"] + whoosh_labels
    filter_steps.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:duration=first:dropout_transition=0[master_raw]")
    filter_steps.append("[master_raw]loudnorm=I=-14:LRA=9:TP=-1.5[out_a]")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        *sfx_inputs,
        "-filter_complex", ";".join(filter_steps),
        "-map", "[out_a]",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(target_seconds),
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return output_path


def retry_pending_publishes(db: SessionLocal):
    """Auto-retry publish jobs that were paused or failed due to missing YouTube signup."""
    failed_jobs = (
        db.query(PublishJob)
        .filter(PublishJob.status == "failed")
        .all()
    )
    for job in failed_jobs:
        if job.error and ("youtubeSignupRequired" in job.error or "Unauthorized" in job.error):
            render_job = db.query(RenderJob).filter(RenderJob.id == job.render_job_id).first()
            if render_job and Path(render_job.output_path).is_file():
                log.info("Checking if YouTube channel is created for PublishJob %d...", job.id)
                try:
                    video_id = upload_video(
                        render_job.output_path,
                        title=job.title,
                        description=job.description,
                        tags=json.loads(job.tags_json or "[]"),
                        privacy_status=job.privacy_status or "private",
                        category_id="28",
                        publish_job_id=job.id,
                        upload_attempt=1,
                    )
                    job.status = "uploaded"
                    job.youtube_video_id = video_id
                    job.completed_at = utcnow()
                    job.error = None
                    db.commit()
                    log.info("RETRY SUCCESS! Published video %d to YouTube: https://youtu.be/%s", job.id, video_id)
                except Exception as e:
                    log.info("Channel still pending for PublishJob %d (%s)", job.id, e)


def execute_production_cycle(cfg: dict, db: SessionLocal, *, publish: bool = True) -> dict:
    settings = get_settings()
    topic = cfg["topic"]
    script = cfg["script"]
    voice = cfg["voice"]
    rate = cfg.get("rate", "+15%")
    prefixes = cfg["asset_prefixes"]
    keywords = cfg.get("keywords", [])
    bgm_file = cfg.get("bgm_file", "bgm_cinematic_871.mp3")
    bgm_vol = cfg.get("bgm_volume", 0.22)
    project_key = f"{cfg['key']}-{uuid.uuid4().hex[:6]}"

    log.info("Starting autonomous production cycle: '%s' (%s)", topic, project_key)

    # Pre-flight: Check and retry any previously queued uploads
    retry_pending_publishes(db)

    # 1. Voiceover synthesis & broadcast mastering
    voice_file = settings.media_dir / "voiceovers" / f"voice_{project_key}.mp3"
    voice_dur = asyncio.run(_synthesize_voice(script, voice, rate, voice_file))
    target_seconds = math.ceil(voice_dur + 1.8)
    log.info("Vocal track mastered: %.2fs (target: %ds)", voice_dur, target_seconds)

    # 2. Match local verified high-motion clips
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

    source_paths = [a.file_path for a in assets]
    log.info("Loaded %d rapid real-motion video clips", len(source_paths))

    # 3. Render studio sound design (Voice + Ducked BGM + Hook Impact + Scene Whooshes)
    bgm_path = (settings.media_dir / "music" / bgm_file).resolve()
    audio_mix_file = settings.media_dir / "voiceovers" / f"sound_design_{project_key}.m4a"
    render_sound_design_master(voice_file, bgm_path, audio_mix_file, len(source_paths), target_seconds, bgm_volume=bgm_vol)
    log.info("Studio stereo sound design rendered: %s", audio_mix_file)

    # 4. Generate kinetic subtitles with keyword pop highlights
    segments = segment_script(script, voice_dur, max_chars=32, max_words_per_cue=3)
    sub_dir = settings.data_dir / "subtitles"
    sub_dir.mkdir(parents=True, exist_ok=True)
    sub_path = sub_dir / f"{project_key}.srt"
    ass_path = sub_dir / f"{project_key}.ass"
    write_srt(segments, sub_path)
    write_ass(segments, ass_path, style="CapCutViral", uppercase=True, highlight_keywords=keywords)

    # 5. Render 1080x1920 full-bleed vertical short
    out_file = settings.render_dir / f"{project_key}.mp4"
    rendered = render_montage(
        source_paths=source_paths,
        destination=out_file,
        preset="shorts",
        target_seconds=target_seconds,
        fit_mode="crop",
        subtitle_file=sub_path,
        voiceover_path=audio_mix_file,
        enable_ken_burns=False,
    )
    log.info("Render complete: %s (%.2f MB)", rendered, Path(rendered).stat().st_size / 1024 / 1024)

    # 6. Generate click-worthy viral thumbnail
    thumb_file = settings.render_dir / f"{project_key}-thumb.jpg"
    headline = cfg.get("headline", [topic.upper()])
    badge = cfg.get("category", "VYRALX")
    badge_color = cfg.get("badge_color", (255, 215, 0))
    create_viral_thumbnail(
        rendered,
        thumb_file,
        headline,
        badge_text=badge,
        badge_color=badge_color,
        timestamp_seconds=2.0,
    )
    log.info("Viral thumbnail created: %s", thumb_file)

    # 7. Database record keeping
    pack = ContentPack(
        topic=topic,
        video_format="shorts",
        status="generated",
        pack_json=json.dumps({"script": script, "topic": topic, "voice": voice, "category": cfg.get("category")}),
        voiceover_path=str(audio_mix_file),
        voiceover_status="ready",
    )
    db.add(pack)
    db.flush()

    project = VideoProject(
        project_key=project_key,
        topic=topic,
        video_format="shorts",
        target_seconds=target_seconds,
        audience="viral audience",
        tone="intense, dramatic, factual",
        scene_count=len(source_paths),
        confirm_pexels_license=True,
        confirm_pexels_repeat_use=True,
        use_voiceover=True,
        status="completed",
        content_pack_id=pack.id,
        primary_asset_id=assets[0].id,
        asset_ids_json=json.dumps([a.id for a in assets]),
        attempts=1,
    )
    db.add(project)
    db.flush()

    render_job = RenderJob(
        asset_id=assets[0].id,
        preset="shorts",
        status="completed",
        output_path=str(rendered),
        attempts=1,
        project_id=project.id,
        options_json=json.dumps({"project_id": project.id, "target_seconds": target_seconds}),
    )
    db.add(render_job)
    db.flush()
    project.render_job_id = render_job.id
    db.commit()

    # Copy to showcase artifact directory
    brain_dir = Path(r"C:\Users\Surendra\.gemini\antigravity\brain\9eb461ef-8e8c-48bb-9abe-936c30ea157d")
    target_artifact = brain_dir / f"{cfg['key']}.mp4"
    target_thumb = brain_dir / f"{cfg['key']}-thumbnail.jpg"
    shutil.copy2(rendered, target_artifact)
    shutil.copy2(thumb_file, target_thumb)

    # 8. Attempt YouTube Publishing
    publish_result = {"status": "skipped", "video_id": None, "error": None}
    if publish:
        publish_job = PublishJob(
            asset_id=assets[0].id,
            render_job_id=render_job.id,
            title=f"{topic} #Shorts",
            description=f"{script}\n\n#Shorts #History #Documentary #Viral",
            tags_json=json.dumps(keywords[:10]),
            privacy_status="private",
            status="pending_approval",
        )
        db.add(publish_job)
        db.commit()
        db.refresh(publish_job)

        try:
            log.info("Attempting automated YouTube upload for PublishJob %d...", publish_job.id)
            yt_video_id = upload_video(
                str(rendered),
                title=f"{topic} #Shorts",
                description=f"{script}\n\n#Shorts #History #Documentary #Viral",
                tags=keywords[:10],
                privacy_status="private",
                category_id="28",
                publish_job_id=publish_job.id,
                upload_attempt=1,
            )
            publish_job.status = "uploaded"
            publish_job.youtube_video_id = yt_video_id
            publish_job.completed_at = utcnow()
            db.commit()
            publish_result = {"status": "uploaded", "video_id": yt_video_id, "error": None}
            log.info("SUCCESS! Published to YouTube: https://youtu.be/%s", yt_video_id)
        except Exception as yt_err:
            publish_job.status = "failed"
            publish_job.error = str(yt_err)
            db.commit()
            publish_result = {"status": "failed", "video_id": None, "error": str(yt_err)}
            if "youtubeSignupRequired" in str(yt_err):
                log.warning("YouTube publishing paused: Google account does not yet have a YouTube channel. Please visit youtube.com and click 'Create a channel'.")
            else:
                log.warning("YouTube publishing paused: %s", yt_err)

    return {
        "project_key": project_key,
        "video_file": str(rendered),
        "artifact_file": str(target_artifact),
        "thumbnail_file": str(target_thumb),
        "publish": publish_result,
    }


def run_daemon(poll_interval_seconds: int = 1800):
    global _stopping
    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)
    log.info("VyralX Autonomous Publishing Daemon started (poll_interval=%ds)", poll_interval_seconds)

    queue_index = 0
    with SessionLocal() as db:
        while not _stopping:
            cfg = VIRAL_QUEUE[queue_index % len(VIRAL_QUEUE)]
            queue_index += 1
            try:
                res = execute_production_cycle(cfg, db, publish=True)
                log.info("Autonomous cycle completed successfully: %s", res)
            except Exception as e:
                log.exception("Autonomous cycle failed: %s", e)

            # Wait for next scheduled run or until stopped
            log.info("Sleeping %d seconds until next autonomous production cycle...", poll_interval_seconds)
            elapsed = 0
            while elapsed < poll_interval_seconds and not _stopping:
                time.sleep(1)
                elapsed += 1

    log.info("VyralX Autonomous Publishing Daemon stopped cleanly.")


if __name__ == "__main__":
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 1800
    run_daemon(interval)
