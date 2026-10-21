"""Dynamic Ken Burns motion and camera trajectory engine for video montage rendering."""
from __future__ import annotations

import logging

log = logging.getLogger("vyralx.visual_motion")

SUPPORTED_MOTIONS = {
    "zoom_in",
    "zoom_out",
    "pan_right",
    "pan_left",
    "subtle_drift",
    "static",
}


def build_motion_filter(
    motion_type: str,
    width: int,
    height: int,
    *,
    duration_frames: int = 90,
    fps: int = 30,
    zoom_max: float = 1.15,
) -> str:
    """Build an FFmpeg zoompan filter expression for smooth cinematic camera movement."""
    mode = str(motion_type).lower().strip()
    if mode not in SUPPORTED_MOTIONS:
        mode = "zoom_in"

    w = int(width)
    h = int(height)
    d = max(1, int(duration_frames))
    z_max = max(1.05, min(float(zoom_max), 1.30))
    rate = (z_max - 1.0) / d

    if mode == "static":
        return f"scale={w}:{h}"

    if mode == "zoom_in":
        # Slowly zooms from 1.0 to z_max centered
        return (
            f"zoompan=z='min(zoom+{rate:.5f},{z_max:.2f})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={d}:s={w}x{h}:fps={fps}"
        )

    if mode == "zoom_out":
        # Slowly zooms out from z_max back to 1.0
        return (
            f"zoompan=z='if(lte(on,1),{z_max:.2f},max(1.0,zoom-{rate:.5f}))':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
            f"d={d}:s={w}x{h}:fps={fps}"
        )

    if mode == "pan_right":
        # Slight zoom with smooth pan from left to right
        z = 1.10
        pan_step = (w * (z - 1.0)) / d
        return (
            f"zoompan=z={z:.2f}:"
            f"x='min(iw-iw/zoom,on*{pan_step:.3f})':y='ih/2-(ih/zoom/2)':"
            f"d={d}:s={w}x{h}:fps={fps}"
        )

    if mode == "pan_left":
        # Slight zoom with smooth pan from right to left
        z = 1.10
        pan_step = (w * (z - 1.0)) / d
        return (
            f"zoompan=z={z:.2f}:"
            f"x='max(0,(iw-iw/zoom)-on*{pan_step:.3f})':y='ih/2-(ih/zoom/2)':"
            f"d={d}:s={w}x{h}:fps={fps}"
        )

    # subtle_drift: gentle pan and slow zoom
    return (
        f"zoompan=z='min(zoom+{rate*0.6:.5f},{1.08:.2f})':"
        f"x='iw/2-(iw/zoom/2)+sin(on/10)*8':y='ih/2-(ih/zoom/2)':"
        f"d={d}:s={w}x{h}:fps={fps}"
    )


def assign_scene_motions(scene_count: int, *, alternating: bool = True) -> list[str]:
    """Assign complementary motion trajectories across montage scenes to prevent viewer fatigue."""
    count = max(1, int(scene_count))
    if not alternating:
        return ["zoom_in"] * count

    sequence = ["zoom_in", "pan_right", "zoom_out", "pan_left", "subtle_drift"]
    assignments = []
    for i in range(count):
        assignments.append(sequence[i % len(sequence)])
    return assignments
