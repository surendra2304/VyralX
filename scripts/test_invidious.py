import json
import urllib.request

instances = [
    "https://api.piped.private.coffee/streams/8kggT2ej-lo",
    "https://pipedapi.leptons.xyz/streams/8kggT2ej-lo",
    "https://inv.nadeko.net/api/v1/videos/8kggT2ej-lo",
    "https://invidious.nerdvpn.de/api/v1/videos/8kggT2ej-lo",
    "https://invidious.projectsegfau.lt/api/v1/videos/8kggT2ej-lo"
]

for url in instances:
    print(f"Trying {url}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"SUCCESS on {url}!")
            if "videoStreams" in data:
                print(f"Piped found {len(data['videoStreams'])} video streams!")
                for s in data["videoStreams"][:2]:
                    print(f"  Quality: {s.get('quality')}, URL: {s.get('url')[:60]}...")
            elif "formatStreams" in data:
                print(f"Invidious found {len(data['formatStreams'])} format streams!")
                for s in data["formatStreams"][:2]:
                    print(f"  Resolution: {s.get('resolution')}, URL: {s.get('url')[:60]}...")
            break
    except Exception as e:
        print(f"Failed {url}: {e}")
