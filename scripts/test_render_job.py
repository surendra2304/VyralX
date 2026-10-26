import json
import logging
import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

from app.services.autonomous_pipeline import create_visual_job_from_source, render_video

clip_path = Path("media/viral_sources/mixkit_31596.mp4")
print(f"Creating visual job for {clip_path}...")
job = create_visual_job_from_source(clip_path, voice="en-US-GuyNeural")

print("\n--- GENERATED VIRAL METADATA ---")
print(f"Title: {job.title}")
print(f"Hook: {job.hook}")
print(f"Voice: {job.voice}")
print(f"Script ({len(job.script.split())} words):\n{job.script}")
print(f"Debate Question: {job.debate_question}")
print(f"Tags: {job.tags[:5]}")

print("\n--- RENDERING TEST VIDEO ON SERVER 2 ---")
output_path = Path("media/edited_videos/test_supercar_render.mp4")
rendered = render_video(job, output_path)

print(f"\nSUCCESS! Rendered file: {rendered} ({rendered.stat().st_size / (1024*1024):.2f} MB)")

# Verify with ffprobe
import subprocess
res = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(rendered)], capture_output=True, text=True)
info = json.loads(res.stdout)
print("\n--- RENDERED STREAMS ---")
for s in info.get("streams", []):
    print(f"  Stream {s.get('codec_type')}: codec={s.get('codec_name')}, res={s.get('width')}x{s.get('height')}, dur={s.get('duration')}s")
