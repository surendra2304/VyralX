import subprocess
from pathlib import Path

fonts_dir = str(Path('data/fonts').resolve()).replace('\\', '/')
if ':' in fonts_dir:
    drive, rest = fonts_dir.split(':', 1)
    fonts_dir_escaped = f"{drive}\\:{rest}"
else:
    fonts_dir_escaped = fonts_dir

# Test wide, open, comfortable fonts:
# 1. Montserrat-Black (Wide, geometric, modern, un-squeezed)
# 2. Poppins-Black (Round, friendly, wide, extremely easy to look at)

configs = [
    ("Montserrat Black", 90, "SOAP BUBBLES", "wide_montserrat_90.jpg"),
    ("Poppins Black", 90, "SOAP BUBBLES", "wide_poppins_90.jpg"),
    ("Montserrat Black", 105, "SOAP BUBBLES", "wide_montserrat_105.jpg"),
    ("Poppins Black", 105, "SOAP BUBBLES", "wide_poppins_105.jpg"),
]

cyan = r"{\c&H00FFE500&}"
white = r"{\c&H00FFFFFF&}"

for font_name, size, text, out_name in configs:
    ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: WideComfort,{font_name},{size},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,5.0,3.0,2,60,60,450,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,WideComfort,,0,0,0,,LITERAL {cyan}SOAP BUBBLES{white}
"""
    clean_key = font_name.replace(" ", "_")
    ass_path = Path(f"temp_wide_{clean_key}_{size}.ass")
    ass_path.write_text(ass, encoding="utf-8")

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-ss", "00:00:04.0",
        "-i", "media/viral_sources/A_Q2qpbHrqo.mp4",
        "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles={ass_path}:fontsdir='{fonts_dir_escaped}'",
        "-vframes", "1", out_name
    ]
    subprocess.run(cmd, check=True)
    print(f"Rendered {font_name} {size} -> {out_name}")
