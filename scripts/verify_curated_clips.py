import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.mixkit import import_video_file

dna_ids = [
    ("3780", "Molecular Bonds"),
    ("3957", "Cells Interaction"),
    ("46747", "Lab Biological Samples"),
    ("47783", "Scientist Microscope"),
    ("46635", "Programming Code Tech"),
    ("4719", "Scientist Chemistry Flask"),
    ("99786", "Futuristic Tech Animation"),
    ("18791", "Cosmic Wormhole"),
    ("31596", "Fluorescent Nebula"),
    ("29351", "Earth Spinning Space")
]

wealth_ids = [
    ("18296", "Counting Wad Of Bills"),
    ("47005", "Rotating Cash Bills"),
    ("47012", "Stock Market Profit"),
    ("23219", "Data Center Hallway"),
    ("46635", "Coding Automated Engine"),
    ("30873", "Stock Market Concept 3D"),
    ("47011", "Wallet Full Of Cash"),
    ("45708", "Investor Checking Tablet"),
    ("7891", "Server Cables Room"),
    ("46988", "Dollars On Table")
]

for vid, title in dna_ids + wealth_ids:
    try:
        res = import_video_file(vid, f"https://assets.mixkit.co/videos/{vid}/{vid}-720.mp4", fallback_url=f"https://assets.mixkit.co/videos/{vid}/{vid}-360.mp4", title=title)
        w = res["metadata"]["width"]
        h = res["metadata"]["height"]
        print(f"OK:   {vid:6s} {title:25s} -> {w}x{h}")
    except Exception as e:
        print(f"FAIL: {vid:6s} {title:25s} -> {e}")
