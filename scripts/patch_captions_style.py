from pathlib import Path

p = Path("app/services/captions.py")
text = p.read_text(encoding="utf-8")
text = text.replace('"margin_v": 300', '"margin_v": 640')
text = text.replace('"outline_width": 6', '"outline_width": 8')
text = text.replace('"shadow_depth": 3', '"shadow_depth": 4')
p.write_text(text, encoding="utf-8")
print("Updated captions.py styles to margin_v=640, outline=8")
