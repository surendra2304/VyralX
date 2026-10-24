"""VyralX High-CTR Thumbnail Designer.

Generates ultra-clickable, visually stunning YouTube Shorts & Reels thumbnails.
Features:
- Smart keyframe selection (picks highest-entropy, sharpest peak action frame)
- Cinematic color enhancement (+contrast, +saturation, +sharpness)
- Genre-specific badge pills (WILDLIFE 🐆, COMEDY 😂, SURVIVAL 🏕️, RESPECT 🏆)
- Dual-tone impact typography with heavy drop shadow and zero clipping
- Sleek modern glowing border accent
"""
from __future__ import annotations

import logging
import math
import subprocess
import textwrap
from pathlib import Path

import cv2
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from app.config import get_settings
from app.services.video_styler import get_genre_profile

log = logging.getLogger("vyralx.thumbnail_designer")


def _calculate_frame_sharpness(image_path: Path) -> float:
    """Calculate the Laplacian variance of an image to measure clarity and sharpness."""
    try:
        img = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return 0.0
        return float(cv2.Laplacian(img, cv2.CV_64F).var())
    except Exception:
        return 0.0


def _get_thumbnail_font(font_name: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """Loads heavy viral font with failover to local data/fonts directory."""
    local_candidates = [
        Path("data/fonts") / "Montserrat-Black.ttf",
        Path("data/fonts") / "Anton-Regular.ttf",
        Path("data/fonts") / font_name,
        Path("/opt/friday_universe/VyralX/data/fonts") / "Montserrat-Black.ttf",
        Path("/usr/local/share/fonts") / "Montserrat-Black.ttf",
    ]
    for cand in local_candidates:
        if cand.is_file():
            try:
                return ImageFont.truetype(str(cand.resolve()), size)
            except Exception:
                pass
    try:
        return ImageFont.truetype(font_name, size)
    except Exception:
        return ImageFont.load_default()


def extract_best_keyframe(
    video_path: Path,
    candidate_timestamps: list[float] | None = None,
    width: int = 1080,
    height: int = 1920,
) -> Image.Image:
    """Extract candidate frames across the video and return the highest-sharpness peak action frame.

    Always resolves to raw un-edited footage to guarantee zero burnt-in subtitles in the thumbnail.
    """
    settings = get_settings()

    # Priority: ALWAYS extract from raw source video to prevent capturing burned subtitles
    clean_video = video_path
    stem = video_path.stem.replace("vyralx-commentary-", "").replace("vyralx-v2-", "").replace("vyralx-remix-", "")
    for candidate_dir in [Path("media/viral_sources"), settings.media_dir / "viral_sources"]:
        potential = candidate_dir / f"{stem}.mp4"
        if potential.is_file() and potential.stat().st_size > 0:
            clean_video = potential
            break

    timestamps = candidate_timestamps or [2.0, 4.0, 6.5, 9.0, 12.0]

    best_score = -1.0
    best_image: Image.Image | None = None
    temp_dir = settings.data_dir / "temp_thumbs"
    temp_dir.mkdir(parents=True, exist_ok=True)

    for idx, ts in enumerate(timestamps):
        temp_file = temp_dir / f"cand_{idx}_{int(ts*10)}.jpg"
        filter_str = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}"
        )
        cmd = [
            settings.ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-ss", str(ts),
            "-i", str(clean_video),
            "-frames:v", "1",
            "-vf", filter_str,
            "-q:v", "2",
            str(temp_file),
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=30)
        if res.returncode == 0 and temp_file.is_file():
            score = _calculate_frame_sharpness(temp_file)
            if score > best_score:
                best_score = score
                try:
                    best_image = Image.open(temp_file).convert("RGBA")
                except Exception:
                    pass
            temp_file.unlink(missing_ok=True)

    if best_image is None:
        # Fallback to single frame at 2.0s
        fallback_file = temp_dir / "fallback.jpg"
        cmd = [
            settings.ffmpeg_bin,
            "-hide_banner",
            "-nostdin",
            "-y",
            "-ss", "2.0",
            "-i", str(clean_video),
            "-frames:v", "1",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
            "-q:v", "2",
            str(fallback_file),
        ]
        subprocess.run(cmd, capture_output=True, timeout=30)
        best_image = Image.open(fallback_file).convert("RGBA")
        fallback_file.unlink(missing_ok=True)

    return best_image


def generate_genre_thumbnail(
    video_path: Path,
    output_path: Path,
    headline: str,
    category: str,
    candidate_timestamps: list[float] | None = None,
    width: int = 1080,
    height: int = 1920,
) -> Path:
    """Generate a high-CTR, genre-styled viral thumbnail with vivid typography and badges."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    profile = get_genre_profile(category)

    # 1. Extract best action keyframe
    base_img = extract_best_keyframe(video_path, candidate_timestamps, width=width, height=height)

    # 2. Cinematic Color Enhancement
    base_img = ImageEnhance.Contrast(base_img).enhance(1.22)
    base_img = ImageEnhance.Color(base_img).enhance(1.28)
    base_img = ImageEnhance.Sharpness(base_img).enhance(1.18)

    # 3. Add smooth dark gradient at top for maximum text contrast
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    grad_height = int(height * 0.40)
    for y in range(grad_height):
        ratio = y / grad_height
        alpha = int(230 * ((1.0 + math.cos(math.pi * ratio)) / 2.0))
        draw_ov.line([(0, y), (width, y)], fill=(0, 0, 0, alpha))

    # Also add subtle bottom vignette
    bot_height = int(height * 0.18)
    for b_idx in range(bot_height):
        ratio = b_idx / bot_height
        alpha = int(180 * (ratio ** 2))
        draw_ov.line([(0, height - bot_height + b_idx), (width, height - bot_height + b_idx)], fill=(0, 0, 0, alpha))

    base_img = Image.alpha_composite(base_img, overlay)
    draw = ImageDraw.Draw(base_img)

    # 4. Subtle Outer Neon Accent Border (2px)
    border_col = (*profile.badge_color, 180)
    draw.rectangle([6, 6, width - 6, height - 6], outline=border_col, width=3)

    # 5. Category Badge Pill (Top-Left)
    badge_font = _get_thumbnail_font(profile.font_name, 36)

    bx, by = 65, 85
    badge_text = profile.badge_label
    badge_bbox = draw.textbbox((bx, by), badge_text, font=badge_font)
    draw.rounded_rectangle(
        [badge_bbox[0] - 20, badge_bbox[1] - 10, badge_bbox[2] + 20, badge_bbox[3] + 10],
        radius=14,
        fill=(10, 10, 10, 235),
        outline=(*profile.badge_color, 255),
        width=3,
    )
    draw.text((bx, by), badge_text, fill=(*profile.badge_color, 255), font=badge_font)

    # 6. Auto-fitting Headline Typography (Multi-line, Auto-wrapping, Zero-clipping)
    words = headline.strip().split()
    max_w = width - 130  # 65px margin on each side
    fitted_lines = [headline]
    fitted_font = None
    fitted_size = 76

    for size_cand in range(80, 48, -4):
        cand_font = _get_thumbnail_font(profile.font_name, size_cand)
        cand_draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        found = False
        for wrap_w in range(12, 26):
            wrap_cand = textwrap.wrap(" ".join(words), width=wrap_w)
            if len(wrap_cand) > 3:
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
        fitted_font = _get_thumbnail_font(profile.font_name, 54)
        fitted_lines = textwrap.wrap(" ".join(words), width=18)[:3]

    ty = by + (badge_bbox[3] - badge_bbox[1]) + 45
    line_spacing = int(fitted_size * 1.25)

    for idx, line in enumerate(fitted_lines):
        line_clean = line.strip().upper()
        # Dual-tone: Climax punchline line gets vivid genre accent color, earlier lines pure white
        if idx == len(fitted_lines) - 1 and len(fitted_lines) > 1:
            line_color = (*profile.badge_color, 255)
        else:
            line_color = (255, 255, 255, 255)

        draw.text(
            (65, ty),
            line_clean,
            fill=line_color,
            stroke_width=max(6, int(fitted_size * 0.11)),
            stroke_fill=(0, 0, 0, 255),
            font=fitted_font,
        )
        ty += line_spacing

    base_img.convert("RGB").save(output_path, quality=95)
    log.info("Generated high-CTR thumbnail for %s: %s", category, output_path.name)
    return output_path
