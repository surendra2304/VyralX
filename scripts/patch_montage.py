from pathlib import Path

path = Path("app/services/montage.py")
content = path.read_text(encoding="utf-8")

old_snippet = """        if fit_mode == "crop":
            framing = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:(in_w-out_w)/2:(in_h-out_h)/2"
            )
        else:
            framing = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
        if enable_ken_burns:
            from app.services.visual_motion import assign_scene_motions, build_motion_filter

            motions = motion_effects or assign_scene_motions(len(sources))
            motion_type = motions[index % len(motions)]
            motion_filter = build_motion_filter(
                motion_type, width, height, duration_frames=max(30, int(segment_seconds * 30)), fps=30
            )
            filters.append(
                f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
                f"setpts=PTS-STARTPTS,{framing},{motion_filter},setsar=1[{label}]"
            )
        else:
            filters.append(
                f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
                f"setpts=PTS-STARTPTS,{framing},setsar=1[{label}]"
            )"""

new_snippet = """        is_still = sources[index].suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        if fit_mode in ("blur_pad", "smart_vertical"):
            bg_raw = f"bgraw_{index}"
            fg_raw = f"fgraw_{index}"
            bg_blur = f"bgblur_{index}"
            fg_scaled = f"fgscaled_{index}"
            filters.append(
                f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
                f"setpts=PTS-STARTPTS,split=2[{bg_raw}][{fg_raw}]"
            )
            filters.append(
                f"[{bg_raw}]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},boxblur=25:5[{bg_blur}]"
            )
            filters.append(
                f"[{fg_raw}]scale={width}:-2:force_original_aspect_ratio=decrease[{fg_scaled}]"
            )
            filters.append(
                f"[{bg_blur}][{fg_scaled}]overlay=(W-w)/2:(H-h)/2,setsar=1[{label}]"
            )
        elif fit_mode == "crop":
            framing = (
                f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:(in_w-out_w)/2:(in_h-out_h)/2"
            )
            if enable_ken_burns and is_still:
                from app.services.visual_motion import assign_scene_motions, build_motion_filter

                motions = motion_effects or assign_scene_motions(len(sources))
                motion_type = motions[index % len(motions)]
                motion_filter = build_motion_filter(
                    motion_type, width, height, duration_frames=max(30, int(segment_seconds * 30)), fps=30
                )
                filters.append(
                    f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
                    f"setpts=PTS-STARTPTS,{framing},{motion_filter},setsar=1[{label}]"
                )
            else:
                filters.append(
                    f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
                    f"setpts=PTS-STARTPTS,{framing},setsar=1[{label}]"
                )
        else:
            framing = (
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black"
            )
            if enable_ken_burns and is_still:
                from app.services.visual_motion import assign_scene_motions, build_motion_filter

                motions = motion_effects or assign_scene_motions(len(sources))
                motion_type = motions[index % len(motions)]
                motion_filter = build_motion_filter(
                    motion_type, width, height, duration_frames=max(30, int(segment_seconds * 30)), fps=30
                )
                filters.append(
                    f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
                    f"setpts=PTS-STARTPTS,{framing},{motion_filter},setsar=1[{label}]"
                )
            else:
                filters.append(
                    f"[{index}:v:0]fps=30,trim=duration={segment_seconds:.4f},"
                    f"setpts=PTS-STARTPTS,{framing},setsar=1[{label}]"
                )"""

assert old_snippet in content, "old_snippet not found in montage.py"
path.write_text(content.replace(old_snippet, new_snippet), encoding="utf-8")
print("montage.py updated successfully")
