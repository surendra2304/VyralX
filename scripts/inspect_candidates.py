import subprocess
import json
import sys

sys.stdout.reconfigure(encoding="utf-8")

for vid in ["sOZrJUkCLYU", "JjuQ2ink05Q", "bS_CSAPHjUY", "k--pkJcePTM", "BmW5Qb3fqlk", "heI4DLab-l8"]:
    res = subprocess.run(["yt-dlp", "--skip-download", "--dump-json", f"https://youtube.com/shorts/{vid}"], capture_output=True, text=True, encoding="utf-8")
    if res.stdout:
        try:
            d = json.loads(res.stdout)
            print(f"{vid} | Views: {d.get('view_count'):,} | Title: {d.get('title')}")
        except Exception as e:
            print(vid, e)
