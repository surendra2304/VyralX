import json
import subprocess
import urllib.request

print("--- Testing Reddit Video Fetch ---")
try:
    req = urllib.request.Request(
        "https://www.reddit.com/r/oddlysatisfying/top.json?t=month&limit=10",
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        video_posts = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            if d.get("is_video") and d.get("media"):
                fallback_url = d["media"].get("reddit_video", {}).get("fallback_url")
                dur = d["media"].get("reddit_video", {}).get("duration", 0)
                video_posts.append({
                    "id": d.get("id"),
                    "title": d.get("title"),
                    "url": d.get("url"),
                    "fallback_url": fallback_url,
                    "duration": dur,
                    "ups": d.get("ups")
                })
        print(f"Found {len(video_posts)} viral Reddit videos:")
        for vp in video_posts[:3]:
            print(f"  - [{vp['ups']} ups, {vp['duration']}s] {vp['title'][:50]} -> {vp['fallback_url']}")
except Exception as e:
    print(f"Reddit fetch failed: {e}")

print("\n--- Testing yt-dlp Reddit Video Extraction ---")
if 'video_posts' in locals() and video_posts:
    test_url = video_posts[0]["url"]
    print(f"Testing yt-dlp on {test_url}...")
    res = subprocess.run(["yt-dlp", "-g", test_url], capture_output=True, text=True)
    if res.returncode == 0:
        print("yt-dlp successfully extracted Reddit video stream URL!")
        print(res.stdout[:150])
    else:
        print(f"yt-dlp failed on Reddit: {res.stderr[:200]}")
