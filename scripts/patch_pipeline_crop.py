from pathlib import Path

p = Path("app/services/project_pipeline.py")
text = p.read_text(encoding="utf-8")
old = 'fit_mode = "smart_vertical" if project.video_format == "shorts" else "pad"'
new = 'fit_mode = "crop" if project.video_format == "shorts" else "pad"'
assert old in text, "old fit_mode line not found"
text = text.replace(old, new)
p.write_text(text, encoding="utf-8")
print("Updated pipeline fit_mode to crop")
