#!/usr/bin/env python3
import subprocess
import json

queries = [
    "oddly satisfying visual craft silent",
    "insane human precision trickshot silent",
    "mesmerizing soap cutting satisfying asmr",
    "satisfying industrial loop machine silent"
]

results = []
for q in queries:
    cmd = [
        "yt-dlp", "--skip-download", "--dump-json",
        f"ytsearch2:{q}",
        "--match-filter", "duration <= 60 & duration >= 15"
    ]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    for line in p.stdout.strip().split("\n"):
        if not line:
            continue
        try:
            d = json.loads(line)
            results.append({
                "id": d.get("id"),
                "title": d.get("title"),
                "views": d.get("view_count"),
                "duration": d.get("duration"),
                "url": f"https://youtube.com/shorts/{d.get('id')}"
            })
        except Exception:
            pass

print(json.dumps(results[:6], indent=2))
