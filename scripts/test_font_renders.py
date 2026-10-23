import subprocess
from pathlib import Path

fonts_dir = str(Path('data/fonts').resolve()).replace('\\', '/')
if ':' in fonts_dir:
    drive, rest = fonts_dir.split(':', 1)
    fonts_dir_escaped = f"{drive}\\:{rest}"
else:
    fonts_dir_escaped = fonts_dir

font_configs = [
    ("Anton", 88, "SOAP BUBBLES", "font_anton.jpg"),
    ("Montserrat Black", 78, "SOAP BUBBLES", "font_montserrat.jpg"),
    ("Poppins Black", 78, "SOAP BUBBLES", "font_poppins.jpg"),
    ("Bebas Neue", 92, "SOAP BUBBLES", "font_bebas.jpg"),
]

for font_name, size, text, out_name in font_configs:
    ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: BigFont,{font_name},{size},&H00FFFFFF,&H000000FF,&H00000000,&HA0000000,0,0,0,0,100,100,2,0,1,5.5,3.0,2,60,60,420,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,BigFont,,0,0,0,,{text}
"""
    clean_key = font_name.replace(" ", "_")
    ass_path = Path(f"temp_{clean_key}.ass")
    ass_path.write_text(ass, encoding="utf-8")

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-ss", "00:00:04.0",
        "-i", "media/viral_sources/A_Q2qpbHrqo.mp4",
        "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles={ass_path}:fontsdir='{fonts_dir_escaped}'",
        "-vframes", "1", out_name
    ]
    subprocess.run(cmd, check=True)
    print(f"Rendered {font_name} at size {size} -> {out_name}")
