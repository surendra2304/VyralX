#!/usr/bin/env python3
"""VyralX Next-Gen Futuristic Cinematic Thumbnail Engine.

Design Principles:
1. ZERO cheesy badge pills (NO 'COMEDY', NO 'VIRAL', NO rounded boxes).
2. ZERO tacky border outlines.
3. High Dynamic Range (HDR) Color Grading: Deep cinematic shadows, rich saturation, micro-contrast.
4. Radial cinematic lighting: Soft radial vignette focusing attention on key action.
5. Futuristic Holographic Typography:
   - Ultra-bold punch phrases (2 words max per line, 2 lines max).
   - Multi-layer neon ambient glow (Electric Cyan #00E5FF / Cyber Gold #FFD700).
   - Deep 3D drop shadow for maximum legibility on any display.
"""
from __future__ import annotations

import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont


def get_font(size: int) -> ImageFont.FreeTypeFont:
    for cand in [
        Path("data/fonts/Montserrat-Black.ttf"),
        Path("data/fonts/Anton-Regular.ttf"),
        Path("data/fonts/BebasNeue-Regular.ttf"),
    ]:
        if cand.is_file():
            try:
                return ImageFont.truetype(str(cand.resolve()), size)
            except Exception:
                pass
    return ImageFont.load_default()


def apply_cinematic_grade(img: Image.Image) -> Image.Image:
    """Enhance colors, micro-contrast, and sharpness for cinematic punch."""
    img = ImageEnhance.Contrast(img).enhance(1.28)
    img = ImageEnhance.Color(img).enhance(1.30)
    img = ImageEnhance.Sharpness(img).enhance(1.35)
    return img


def apply_futuristic_atmosphere(img: Image.Image, accent_color: tuple[int, int, int]) -> Image.Image:
    """Adds a smooth cinematic vignette and subtle futuristic ambient lighting."""
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # 1. Smooth Dark Top Gradient for Text Legibility
    top_h = int(h * 0.42)
    for y in range(top_h):
        ratio = y / top_h
        alpha = int(220 * ((1.0 + math.cos(math.pi * ratio)) / 2.0))
        draw.line([(0, y), (w, y)], fill=(5, 8, 15, alpha))

    # 2. Cinematic Bottom Vignette
    bot_h = int(h * 0.22)
    for y in range(bot_h):
        ratio = y / bot_h
        alpha = int(160 * (ratio ** 2))
        draw.line([(0, h - bot_h + y), (w, h - bot_h + y)], fill=(0, 0, 0, alpha))

    # 3. Futuristic Subtle Top Rim Glow
    glow_h = int(h * 0.08)
    for y in range(glow_h):
        ratio = y / glow_h
        alpha = int(70 * (1.0 - ratio))
        draw.line([(0, y), (w, y)], fill=(*accent_color, alpha))

    return Image.alpha_composite(img.convert("RGBA"), overlay)


def render_futuristic_text(
    base: Image.Image,
    line1: str,
    line2: str,
    accent_color: tuple[int, int, int],
    line1_color: tuple[int, int, int] | None = None,
    font_size: int = 96,
    top_y: int = 140,
) -> Image.Image:
    """Renders 2-line high-impact futuristic typography with neon ambient glow and 3D shadow."""
    w, h = base.size
    font = get_font(font_size)

    # Create glow layer for gaussian blur
    glow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)

    # Shadow layer
    shadow_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_layer)

    # Text layer
    text_layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    text_draw = ImageDraw.Draw(text_layer)

    lines = [(line1, line1_color or accent_color), (line2, (255, 255, 255))]
    line_h = int(font_size * 1.18)

    for idx, (text, col) in enumerate(lines):
        if not text:
            continue
        cur_y = top_y + (idx * line_h)
        bbox = text_draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        # Center text horizontally with high-end margins
        cur_x = int((w - text_w) / 2)

        # 1. Heavy Neon Glow behind text
        glow_draw.text((cur_x, cur_y), text, font=font, fill=(*accent_color, 240), stroke_width=18, stroke_fill=(*accent_color, 240))

        # 2. 3D Hard Shadow
        for off_x, off_y in [(0, 6), (4, 6), (-4, 6), (0, 10), (4, 10)]:
            shadow_draw.text((cur_x + off_x, cur_y + off_y), text, font=font, fill=(0, 0, 0, 240), stroke_width=8, stroke_fill=(0, 0, 0, 240))

        # 3. Crisp Foreground Text
        text_draw.text((cur_x, cur_y), text, font=font, fill=(*col, 255), stroke_width=4, stroke_fill=(0, 0, 0, 255))

    # Apply blur to glow layer for authentic futuristic bloom
    blurred_glow = glow_layer.filter(ImageFilter.GaussianBlur(radius=16))

    # Composite layers: base -> blurred_glow -> shadow -> sharp text
    comp = Image.alpha_composite(base, blurred_glow)
    comp = Image.alpha_composite(comp, shadow_layer)
    comp = Image.alpha_composite(comp, text_layer)
    return comp


def create_thumbnails():
    out_dir = Path("media/edited_videos").resolve()

    # --- Video 1: Michelin Restaurant ---
    # Best sharpest frame with tuxedo man + soap bubbles
    m_src = Path("media/thumb_cands/michelin_11.5s.jpg")
    m_img = Image.open(m_src).convert("RGBA")
    m_img = apply_cinematic_grade(m_img)
    m_img = apply_futuristic_atmosphere(m_img, accent_color=(0, 229, 255))  # Electric Cyan
    m_final = render_futuristic_text(
        m_img,
        line1="$10,000,000",
        line2="SOAP DINNER?",
        accent_color=(0, 229, 255),       # Cyan Neon Glow
        line1_color=(255, 215, 0),        # Cyber Gold Text
        font_size=104,
        top_y=130,
    )
    m_dest = out_dir / "vyralx-commentary-A_Q2qpbHrqo-thumbnail.jpg"
    m_final.convert("RGB").save(m_dest, quality=98)
    print(f"Generated futuristic thumbnail 1 -> {m_dest}")

    # --- Video 2: Main Character Energy ---
    # Sharpest frame (sharpness 638.0) of girl walking down hallway with total confidence
    c_src = Path("media/thumb_cands/mainchar_34.0s.jpg")
    c_img = Image.open(c_src).convert("RGBA")
    c_img = apply_cinematic_grade(c_img)
    c_img = apply_futuristic_atmosphere(c_img, accent_color=(0, 240, 255))
    c_final = render_futuristic_text(
        c_img,
        line1="1000% ENERGY",
        line2="UNBOTHERED",
        accent_color=(0, 229, 255),       # Electric Cyan Neon Glow
        line1_color=(0, 229, 255),        # Electric Cyan Text
        font_size=102,
        top_y=130,
    )
    c_dest = out_dir / "vyralx-commentary-hx265ujsLVU-thumbnail.jpg"
    c_final.convert("RGB").save(c_dest, quality=98)
    print(f"Generated futuristic thumbnail 2 -> {c_dest}")


if __name__ == "__main__":
    create_thumbnails()
