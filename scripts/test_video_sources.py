import re
import requests

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# 1. Test Mixkit
r = requests.get("https://mixkit.co/free-stock-video/technology/", headers=headers, timeout=10)
print("Mixkit status:", r.status_code)
videos = list(set(re.findall(r'https://assets\.mixkit\.co/videos/[^"\'\s]+\.mp4', r.text)))
print("Mixkit videos found:", len(videos))
for v in videos[:3]:
    print(" -", v)

# 2. Test Coverr
r_coverr = requests.get("https://api.coverr.co/videos?query=technology&page=1", headers=headers, timeout=10)
print("Coverr API status:", r_coverr.status_code)
if r_coverr.status_code == 200:
    data = r_coverr.json()
    hits = data.get("hits", [])
    print("Coverr hits:", len(hits))
    for h in hits[:3]:
        print(" - Coverr URL:", h.get("urls", {}).get("mp4"))
