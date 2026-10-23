import subprocess
from pathlib import Path

fonts_dir = str(Path('data/fonts').resolve()).replace('\\', '/')
if ':' in fonts_dir:
    drive, rest = fonts_dir.split(':', 1)
    fonts_dir_escaped = f"{drive}\\:{rest}"
else:
    fonts_dir_escaped = fonts_dir

cyan = r"{\c&H00FFE500&}"
white = r"{\c&H00FFFFFF&}"

ass = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: AntonPunch,Anton,96,&H00FFFFFF,&H000000FF,&H00000000,&HAA000000,0,0,0,0,100,100,1.5,0,1,6.0,3.5,2,70,70,450,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:10.00,AntonPunch,,0,0,0,,FIVE-STAR {cyan}MICHELIN DINNER{white}
"""
Path('temp_anton_96.ass').write_text(ass, encoding='utf-8')

cmd = [
    'ffmpeg', '-hide_banner', '-y',
    '-ss', '00:00:04.0',
    '-i', 'media/viral_sources/A_Q2qpbHrqo.mp4',
    '-vf', f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles=temp_anton_96.ass:fontsdir='{fonts_dir_escaped}'",
    '-vframes', '1', 'anton_test_96.jpg'
]
subprocess.run(cmd, check=True)
print('Rendered anton 96 successfully')
