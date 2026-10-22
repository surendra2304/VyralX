from pathlib import Path

p = Path("app/services/project_pipeline.py")
t = p.read_text(encoding="utf-8")

old = """        try:
            category_badge = "VYRALX SCIENCE" if any(w in project.topic.lower() for w in ("dna", "science", "space", "bio")) else "VYRALX WEALTH"
            create_viral_thumbnail(
                assets[0].file_path,
                thumbnail,
                thumb_lines,
                badge_text=category_badge,
                badge_color=(0, 255, 230) if "SCIENCE" in category_badge else (255, 215, 0),
                accent_color=(0, 255, 230) if "SCIENCE" in category_badge else (255, 220, 0),
                timestamp_seconds=1.5,
            )"""

new = """        try:
            topic_lower = project.topic.lower()
            if any(w in topic_lower for w in ("psych", "mind", "trick", "liar", "dark", "fbi", "secret")):
                category_badge = "VYRALX PSYCHOLOGY"
                badge_color = (255, 60, 90)
                accent_color = (255, 80, 110)
            elif any(w in topic_lower for w in ("dna", "science", "space", "bio")):
                category_badge = "VYRALX SCIENCE"
                badge_color = (0, 255, 230)
                accent_color = (0, 255, 230)
            else:
                category_badge = "VYRALX WEALTH"
                badge_color = (255, 215, 0)
                accent_color = (255, 220, 0)

            create_viral_thumbnail(
                assets[0].file_path,
                thumbnail,
                thumb_lines,
                badge_text=category_badge,
                badge_color=badge_color,
                accent_color=accent_color,
                timestamp_seconds=1.5,
            )"""

assert old.replace("\r\n", "\n") in t.replace("\r\n", "\n"), "old badge snippet not found"
t_up = t.replace("\r\n", "\n").replace(old.replace("\r\n", "\n"), new)
p.write_text(t_up, encoding="utf-8")
print("Updated category badge logic successfully")
