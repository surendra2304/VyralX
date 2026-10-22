"""Deterministic thumbnail extraction using FFmpeg."""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

from app.config import get_settings


def extract_thumbnail(render_path: str | Path, destination: str | Path, timestamp_seconds: float) -> str:
    settings = get_settings()
    source = Path(render_path).resolve()
    output = Path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError("Rendered video does not exist")
    if timestamp_seconds < 0:
        raise ValueError("Thumbnail timestamp must be non-negative")
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        settings.ffmpeg_bin, "-hide_banner", "-nostdin", "-y",
        "-ss", str(float(timestamp_seconds)), "-i", str(source),
        "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "2", str(output),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Thumbnail extraction exceeded 45 seconds") from exc
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        output.unlink(missing_ok=True)
        raise RuntimeError((result.stderr or "FFmpeg thumbnail extraction failed")[-1500:])
    return str(output)


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
    """Generate high-contrast, high-CTR viral thumbnail with category badge and bold headline."""
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
    import textwrap

    im = Image.open(temp_frame).convert("RGBA")
    temp_frame.unlink(missing_ok=True)

    # 1. Enhance visual pop
    im = ImageEnhance.Contrast(im).enhance(1.25)
    im = ImageEnhance.Color(im).enhance(1.30)
    im = ImageEnhance.Sharpness(im).enhance(1.15)

    # 2. Add smooth dark gradient at top for maximum text contrast
    w, h = im.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    grad_height = int(h * 0.45)
    for y in range(grad_height):
        ratio = y / grad_height
        alpha = int(225 * ((1.0 + math.cos(math.pi * ratio)) / 2.0))
        draw_ov.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))
    im = Image.alpha_composite(im, overlay)
    draw = ImageDraw.Draw(im)

    # 3. Category Badge Pill
    try:
        badge_font = ImageFont.truetype("arialbd.ttf", 38)
    except Exception:
        badge_font = ImageFont.load_default()
    bx, by = 70, 95
    badge_bbox = draw.textbbox((bx, by), badge_text, font=badge_font)
    draw.rounded_rectangle(
        [badge_bbox[0] - 22, badge_bbox[1] - 12, badge_bbox[2] + 22, badge_bbox[3] + 12],
        radius=14,
        fill=(0, 0, 0, 230),
        outline=(*badge_color, 255),
        width=3,
    )
    draw.text((bx, by), badge_text, fill=(*badge_color, 255), font=badge_font)

    # 4. Auto-Fitting Headline Typography (prevents any canvas clipping)
    if isinstance(headline_lines, str):
        full_text = headline_lines
    else:
        full_text = " ".join(headline_lines)
    words = full_text.split()

    max_w = w - 140  # 70px margin on each side
    fitted_lines = [full_text]
    fitted_font = None
    fitted_size = 76

    for size_cand in range(84, 46, -4):
        try:
            cand_font = ImageFont.truetype("ariblk.ttf", size_cand)
        except Exception:
            cand_font = ImageFont.load_default()
            fitted_font = cand_font
            break

        cand_draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        found = False
        for wrap_w in range(12, 28):
            wrap_cand = textwrap.wrap(" ".join(words), width=wrap_w)
            if len(wrap_cand) > 4:
                continue
            widths = [
                cand_draw.textbbox((0, 0), line.upper(), font=cand_font)[2]
                - cand_draw.textbbox((0, 0), line.upper(), font=cand_font)[0]
                for line in wrap_cand
            ]
            if all(wd <= max_w for wd in widths):
                fitted_lines = wrap_cand
                fitted_font = cand_font
                fitted_size = size_cand
                found = True
                break
        if found:
            break

    if fitted_font is None:
        try:
            fitted_font = ImageFont.truetype("ariblk.ttf", 52)
        except Exception:
            fitted_font = ImageFont.load_default()
        fitted_lines = textwrap.wrap(" ".join(words), width=22)[:4]

    ty = by + (badge_bbox[3] - badge_bbox[1]) + 45
    line_spacing = int(fitted_size * 1.25)
    for idx, line in enumerate(fitted_lines):
        line_clean = line.strip().upper()
        color = (*accent_color, 255) if (idx == len(fitted_lines) - 1 and len(fitted_lines) > 1) else (255, 255, 255, 255)
        draw.text(
            (70, ty),
            line_clean,
            fill=color,
            stroke_width=max(6, int(fitted_size * 0.10)),
            stroke_fill=(0, 0, 0, 255),
            font=fitted_font,
        )
        ty += line_spacing

    im.convert("RGB").save(output, quality=95)
    return str(output)
