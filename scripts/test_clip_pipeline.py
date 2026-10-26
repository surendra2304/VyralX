import json
import subprocess
from pathlib import Path
import httpx

dest = Path("media/viral_sources/mixkit_31596.mp4")
dest.parent.mkdir(parents=True, exist_ok=True)
url = "https://assets.mixkit.co/videos/31596/31596-720.mp4"
print(f"Downloading supercar drift clip directly on Server 2 from {url}...")
with httpx.Client(timeout=30.0, follow_redirects=True) as client:
    resp = client.get(url)
    if resp.status_code == 200:
        dest.write_bytes(resp.content)
        print(f"Downloaded {dest.name} ({len(resp.content)/(1024*1024):.2f} MB)")

res = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", str(dest)], capture_output=True, text=True)
info = json.loads(res.stdout)
for s in info.get("streams", []):
    print(f"Stream {s.get('codec_type')}: codec={s.get('codec_name')}, dur={s.get('duration')}s, res={s.get('width')}x{s.get('height')}")
