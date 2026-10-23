import subprocess
from pathlib import Path

# Let's test 3 different high-end subtitle styles on a frame of A_Q2qpbHrqo

def render_style(style_num: int, style_str: str, text: str, out_img: str):
    ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
{style_str}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,TestStyle,,0,0,0,,{text}
"""
    ass_file = f"temp_style_{style_num}.ass"
    Path(ass_file).write_text(ass_content, encoding="utf-8")

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-ss", "00:00:04.0",
        "-i", "media/viral_sources/A_Q2qpbHrqo.mp4",
        "-vf", f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles={ass_file}",
        "-vframes", "1", out_img
    ]
    subprocess.run(cmd, check=True)
    print(f"Rendered style {style_num} -> {out_img}")

# Style 1: Electric Yellow MrBeast / Hormozi (Impact, heavy outline, vibrant yellow)
s1 = "Style: TestStyle,Impact,68,&H0000EEFF,&H000000FF,&H00000000,&H80000000,0,0,0,0,100,100,1.5,0,1,5.0,3.0,2,80,80,380,1"
t1 = "SERVES HIM LITERAL SOAP FOAM"

# Style 2: Modern CapCut Dark Frosted Pill (Montserrat, white text in sleek dark translucent box)
s2 = "Style: TestStyle,Montserrat,56,&H00FFFFFF,&H000000FF,&H00000000,&H90000000,1,0,0,0,100,100,1.0,0,3,10.0,0.0,2,80,80,380,1"
t2 = "{\\c&H00FFFFFF&}SERVES HIM {\\c&H0024E8FF&}SOAP FOAM"

# Style 3: Clean Ultra-Bold Duo-Tone (Arial Black, crisp white + golden punchword, sharp 4px stroke + 2px drop shadow)
s3 = "Style: TestStyle,Arial Black,62,&H00FFFFFF,&H000000FF,&H00000000,&H90000000,1,0,0,0,100,100,1.2,0,1,4.5,2.5,2,80,80,380,1"
t3 = "SERVES HIM {\\c&H0000E6FF&}SOAP FOAM"

render_style(1, s1, t1, "style_1_yellow.jpg")
render_style(2, s2, t2, "style_2_pill.jpg")
render_style(3, s3, t3, "style_3_duotone.jpg")
