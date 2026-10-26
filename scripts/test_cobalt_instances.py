import json
import urllib.request

try:
    print("Fetching active open Cobalt instances...")
    req = urllib.request.Request("https://instances.hyper.lol/instances.json", headers={"User-Agent": "VyralX/2.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        instances = json.loads(resp.read().decode("utf-8"))
        print(f"Total instances found: {len(instances)}")
        open_apis = []
        for inst in instances:
            # Check for online and api enabled
            if inst.get("api") and inst.get("online"):
                url = inst.get("protocol", "https") + "://" + inst.get("api")
                open_apis.append(url)
        print(f"Active API instances ({len(open_apis)}): {open_apis[:5]}")

        test_url = "https://www.youtube.com/shorts/8kggT2ej-lo"
        for api_url in open_apis[:8]:
            try:
                print(f"Testing {api_url}...")
                post_req = urllib.request.Request(
                    api_url,
                    data=json.dumps({"url": test_url}).encode("utf-8"),
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0"
                    }
                )
                with urllib.request.urlopen(post_req, timeout=8) as p_resp:
                    res_data = json.loads(p_resp.read().decode("utf-8"))
                    print(f"SUCCESS with {api_url} -> {res_data}")
                    break
            except Exception as e:
                print(f"  {api_url} failed: {e}")
except Exception as err:
    print(f"Failed to fetch instances: {err}")
