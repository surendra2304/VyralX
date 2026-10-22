from pathlib import Path

p = Path("app/services/montage.py")
t = p.read_text(encoding="utf-8")
old = '"-c:v", "libx264", "-preset", "veryfast", "-crf", "23",'
new = '"-c:v", "libx264", "-preset", "veryfast", "-crf", "25", "-maxrate", "2200k", "-bufsize", "3500k",'
assert old in t
t = t.replace(old, new)
p.write_text(t, encoding="utf-8")
print("Updated montage.py video bitrate settings")
