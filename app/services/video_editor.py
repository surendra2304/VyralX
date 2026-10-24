"""
VyralX/app/services/video_editor.py — VyralX Automated Video Editor.

Extends VyralX's capabilities with:
1. Automated Editing: cut, trim, and rearrange video segments
2. Scene Detection: automatically detect scene changes
3. Beat Synchronization: sync cuts to music beats
4. Transition Generation: create smooth transitions between clips
5. Color Grading: auto-grade video colors
6. Subtitle Generation: auto-generate and sync subtitles
7. Thumbnail Generation: auto-generate thumbnails from frames
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SceneChange:
    """A detected scene change."""
    timestamp: float
    confidence: float
    type: str  # hard_cut, fade, dissolve
    previous_scene: str = ""
    new_scene: str = ""


@dataclass
class BeatPoint:
    """A detected music beat."""
    timestamp: float
    intensity: float
    is_downbeat: bool = False


@dataclass
class EditDecision:
    """An automated editing decision."""
    timestamp: float
    action: str  # cut, keep, transition
    reason: str
    confidence: float


@dataclass
class VideoEditPlan:
    """A complete video edit plan."""
    title: str
    total_duration: float
    scenes: list[SceneChange]
    beats: list[BeatPoint]
    cuts: list[EditDecision]
    estimated_export_time: float
    complexity: float


class VideoEditor:
    """Automated video editing engine."""

    def __init__(self):
        self._scene_changes: list[SceneChange] = []
        self._beat_points: list[BeatPoint] = []
        self._edit_plans: dict[str, VideoEditPlan] = {}

    # ── Scene Detection ───────────────────────────────────────────────────

    def detect_scenes(
        self,
        frames: list[dict],
        threshold: float = 0.3,
    ) -> list[SceneChange]:
        """Detect scene changes in video frames."""
        scenes = []

        for i in range(1, len(frames)):
            prev = frames[i-1]
            curr = frames[i]

            # Calculate histogram difference
            diff = self._frame_difference(prev, curr)

            if diff > threshold:
                scene = SceneChange(
                    timestamp=curr.get("timestamp", i * 0.033),
                    confidence=min(1.0, diff),
                    type="hard_cut" if diff > 0.6 else "fade",
                    previous_scene=prev.get("scene_id", ""),
                    new_scene=curr.get("scene_id", ""),
                )
                scenes.append(scene)

        self._scene_changes = scenes
        return scenes

    def _frame_difference(self, f1: dict, f2: dict) -> float:
        """Calculate difference between two frames."""
        h1 = f1.get("histogram", [0.0] * 256)
        h2 = f2.get("histogram", [0.0] * 256)

        if len(h1) != len(h2):
            return 0.0

        # Histogram intersection
        intersection = sum(min(a, b) for a, b in zip(h1, h2))
        union = sum(max(a, b) for a, b in zip(h1, h2))

        if union == 0:
            return 0.0

        return 1.0 - (intersection / union)

    # ── Beat Detection ─────────────────────────────────────────────────────

    def detect_beats(
        self,
        audio_features: list[dict],
        bpm: float | None = None,
    ) -> list[BeatPoint]:
        """Detect music beats from audio features."""
        beats = []

        onsets = audio_features
        if not onsets:
            return beats

        # Calculate inter-onset intervals
        intensities = [o.get("intensity", 0.0) for o in onsets]
        timestamps = [o.get("timestamp", i * 0.023) for i, o in enumerate(onsets)]

        # Simple beat detection: find peaks
        for i in range(1, len(intensities) - 1):
            if intensities[i] > intensities[i-1] and intensities[i] > intensities[i+1]:
                if intensities[i] > 0.3:  # Threshold
                    beat = BeatPoint(
                        timestamp=timestamps[i],
                        intensity=intensities[i],
                        is_downbeat=intensities[i] > 0.7,
                    )
                    beats.append(beat)

        # If BPM known, refine beat positions
        if bpm and len(beats) > 2:
            self._refine_beats(beats, bpm)

        self._beat_points = beats
        return beats

    def _refine_beats(self, beats: list[BeatPoint], bpm: float) -> None:
        """Refine beat positions using known BPM."""
        interval = 60.0 / bpm

        # Sort by timestamp
        beats.sort(key=lambda b: b.timestamp)

        # Adjust beats to grid
        for i, beat in enumerate(beats):
            expected = i * interval
            if beat.timestamp - expected > interval * 0.25:
                # Move beat to grid
                beat.timestamp = expected

    # ── Edit Planning ─────────────────────────────────────────────────────

    def create_edit_plan(
        self,
        title: str,
        total_duration: float,
        raw_clips: list[dict],
        music_beats: list[BeatPoint] | None = None,
        pacing: str = "dynamic",  # slow, medium, dynamic, fast
    ) -> VideoEditPlan:
        """Create an automated edit plan."""
        scenes = self._scene_changes
        beats = music_beats or self._beat_points

        # Determine cut decisions
        cuts = []

        # Pacing settings
        pacing_config = {
            "slow": {"min_clip": 5.0, "transition_prob": 0.3},
            "medium": {"min_clip": 3.0, "transition_prob": 0.5},
            "dynamic": {"min_clip": 2.0, "transition_prob": 0.4},
            "fast": {"min_clip": 1.0, "transition_prob": 0.2},
        }

        config = pacing_config.get(pacing, pacing_config["medium"])

        # Generate cut decisions
        for i, clip in enumerate(raw_clips):
            duration = clip.get("duration", 5.0)

            if duration < config["min_clip"]:
                # Cut short
                cuts.append(EditDecision(
                    timestamp=clip.get("start", 0.0),
                    action="cut",
                    reason=f"Clip too long at {pacing} pacing",
                    confidence=0.7,
                ))
            elif duration > 10.0:
                # Cut long clips
                cuts.append(EditDecision(
                    timestamp=clip.get("start", 0.0) + duration / 2,
                    action="cut",
                    reason="Breaking up long clip for engagement",
                    confidence=0.6,
                ))

            # Add transition at scene changes
            if scenes and any(
                abs(s.timestamp - clip.get("start", 0.0)) < 0.5
                for s in scenes
            ):
                if random.random() < config["transition_prob"]:
                    cuts.append(EditDecision(
                        timestamp=clip.get("start", 0.0),
                        action="transition",
                        reason="Scene change detected",
                        confidence=0.8,
                    ))

        # Sync cuts to beats if available
        if beats:
            for beat in beats:
                if beat.is_downbeat:
                    cuts.append(EditDecision(
                        timestamp=beat.timestamp,
                        action="cut",
                        reason="Downbeat synchronization",
                        confidence=0.9,
                    ))

        # Sort cuts by timestamp
        cuts.sort(key=lambda c: c.timestamp)

        # Calculate complexity
        complexity = len(cuts) / total_duration * 60  # cuts per minute

        # Estimate export time
        export_time = total_duration * 0.5  # 0.5x playback speed

        plan = VideoEditPlan(
            title=title,
            total_duration=total_duration,
            scenes=scenes,
            beats=beats,
            cuts=cuts,
            estimated_export_time=export_time,
            complexity=complexity,
        )

        self._edit_plans[title] = plan
        return plan

    # ── Color Grading ──────────────────────────────────────────────────────

    def auto_color_grade(
        self,
        frame_analysis: dict,
        mood: str = "neutral",  # warm, cool, neutral, cinematic, vibrant
    ) -> dict[str, float]:
        """Generate color grading parameters."""
        grading = {
            "exposure": 1.0,
            "contrast": 1.0,
            "saturation": 1.0,
            "temperature": 0.0,
            "tint": 0.0,
            "highlights": 1.0,
            "shadows": 1.0,
            "white_balance": 0.0,
        }

        if mood == "warm":
            grading["temperature"] = 0.15
            grading["saturation"] = 1.1
            grading["exposure"] = 1.05

        elif mood == "cool":
            grading["temperature"] = -0.15
            grading["saturation"] = 0.95
            grading["contrast"] = 1.05

        elif mood == "cinematic":
            grading["contrast"] = 1.15
            grading["saturation"] = 0.9
            grading["temperature"] = -0.05
            grading["highlights"] = 0.95
            grading["shadows"] = 1.1

        elif mood == "vibrant":
            grading["saturation"] = 1.3
            grading["contrast"] = 1.1
            grading["exposure"] = 1.05

        return grading

    # ── Subtitle Generation ────────────────────────────────────────────────

    def generate_subtitles(
        self,
        transcript: list[dict],
        video_duration: float,
        sync_tolerance: float = 0.3,
    ) -> list[dict]:
        """Generate synced subtitles from a transcript."""
        subtitles = []

        for segment in transcript:
            text = segment.get("text", "")
            timestamp = segment.get("timestamp", 0.0)
            duration = segment.get("duration", 2.0)

            # Clean and format
            text = text.strip()
            if len(text) > 100:
                # Split long segments
                words = text.split()
                mid = len(words) // 2
                sub1 = " ".join(words[:mid])
                sub2 = " ".join(words[mid:])

                subtitles.append({
                    "start": timestamp,
                    "end": timestamp + duration / 2,
                    "text": sub1,
                })
                subtitles.append({
                    "start": timestamp + duration / 2,
                    "end": timestamp + duration,
                    "text": sub2,
                })
            else:
                subtitles.append({
                    "start": timestamp,
                    "end": timestamp + duration,
                    "text": text,
                })

        return subtitles

    # ── Thumbnail Generation ───────────────────────────────────────────────

    def select_thumbnail(
        self,
        frames: list[dict],
        video_title: str,
    ) -> dict[str, Any]:
        """Select the best thumbnail from video frames."""
        if not frames:
            return {"frame": None, "score": 0.0}

        best_frame = None
        best_score = 0.0

        for frame in frames:
            score = 0.0

            # Brightness score (not too dark, not too bright)
            brightness = frame.get("brightness", 0.5)
            if 0.3 < brightness < 0.7:
                score += 0.3

            # Contrast score
            contrast = frame.get("contrast", 0.5)
            if contrast > 0.4:
                score += 0.2

            # Face detection
            if frame.get("has_face"):
                score += 0.3

            # Text/emoji presence
            if frame.get("has_text") or frame.get("has_emoji"):
                score += 0.2

            # Action/motion
            if frame.get("motion_score", 0) > 0.5:
                score += 0.1

            if score > best_score:
                best_score = score
                best_frame = frame

        return {
            "frame_id": best_frame.get("frame_id", ""),
            "score": best_score,
            "reason": "Best visual appeal score" if best_score > 0.5 else "No ideal frame found",
        }

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_edit_report(self) -> dict[str, Any]:
        """Generate an editing report."""
        return {
            "total_scenes_detected": len(self._scene_changes),
            "total_beats_detected": len(self._beat_points),
            "total_edit_plans": len(self._edit_plans),
            "avg_complexity": (
                sum(p.complexity for p in self._edit_plans.values()) / len(self._edit_plans)
                if self._edit_plans else 0.0
            ),
        }
