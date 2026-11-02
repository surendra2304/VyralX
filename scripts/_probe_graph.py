import yt_dlp

CHANNELS = {
    "boxtoxtv": "UCCfKlFlKYBxZ-UU2dWc17IQ",
    "Red Bull": "UCblfuW_4rakIf2h6aqANefA",
    "nishi tiwari": "UC8238GT1G2CmJ9bsmKpL-jw",
    "CuRe": "UCkLNHZZsC3LKdUAroKNwOOw",
    "H&T Official": "UCYCh5_-In6wtzWR-s_kM03w",
}
for name, cid in CHANNELS.items():
    url = f"https://www.youtube.com/channel/{cid}/shorts"
    try:
        with yt_dlp.YoutubeDL(
            {"quiet": True, "no_warnings": True, "skip_download": True, "playlistend": 15, "ignoreerrors": True}
        ) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        print("FAIL", name, type(exc).__name__, str(exc)[:80])
        continue
    entries = [e for e in (info.get("entries") or []) if e]
    shorts = [e for e in entries if e.get("duration") and 10 <= e["duration"] <= 58]
    print("===", name, "n", len(entries), "short", len(shorts))
    for e in shorts[:5]:
        print("   ", e.get("id"), e.get("duration"), e.get("view_count"), "|", str(e.get("title"))[:45])
