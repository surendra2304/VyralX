from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from pathlib import Path

img_path = Path("renders/v2_scene1_cash.jpg")
im = Image.open(img_path).convert("RGBA")

# 1. Enhance color and contrast
im = ImageEnhance.Contrast(im).enhance(1.2)
im = ImageEnhance.Color(im).enhance(1.3)

# 2. Add top dark gradient for text readability
w, h = im.size
overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
draw = ImageDraw.Draw(overlay)

for y in range(int(h * 0.38)):
    alpha = int(190 * (1.0 - (y / (h * 0.38))))
    draw.line([(0, y), (w, y)], fill=(0, 0, 0, alpha))

im = Image.alpha_composite(im, overlay)
draw = ImageDraw.Draw(im)

# 3. Draw Category Badge
badge_text = "VYRALX WEALTH"
try:
    badge_font = ImageFont.truetype("arialbd.ttf", 36)
except Exception:
    badge_font = ImageFont.load_default()

bx, by = 60, 80
bbox = draw.textbbox((bx, by), badge_text, font=badge_font)
draw.rounded_rectangle([bbox[0]-16, bbox[1]-8, bbox[2]+16, bbox[3]+8], radius=12, fill=(0, 0, 0, 200), outline=(255, 215, 0, 255), width=3)
draw.text((bx, by), badge_text, fill=(255, 215, 0, 255), font=badge_font)

# 4. Draw Bold Viral Headline
headline_1 = "DON'T TRADE"
headline_2 = "TIME FOR MONEY"
try:
    font_title = ImageFont.truetype("ariblk.ttf", 84)
except Exception:
    font_title = ImageFont.load_default()

ty = 160
draw.text((60, ty), headline_1, fill=(255, 255, 255), stroke_width=8, stroke_fill=(0, 0, 0), font=font_title)
draw.text((60, ty + 105), headline_2, fill=(255, 220, 0), stroke_width=8, stroke_fill=(0, 0, 0), font=font_title)

out_path = Path("renders/test_viral_thumb.jpg")
im.convert("RGB").save(out_path, quality=95)
print("Saved:", out_path.is_file(), "size:", out_path.stat().st_size)
