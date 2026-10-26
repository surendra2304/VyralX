import json
import urllib.request
import urllib.parse

print("--- Testing Wikimedia Commons Video API ---")
try:
    # Search for popular vertical/viral videos on Wikimedia Commons
    url = "https://commons.wikimedia.org/w/api.php?action=query&list=search&srsearch=filetype:video%20stunt&srnamespace=6&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "VyralX/2.0 (mailto:admin@vyralx.ai)"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        items = data.get("query", {}).get("search", [])
        print(f"Wikimedia found {len(items)} items:")
        for item in items[:2]:
            print(f"  - {item['title']}")
except Exception as e:
    print(f"Wikimedia error: {e}")

print("\n--- Testing Cobalt Tools API v10 Request Format ---")
try:
    c_url = "https://api.cobalt.tools"
    payload = json.dumps({"url": "https://www.youtube.com/watch?v=8kggT2ej-lo"}).encode("utf-8")
    req = urllib.request.Request(
        c_url,
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        res_data = json.loads(resp.read().decode("utf-8"))
        print(f"Cobalt response: {res_data}")
except urllib.error.HTTPError as he:
    print(f"Cobalt HTTP {he.code}: {he.read().decode('utf-8')[:300]}")
except Exception as e:
    print(f"Cobalt general error: {e}")

print("\n--- Testing Archive.org Video Search ---")
try:
    a_url = "https://archive.org/advancedsearch.php?q=mediatype:movies+AND+subject:stunt&fl[]=identifier,title,downloads&sort[]=downloads+desc&rows=3&page=1&output=json"
    req = urllib.request.Request(a_url, headers={"User-Agent": "VyralX/2.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        docs = data.get("response", {}).get("docs", [])
        print(f"Archive.org found {len(docs)} viral movies:")
        for doc in docs:
            print(f"  - [{doc.get('downloads')} dl] {doc.get('title')} (id: {doc.get('identifier')})")
            print(f"    Download: https://archive.org/download/{doc.get('identifier')}/{doc.get('identifier')}_512kb.mp4")
except Exception as e:
    print(f"Archive.org error: {e}")
