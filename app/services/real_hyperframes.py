"""
VyralX — hyperframes Engine

Write HTML, render video. Agent-first video pipeline with scene rendering,
frame composition, and content-to-video transformation.

Key concepts: HTML scene rendering, frame composition, text-to-video,
scene transitions, aspect ratio handling, and rendering pipeline.

Tests: tests/test_real_batch4a.py
"""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HTMLScene:
    """An HTML scene for video rendering."""
    scene_id: str
    html_content: str
    duration: float = 5.0
    title: str = ""
    bg_color: str = "#000000"
    text_color: str = "#FFFFFF"
    transition: str = "fade"
    width: int = 1920
    height: int = 1080

    @staticmethod
    def create_scene(html_content: str, title: str = "", duration: float = 5.0) -> HTMLScene:
        sid = hashlib.md5(f"{title}:{html_content[:50]}".encode()).hexdigest()[:12]
        return HTMLScene(
            scene_id=f"scene-{sid}",
            html_content=html_content,
            title=title,
            duration=duration,
        )

    @property
    def aspect_ratio(self) -> str:
        w, h = self.width, self.height
        if abs(w / h - 16 / 9) < 0.05:
            return "16:9"
        elif abs(w / h - 9 / 16) < 0.05:
            return "9:16"
        elif abs(w / h - 1) < 0.05:
            return "1:1"
        return f"{w}:{h}"

    @property
    def text_content(self) -> str:
        text = re.sub(r'<[^>]+>', '', self.html_content)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @property
    def element_count(self) -> int:
        tags = re.findall(r'<(\w+)', self.html_content)
        return len(tags)

    @property
    def has_animation(self) -> bool:
        return any(anim in self.html_content for anim in ["@keyframes", "animation", "transition"])

    @property
    def has_responsive_design(self) -> bool:
        return "viewport" in self.html_content or "@media" in self.html_content

    def to_frame_count(self, fps: int = 30) -> int:
        return int(self.duration * fps)

    def scene_hash(self) -> str:
        return hashlib.sha256(self.html_content.encode()).hexdigest()[:16]


@dataclass
class FrameCompositor:
    """Frame composition and rendering."""
    fps: int = 30
    total_frames: int = 0

    @staticmethod
    def frames_for_scene(scene: HTMLScene, fps: int = 30) -> int:
        return int(scene.duration * fps)

    @staticmethod
    def frames_for_video(duration: float, fps: int = 30) -> int:
        return int(duration * fps)

    @staticmethod
    def calculate_file_size(resolution: tuple[int, int], duration: float, fps: int = 30, bitrate_mbps: float = 8.0) -> float:
        width, height = resolution
        total_bits = width * height * 3 * bitrate_mbps * 1_000_000 * duration / (width * height * 3 * 1_000_000)
        return total_bits / 8 / 1_024_024

    @staticmethod
    def total_video_duration(scenes: list[HTMLScene]) -> float:
        return sum(s.duration for s in scenes)

    @staticmethod
    def render_time_estimate(scenes: list[HTMLScene], render_speed: float = 1.0) -> float:
        total_duration = FrameCompositor.total_video_duration(scenes)
        total_frames = int(total_duration * 30)
        return total_frames * render_speed

    @staticmethod
    def transition_frames(transition: str, fps: int = 30) -> int:
        transition_durations = {
            "fade": 0.5,
            "cut": 0.0,
            "slide": 0.5,
            "wipe": 0.3,
            "dissolve": 0.5,
        }
        duration = transition_durations.get(transition, 0.5)
        return int(duration * fps)

    @staticmethod
    def scene_resolution(scenes: list[HTMLScene]) -> tuple[int, int]:
        if not scenes:
            return (1920, 1080)
        return (scenes[0].width, scenes[0].height)

    def add_scenes(self, scenes: list[HTMLScene]) -> None:
        self.total_frames = int(sum(s.duration for s in scenes) * self.fps)

    @property
    def total_duration(self) -> float:
        return self.total_frames / self.fps if self.fps > 0 else 0.0


@dataclass
class SceneTransition:
    """Scene transition definition."""
    from_scene: str
    to_scene: str
    type: str = "fade"
    duration: float = 0.5

    @staticmethod
    def fade(duration: float = 0.5) -> SceneTransition:
        return SceneTransition(from_scene="", to_scene="", type="fade", duration=duration)

    @staticmethod
    def cut() -> SceneTransition:
        return SceneTransition(from_scene="", to_scene="", type="cut", duration=0.0)

    @staticmethod
    def slide(direction: str = "left", duration: float = 0.5) -> SceneTransition:
        transition = SceneTransition(from_scene="", to_scene="", type="slide", duration=duration)
        transition._direction = direction
        return transition

    @staticmethod
    def wipe(direction: str = "left", duration: float = 0.3) -> SceneTransition:
        transition = SceneTransition(from_scene="", to_scene="", type="wipe", duration=duration)
        transition._direction = direction
        return transition

    def render_css(self) -> str:
        if self.type == "fade":
            return f"transition: opacity {self.duration}s ease-in-out;"
        elif self.type == "slide":
            direction = getattr(self, "_direction", "left")
            return f"transition: transform {self.duration}s ease-in-out;"
        elif self.type == "wipe":
            return f"transition: clip-path {self.duration}s ease-in-out;"
        else:
            return ""


@dataclass
class VideoScript:
    """Video script with scenes."""
    title: str
    scenes: list[HTMLScene] = field(default_factory=list)
    transitions: list[SceneTransition] = field(default_factory=list)

    @staticmethod
    def from_text(text: str, title: str = "Untitled") -> VideoScript:
        sentences = [s.strip() for s in re.split(r'[.!?]', text) if s.strip()]
        scenes = []
        for i, sentence in enumerate(sentences):
            scene = HTMLScene.create_scene(
                f"<div class=\"scene\"><h1>{title}</h1><p>{sentence}</p></div>",
                title=f"Scene {i+1}",
                duration=3.0,
            )
            scenes.append(scene)
        return VideoScript(title=title, scenes=scenes)

    def add_scene(self, scene: HTMLScene) -> None:
        self.scenes.append(scene)

    def total_duration(self) -> float:
        return sum(s.duration for s in self.scenes)

    def total_frames(self, fps: int = 30) -> int:
        return int(self.total_duration() * fps)

    def scene_count(self) -> int:
        return len(self.scenes)

    def to_scene_list(self) -> list[dict[str, Any]]:
        return [
            {"scene_id": s.scene_id, "title": s.title, "duration": s.duration, "aspect": s.aspect_ratio}
            for s in self.scenes
        ]


@dataclass
class RenderPipeline:
    """Video rendering pipeline."""
    fps: int = 30
    output_format: str = "mp4"
    bitrate: float = 8.0

    @staticmethod
    def estimate_render_time(script: VideoScript, render_speed: float = 1.0) -> float:
        total_frames = script.total_frames()
        return total_frames * render_speed / 30

    @staticmethod
    def estimate_file_size(script: VideoScript, resolution: tuple[int, int], bitrate: float = 8.0) -> float:
        duration = script.total_duration()
        width, height = resolution
        megabits = bitrate * duration
        return megabits / 8

    @staticmethod
    def render_progress(frame: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return frame / total

    @staticmethod
    def encoding_settings(resolution: tuple[int, int], fps: int, bitrate: float) -> dict[str, Any]:
        width, height = resolution
        return {
            "width": width,
            "height": height,
            "fps": fps,
            "bitrate_kbps": int(bitrate * 1000),
            "codec": "h264",
            "pixel_format": "yuv420p",
            "profile": "high",
        }

    @staticmethod
    def scene_pacing(script: VideoScript) -> dict[str, Any]:
        total = script.total_duration()
        if total <= 0:
            return {"avg_scene_duration": 0.0, "fast_scenes": [], "slow_scenes": []}
        avg = total / script.scene_count() if script.scene_count() > 0 else 0.0
        fast = [s for s in script.scenes if s.duration < avg * 0.5]
        slow = [s for s in script.scenes if s.duration > avg * 2.0]
        return {
            "avg_scene_duration": avg,
            "fast_scenes": [s.scene_id for s in fast],
            "slow_scenes": [s.scene_id for s in slow],
        }


@dataclass
class AspectRatioHandler:
    """Aspect ratio management for multi-format rendering."""
    @staticmethod
    def standard_aspects() -> list[str]:
        return ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "4:5"]

    @staticmethod
    def resolution_for(aspect: str) -> tuple[int, int]:
        aspect_map = {
            "16:9": (1920, 1080),
            "9:16": (1080, 1920),
            "1:1": (1080, 1080),
            "4:3": (1440, 1080),
            "3:4": (1080, 1440),
            "21:9": (2560, 1080),
            "4:5": (1080, 1350),
        }
        return aspect_map.get(aspect, (1920, 1080))

    @staticmethod
    def crop_region(source_width: int, source_height: int, target_ratio: str) -> tuple[int, int, int, int]:
        tw, th = AspectRatioHandler.resolution_for(target_ratio)
        source_ratio = source_width / source_height
        target_ratio_val = tw / th
        if source_ratio > target_ratio_val:
            new_width = int(source_height * target_ratio_val)
            new_height = source_height
            x = (source_width - new_width) // 2
            y = 0
        else:
            new_height = int(source_width / target_ratio_val)
            new_width = source_width
            x = 0
            y = (source_height - new_height) // 2
        return (x, y, new_width, new_height)

    @staticmethod
    def letterbox(source_width: int, source_height: int, target_ratio: str) -> dict[str, int]:
        tw, th = AspectRatioHandler.resolution_for(target_ratio)
        source_ratio = source_width / source_height
        target_ratio_val = tw / th
        if source_ratio > target_ratio_val:
            width = target_ratio_val * source_height
            height = source_height
        else:
            width = source_width
            height = source_width / target_ratio_val
        return {
            "width": int(width),
            "height": int(height),
            "padding_top": int((th - height) / 2),
            "padding_left": int((tw - width) / 2),
        }

    @staticmethod
    def convert_scene(scene: HTMLScene, target_ratio: str) -> HTMLScene:
        tw, th = AspectRatioHandler.resolution_for(target_ratio)
        scene.width = tw
        scene.height = th
        scene.html_content = scene.html_content.replace(
            f"width:{scene.width}", f"width:{tw}"
        )
        return scene


@dataclass
class HyperframesManager:
    """Unified hyperframes video rendering manager."""
    scripts: dict[str, VideoScript] = field(default_factory=dict)
    pipeline: RenderPipeline = field(default_factory=RenderPipeline)

    def create_script(self, title: str, text: str) -> VideoScript:
        script = VideoScript.from_text(text, title)
        self.scripts[title] = script
        return script

    def add_html_scene(self, script_title: str, html_content: str, title: str = "", duration: float = 5.0) -> HTMLScene:
        scene = HTMLScene.create_scene(html_content, title=title, duration=duration)
        if script_title in self.scripts:
            self.scripts[script_title].add_scene(scene)
        return scene

    def render_script(self, script_title: str) -> dict[str, Any]:
        script = self.scripts.get(script_title)
        if not script:
            return {"error": "Script not found", "title": script_title}
        total_frames = script.total_frames()
        duration = script.total_duration()
        estimate = RenderPipeline.estimate_render_time(script)
        return {
            "title": script_title,
            "scenes": script.scene_count(),
            "total_duration": duration,
            "total_frames": total_frames,
            "estimated_render_time": estimate,
            "aspect": script.scenes[0].aspect_ratio if script.scenes else "16:9",
        }

    def optimize_scenes(self, script_title: str) -> dict[str, Any]:
        script = self.scripts.get(script_title)
        if not script:
            return {"error": "Script not found"}
        pacing = RenderPipeline.scene_pacing(script)
        for scene in script.scenes:
            if not scene.has_animation:
                scene.html_content += "<style>.scene{animation: fadeIn 1s;}</style>"
        return pacing

    def export_manifest(self, script_title: str) -> dict[str, Any]:
        script = self.scripts.get(script_title)
        if not script:
            return {"error": "Script not found"}
        return {
            "title": script_title,
            "scenes": script.to_scene_list(),
            "total_duration": script.total_duration(),
            "scene_count": script.scene_count(),
        }

    @property
    def script_count(self) -> int:
        return len(self.scripts)

    @property
    def total_scenes(self) -> int:
        return sum(s.scene_count() for s in self.scripts.values())

    def supported_formats(self) -> list[str]:
        return ["mp4", "webm", "mov", "gif", "avif"]

    def supported_aspects(self) -> list[str]:
        return AspectRatioHandler.standard_aspects()
