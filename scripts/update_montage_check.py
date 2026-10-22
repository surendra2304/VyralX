from pathlib import Path

path = Path("app/services/montage.py")
content = path.read_text(encoding="utf-8")

old_check = """    if not 2 <= len(source_paths) <= 8:
        raise ValueError("Montage requires 2–8 scene clips")
    if preset not in PRESETS:
        raise ValueError("Unknown render preset")
    if fit_mode not in {"pad", "crop"}:
        raise ValueError("fit_mode must be pad or crop")"""

new_check = """    if not 2 <= len(source_paths) <= 12:
        raise ValueError("Montage requires 2–12 scene clips")
    if preset not in PRESETS:
        raise ValueError("Unknown render preset")
    if fit_mode not in {"pad", "crop", "blur_pad", "smart_vertical"}:
        raise ValueError("fit_mode must be pad, crop, blur_pad, or smart_vertical")"""

# Normalize \r\n for matching
content_norm = content.replace("\r\n", "\n")
assert old_check in content_norm, "old_check not found in montage.py"
content_updated = content_norm.replace(old_check, new_check)
path.write_text(content_updated, encoding="utf-8")
print("montage.py check updated successfully")
