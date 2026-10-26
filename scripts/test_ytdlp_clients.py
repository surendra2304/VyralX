import subprocess

clients = [
    "web",
    "web_safari",
    "mweb",
    "android",
    "ios",
    "tv",
    "tv_embedded",
    "android_embedded",
    "web_embedded",
    "android_vr"
]

url = "https://www.youtube.com/shorts/8kggT2ej-lo"

for c in clients:
    cmd = [
        "yt-dlp",
        "--extractor-args", f"youtube:player_client={c}",
        "-g",
        url
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"SUCCESS with client '{c}'!")
        print(res.stdout[:100])
        break
    else:
        err = res.stderr.split("\n")
        first_err = [l for l in err if "ERROR" in l or "Sign in" in l]
        msg = first_err[0] if first_err else err[0]
        print(f"Client '{c}' failed: {msg[:80]}")
