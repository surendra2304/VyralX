from pathlib import Path

path = Path("app/services/project_pipeline.py")
content = path.read_text(encoding="utf-8")

# 1. Update external TTS handling to preserve caption_segments
old_tts = """                else:
                    voice = synthesize_voiceover(caption_text, target_seconds=project.target_seconds)
                    voice_path = str(voice["file_path"])
                    # External TTS returns audio bytes but no forced-alignment result.
                    # Never claim that its captions are synchronized based on duration alone.
                    pack.pop("caption_segments", None)
                    caption_alignment_status = "estimated"
                pack["caption_alignment_status"] = caption_alignment_status"""

new_tts = """                else:
                    voice = synthesize_voiceover(caption_text, target_seconds=project.target_seconds)
                    voice_path = str(voice["file_path"])
                    if isinstance(voice.get("caption_segments"), list) and voice["caption_segments"]:
                        segments = voice["caption_segments"]
                        caption_alignment_status = str(voice.get("caption_alignment_status") or "word_forced")
                        pack["caption_segments"] = segments
                    else:
                        pack.pop("caption_segments", None)
                        caption_alignment_status = "estimated"
                pack["caption_alignment_status"] = caption_alignment_status"""

# 2. Update render_target_seconds to prevent ending cutoff
old_target = """        fit_mode = "smart_vertical" if project.video_format == "shorts" else "pad"
        render_job = RenderJob(
            asset_id=assets[0].id,
            preset=project.video_format,
            status="running",
            attempts=1,
            started_at=utcnow(),
            options_json=json.dumps({
                "project_id": project.id,
                "montage_asset_ids": [asset.id for asset in assets],
                "subtitle_segments": segments,
                "voiceover_path": voice_path,
                "fit_mode": fit_mode,
                "target_seconds": project.target_seconds,
            }, ensure_ascii=False),
            project_id=project.id,
        )
        db.add(render_job)
        db.flush()
        project.status = "rendering"
        project.render_job_id = render_job.id
        project.primary_asset_id = assets[0].id
        project.asset_ids_json = json.dumps([asset.id for asset in assets])
        project.updated_at = utcnow()
        db.commit()
        db.refresh(render_job)
        db.refresh(project)

        output_path = settings.render_dir / f"{project.project_key}-attempt-{project.attempts}.mp4"
        enable_motion = getattr(settings, "render_enable_ken_burns", True)
        rendered = render_montage(
            [asset.file_path for asset in assets],
            output_path,
            project.video_format,
            target_seconds=project.target_seconds,"""

new_target = """        fit_mode = "smart_vertical" if project.video_format == "shorts" else "pad"
        render_target_seconds = project.target_seconds
        if project.use_voiceover and voiceover_duration and voiceover_duration > 0:
            render_target_seconds = max(project.target_seconds, math.ceil(voiceover_duration + 0.8))

        render_job = RenderJob(
            asset_id=assets[0].id,
            preset=project.video_format,
            status="running",
            attempts=1,
            started_at=utcnow(),
            options_json=json.dumps({
                "project_id": project.id,
                "montage_asset_ids": [asset.id for asset in assets],
                "subtitle_segments": segments,
                "voiceover_path": voice_path,
                "fit_mode": fit_mode,
                "target_seconds": render_target_seconds,
            }, ensure_ascii=False),
            project_id=project.id,
        )
        db.add(render_job)
        db.flush()
        project.status = "rendering"
        project.render_job_id = render_job.id
        project.primary_asset_id = assets[0].id
        project.asset_ids_json = json.dumps([asset.id for asset in assets])
        project.updated_at = utcnow()
        db.commit()
        db.refresh(render_job)
        db.refresh(project)

        output_path = settings.render_dir / f"{project.project_key}-attempt-{project.attempts}.mp4"
        enable_motion = getattr(settings, "render_enable_ken_burns", True)
        rendered = render_montage(
            [asset.file_path for asset in assets],
            output_path,
            project.video_format,
            target_seconds=render_target_seconds,"""

# 3. Update thumbnail generation to use create_viral_thumbnail
old_thumb = """        thumbnail = settings.render_dir / f"{project.project_key}-thumbnail.jpg"
        extract_thumbnail(rendered, thumbnail, min(1.0, max(0.0, project.target_seconds / 4)))"""

new_thumb = """        thumbnail = settings.render_dir / f"{project.project_key}-thumbnail.jpg"
        from app.services.thumbnail import create_viral_thumbnail
        thumb_lines = [project.topic[:20], project.topic[20:45]] if len(project.topic) > 20 else [project.topic]
        if pack.get("title_options") and isinstance(pack["title_options"], list):
            primary_title = str(pack["title_options"][0]).replace("#Shorts", "").replace("#shorts", "").strip()
            words_title = primary_title.split()
            if len(words_title) >= 4:
                mid = len(words_title) // 2
                thumb_lines = [" ".join(words_title[:mid]), " ".join(words_title[mid:])]
            else:
                thumb_lines = [primary_title]
        try:
            category_badge = "VYRALX SCIENCE" if any(w in project.topic.lower() for w in ("dna", "science", "space", "bio")) else "VYRALX WEALTH"
            create_viral_thumbnail(
                assets[0].file_path,
                thumbnail,
                thumb_lines,
                badge_text=category_badge,
                badge_color=(0, 255, 230) if "SCIENCE" in category_badge else (255, 215, 0),
                accent_color=(0, 255, 230) if "SCIENCE" in category_badge else (255, 220, 0),
                timestamp_seconds=1.5,
            )
        except Exception as thumb_exc:
            log.warning("Viral thumbnail creation failed (%s), falling back to frame extraction", thumb_exc)
            extract_thumbnail(rendered, thumbnail, min(1.0, max(0.0, project.target_seconds / 4)))"""

content_norm = content.replace("\r\n", "\n")
assert old_tts.replace("\r\n", "\n") in content_norm, "old_tts not found"
assert old_target.replace("\r\n", "\n") in content_norm, "old_target not found"
assert old_thumb.replace("\r\n", "\n") in content_norm, "old_thumb not found"

content_norm = content_norm.replace(old_tts.replace("\r\n", "\n"), new_tts.replace("\r\n", "\n"))
content_norm = content_norm.replace(old_target.replace("\r\n", "\n"), new_target.replace("\r\n", "\n"))
content_norm = content_norm.replace(old_thumb.replace("\r\n", "\n"), new_thumb.replace("\r\n", "\n"))

path.write_text(content_norm, encoding="utf-8")
print("project_pipeline.py updated successfully")
