from pathlib import Path

path = Path("app/services/thumbnail.py")
content = path.read_text(encoding="utf-8")

old_code = """    from PIL import Image, ImageDraw, ImageFont, ImageEnhance

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
    return str(output)"""

new_code = """    from PIL import Image, ImageDraw, ImageFont, ImageEnhance
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
    return str(output)"""

content_norm = content.replace("\r\n", "\n")
assert old_code.replace("\r\n", "\n") in content_norm, "old_code not found"
content_updated = content_norm.replace(old_code.replace("\r\n", "\n"), new_code)
path.write_text(content_updated, encoding="utf-8")
print("Updated thumbnail.py successfully")
