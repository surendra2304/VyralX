import httpx
import re

keywords = [
    "laboratory", "microscope", "chemistry", "earth", "space", 
    "nebula", "technology", "money", "cash", "dollars", 
    "stock-market", "data-center", "server-room"
]

for kw in keywords:
    try:
        r = httpx.get(f"https://mixkit.co/free-stock-video/{kw}/", follow_redirects=True, timeout=8.0)
        is_disc = "/discover/" in str(r.url) or "no results" in r.text.lower()
        matches = re.findall(r"/free-stock-video/([a-zA-Z0-9\-]+)-(\d+)/", r.text)
        # Filter footer links
        footer = {"41576", "2213", "4119", "4075", "1610"}
        real = [(slug, vid) for slug, vid in matches if vid not in footer]
        print(f"{kw:15s} -> status={r.status_code} is_discover={is_disc} count={len(real)} sample={real[:2]}")
    except Exception as e:
        print(f"{kw:15s} -> error: {e}")
