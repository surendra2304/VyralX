from pathlib import Path

path = Path("app/services/montage.py")
content = path.read_text(encoding="utf-8")
content = content.replace("if enable_ken_burns and is_still:", "if enable_ken_burns:")
path.write_text(content, encoding="utf-8")
print("Updated montage.py")
