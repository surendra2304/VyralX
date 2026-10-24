import urllib.request

def check_all():
    agents = [
        ("FRIDAY (Server 1)", "http://10.0.0.121:10000/health"),
        ("Inference (Server 1)", "http://10.0.0.121:8001/health"),
        ("Memora (Server 1)", "http://10.0.0.121:8002/health"),
        ("Stratex (Server 1)", "http://10.0.0.121:8003/health"),
        ("Futuris (Server 1)", "http://10.0.0.121:8004/health"),
        ("IntelX (Server 1)", "http://10.0.0.121:8005/health"),
        ("Forge (Server 1)", "http://10.0.0.121:8006/health"),
        ("VyralX (Server 2)", "http://10.0.0.120:8010/health"),
        ("Sentinel (Server 2)", "http://10.0.0.120:8008/health"),
        ("Cortex (Server 2)", "http://10.0.0.120:8009/health")
    ]
    print("=== FRIDAY UNIVERSE MESH HEALTH AUDIT ===")
    for name, url in agents:
        try:
            req = urllib.request.urlopen(url, timeout=3)
            code = req.getcode()
            body = req.read().decode("utf-8")[:100]
            print(f"[{code}] {name}: OK -> {body}")
        except Exception as e:
            print(f"[FAIL] {name}: {e}")

if __name__ == "__main__":
    check_all()
