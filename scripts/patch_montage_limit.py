from pathlib import Path

p = Path("app/services/montage.py")
t = p.read_text(encoding="utf-8")
old = "if not 2 <= len(source_paths) <= 12:"
new = "if not 2 <= len(source_paths) <= 32:"
assert old in t, "old montage limit not found"
t = t.replace(old, new)
old_msg = '"Montage requires 2–12 scene clips"'
new_msg = '"Montage requires 2–32 scene clips"'
if old_msg in t:
    t = t.replace(old_msg, new_msg)
p.write_text(t, encoding="utf-8")
print("Updated montage.py to support up to 32 scene clips")
