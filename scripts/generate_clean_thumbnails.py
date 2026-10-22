import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import subprocess
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from app.config import get_settings

settings = get_settings()

def generate_viral_thumbnail(
    raw_video_path: str | Path,
    output_path: str | Path,
    headline_lines: list[str],
    *,
    badge_text: str = "VYRALX",
    badge_color: tuple[int, int, int] = (255, 215, 0),
    accent_color: tuple[int, int, int] = (255, 220, 0),
    timestamp_seconds: float = 1.5,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    raw_video = Path(raw_video_path).resolve()
    out = Path(output_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    temp_frame = out.with_suffix(".temp_raw.jpg")

    # Extract framed vertical 1080x1920 shot from raw video using mirror blur background
    filter_str = (
        f"[0:v:0]trim=start={timestamp_seconds}:duration=1,split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=25:5[bg_b];"
        f"[fg]scale={width}:-2:force_original_aspect_ratio=decrease[fg_s];"
        f"[bg_b][fg_s]overlay=(W-w)/2:(H-h)/2,setsar=1[outv]"
    )
    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
        "-i", str(raw_video),
        "-filter_complex", filter_str,
        "-map", "[outv]",
        "-frames:v", "1",
        "-q:v", "2",
        str(temp_frame),
    ]
    subprocess.run(cmd, capture_output=True, check=True)

    im = Image.open(temp_frame).convert("RGBA")
    temp_frame.unlink(missing_ok=True)

    # 1. Enhance visual pop
    im = ImageEnhance.Contrast(im).enhance(1.22)
    im = ImageEnhance.Color(im).enhance(1.30)
    im = ImageEnhance.Sharpness(im).enhance(1.15)

    # 2. Add subtle top dark gradient
    w, h = im.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    for y in range(int(h * 0.40)):
        alpha = int(210 * (1.0 - (y / (h * 0.40))))
        draw_ov.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    im = Image.alpha_composite(im, overlay)
    draw = ImageDraw.Draw(im)

    # 3. Category Badge
    try:
        badge_font = ImageFont.truetype("arialbd.ttf", 40)
    except Exception:
        badge_font = ImageFont.load_default()
    bx, by = 60, 90
    bbox = draw.textbbox((bx, by), badge_text, font=badge_font)
    draw.rounded_rectangle(
        [bbox[0] - 20, bbox[1] - 10, bbox[2] + 20, bbox[3] + 10],
        radius=14,
        fill=(0, 0, 0, 220),
        outline=(*badge_color, 255),
        width=3,
    )
    draw.text((bx, by), badge_text, fill=(*badge_color, 255), font=badge_font)

    # 4. Bold Viral Headline
    try:
        font_title = ImageFont.truetype("ariblk.ttf", 86)
    except Exception:
        font_title = ImageFont.load_default()

    ty = 190
    for idx, line in enumerate(headline_lines):
        line_clean = line.strip().upper()
        # Last line gets the punchline accent color
        color = (*accent_color, 255) if (idx == len(headline_lines) - 1 and len(headline_lines) > 1) else (255, 255, 255, 255)
        # Drop shadow + outline
        draw.text((60, ty), line_clean, fill=color, stroke_width=9, stroke_fill=(0, 0, 0, 255), font=font_title)
        ty += 115

    im.convert("RGB").save(out, quality=95)
    return out

# Generate for Wealth Short
wealth_raw = next(Path("media/stock_videos").glob("mixkit-18296*.mp4"))
thumb_wealth = generate_viral_thumbnail(
    wealth_raw,
    "renders/thumb_wealth_viral.jpg",
    ["DON'T TRADE", "TIME FOR MONEY"],
    badge_text="VYRALX WEALTH",
    badge_color=(255, 215, 0),
    accent_color=(255, 220, 0),
)
print("Wealth thumbnail created:", thumb_wealth)

# Generate for DNA Short (Earth or Microscope or Molecule)
dna_raw = next(Path("media/stock_videos").glob("mixkit-29351*.mp4"))
thumb_dna = generate_viral_thumbnail(
    dna_raw,
    "renders/thumb_dna_viral.jpg",
    ["HUMAN DNA IS", "NOT HUMAN"],
    badge_text="VYRALX SCIENCE",
    badge_color=(0, 255, 230),
    accent_color=(0, 255, 230),
    timestamp_seconds=2.0,
)
print("DNA thumbnail created:", thumb_dna)
