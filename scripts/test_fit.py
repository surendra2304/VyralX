import subprocess
from pathlib import Path
from PIL import Image
import numpy as np

fonts_dir = str(Path('data/fonts').resolve()).replace('\\', '/')
d, r = fonts_dir.split(':', 1)
fonts_dir_escaped = f'{d}\\:{r}'

base = np.array(Image.open('media/test_frames/base_frame.jpg').convert('RGB'), dtype=np.int16)

test_phrase = "HUNDRED NINETY-NINE"

for font in ['Montserrat Black', 'Poppins Black']:
    for size in [95, 100, 105, 110]:
        slug = font.replace(' ', '_').lower()
        ass_content = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Test,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,5.5,3.0,2,60,60,450,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,Test,,0,0,0,,{{\\c&H00FFE500&}}HUNDRED{{\\c&H00FFFFFF&}} NINETY-NINE
"""
        ass_path = Path(f'media/voiceovers/test_fit_{slug}_{size}.ass').resolve()
        ass_path.write_text(ass_content, encoding='utf-8')
        
        ass_esc = str(ass_path).replace('\\', '/')
        ad, ar = ass_esc.split(':', 1)
        ass_filter_path = f'{ad}\\:{ar}'
        
        out_jpg = Path(f'media/test_frames/fit_{slug}_{size}.jpg')
        
        cmd = [
            'ffmpeg', '-y', '-ss', '00:00:03', '-i', 'media/viral_sources/A_Q2qpbHrqo.mp4',
            '-vf', f'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,subtitles=\'{ass_filter_path}\':fontsdir=\'{fonts_dir_escaped}\'',
            '-vframes', '1', str(out_jpg)
        ]
        subprocess.run(cmd, capture_output=True)
        
        sub = np.array(Image.open(out_jpg).convert('RGB'), dtype=np.int16)
        diff = np.abs(sub - base)
        mask = np.any(diff > 30, axis=2)
        y_idx, x_idx = np.where(mask)
        if len(x_idx) > 0:
            min_x, max_x = np.min(x_idx), np.max(x_idx)
            min_y, max_y = np.min(y_idx), np.max(y_idx)
            w = max_x - min_x
            h = max_y - min_y
            print(f'{font} {size}pt: X=[{min_x}, {max_x}] width={w}px (margin={min_x}), height={h}px, multiline={h > 80}')
