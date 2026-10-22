from pathlib import Path

path = Path("app/services/project_pipeline.py")
content = path.read_text(encoding="utf-8")

old_bgm_target = """        fit_mode = "smart_vertical" if project.video_format == "shorts" else "pad"
        render_target_seconds = project.target_seconds
        if project.use_voiceover and voiceover_duration and voiceover_duration > 0:
            render_target_seconds = max(project.target_seconds, math.ceil(voiceover_duration + 0.8))"""

new_bgm_target = """        render_target_seconds = project.target_seconds
        if project.use_voiceover and voiceover_duration and voiceover_duration > 0:
            render_target_seconds = max(project.target_seconds, math.ceil(voiceover_duration + 0.8))
            project.target_seconds = render_target_seconds
            db.commit()

        fit_mode = "smart_vertical" if project.video_format == "shorts" else "pad" """

content_norm = content.replace("\r\n", "\n")
assert old_bgm_target.replace("\r\n", "\n") in content_norm, "old_bgm_target not found"
content_updated = content_norm.replace(old_bgm_target.replace("\r\n", "\n"), new_bgm_target.replace("\r\n", "\n"))
path.write_text(content_updated, encoding="utf-8")
print("Updated project_pipeline.py successfully")
