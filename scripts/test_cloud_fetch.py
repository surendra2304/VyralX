import json
import urllib.request

print("--- 1. Testing Reddit with API User-Agent ---")
try:
    url = "https://www.reddit.com/r/oddlysatisfying/top.json?t=month&limit=5"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "python:com.vyralx.studio:v2.0 (by /u/vyralx_bot)"}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        posts = [c["data"]["title"] for c in data.get("data", {}).get("children", [])]
        print(f"Reddit SUCCESS! Retrieved {len(posts)} posts:")
        for p in posts[:3]:
            print(f"  - {p[:60]}")
except Exception as e:
    print(f"Reddit failed: {e}")

print("\n--- 2. Testing Cobalt Public API Instances for YouTube/TikTok ---")
cobalt_instances = [
    "https://cobalt-api.kwiatekm.tokyo",
    "https://api.cobalt.tools",
    "https://cobalt.api.sc",
    "https://api.wuk.sh"
]

test_short = "https://www.youtube.com/shorts/8kggT2ej-lo"
for c_url in cobalt_instances:
    try:
        print(f"Testing Cobalt at {c_url}...")
        payload = json.dumps({"url": test_short}).encode("utf-8")
        req = urllib.request.Request(
            c_url,
            data=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "VyralX/2.0"
            }
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            print(f"Cobalt SUCCESS at {c_url}: {res_data}")
            break
    except Exception as e:
        print(f"Cobalt instance {c_url} notice: {e}")
