from pathlib import Path

path = Path("app/services/thumbnail.py")
content = path.read_text(encoding="utf-8")

function_code = """

def create_viral_thumbnail(
    video_path: str | Path,
    destination: str | Path,
    headline_lines: list[str] | str,
    *,
    badge_text: str = "VYRALX",
    badge_color: tuple[int, int, int] = (255, 215, 0),
    accent_color: tuple[int, int, int] = (255, 220, 0),
    timestamp_seconds: float = 1.5,
    width: int = 1080,
    height: int = 1920,
) -> str:
    \"\"\"Generate high-contrast, high-CTR viral thumbnail with category badge and bold headline.\"\"\"
    settings = get_settings()
    source = Path(video_path).resolve()
    output = Path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError("Video source for thumbnail does not exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    temp_frame = output.with_suffix(".temp_frame.jpg")

    filter_str = (
        f"[0:v:0]trim=start={timestamp_seconds}:duration=1,split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},boxblur=25:5[bg_b];"
        f"[fg]scale={width}:-2:force_original_aspect_ratio=decrease[fg_s];"
        f"[bg_b][fg_s]overlay=(W-w)/2:(H-h)/2,setsar=1[outv]"
    )
    cmd = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
        "-i", str(source),
        "-filter_complex", filter_str,
        "-map", "[outv]",
        "-frames:v", "1",
        "-q:v", "2",
        str(temp_frame),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=45, check=True)
    except Exception:
        cmd_fallback = [
            settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
            "-ss", str(float(timestamp_seconds)), "-i", str(source),
            "-frames:v", "1", "-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
            "-q:v", "2", str(temp_frame),
        ]
        subprocess.run(cmd_fallback, capture_output=True, timeout=45, check=True)

    from PIL import Image, ImageDraw, ImageFont, ImageEnhance

    im = Image.open(temp_frame).convert("RGBA")
    temp_frame.unlink(missing_ok=True)

    # 1. Enhance visual pop
    im = ImageEnhance.Contrast(im).enhance(1.22)
    im = ImageEnhance.Color(im).enhance(1.30)
    im = ImageEnhance.Sharpness(im).enhance(1.15)

    # 2. Add subtle dark gradient at top
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

    lines = [headline_lines] if isinstance(headline_lines, str) else list(headline_lines)
    ty = 190
    for idx, line in enumerate(lines):
        line_clean = line.strip().upper()
        color = (*accent_color, 255) if (idx == len(lines) - 1 and len(lines) > 1) else (255, 255, 255, 255)
        draw.text((60, ty), line_clean, fill=color, stroke_width=9, stroke_fill=(0, 0, 0, 255), font=font_title)
        ty += 115

    im.convert("RGB").save(output, quality=95)
    return str(output)
"""

if "def create_viral_thumbnail" not in content:
    content += function_code
    path.write_text(content, encoding="utf-8")
    print("Added create_viral_thumbnail to thumbnail.py")
else:
    print("Already present")
