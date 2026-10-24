"""
VyralX/app/services/live_stream_optimizer.py — VyralX Live Stream Optimizer.

Extends VyralX's capabilities with:
1. Live Chat Analysis: analyze chat sentiment and engagement
2. Viewer Retention: predict and optimize viewer retention during streams
3. Stream Schedule Optimization: find best times to stream
4. Moment Detection: detect peak engagement moments
5. Stream Health Monitoring: monitor stream quality in real-time
6. Automated Clip Generation: auto-generate clips from best moments
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChatMessage:
    """A chat message during a stream."""
    user: str
    text: str
    timestamp: float
    sentiment: float = 0.0
    engagement: float = 0.0
    is_mod: bool = False
    is_sub: bool = False


@dataclass
class StreamAnalytics:
    """Analytics from a live stream."""
    stream_id: str
    peak_viewers: int
    avg_viewers: int
    chat_messages: int
    chat_rate: float  # messages per minute
    retention_rate: float
    engagement_score: float
    peak_moments: list[float]  # timestamps of peak engagement
    sentiment_trend: list[float]


@dataclass
class StreamSchedule:
    """Optimized stream schedule."""
    stream_id: str
    best_times: list[dict]  # day, time, predicted_viewers
    recommended_duration: float  # hours
    recommended_frequency: float  # streams per week
    competitor_analysis: str
    predicted_growth: float


@dataclass
class ClipSuggestion:
    """Suggested clip from a stream."""
    clip_id: str
    start_time: float
    end_time: float
    reason: str
    predicted_views: int
    engagement_score: float
    title_suggestion: str


class LiveStreamOptimizer:
    """Live stream optimization engine."""

    def __init__(self):
        self._stream_analytics: dict[str, StreamAnalytics] = {}
        self._clip_suggestions: dict[str, list[ClipSuggestion]] = {}
        self._chat_history: dict[str, list[ChatMessage]] = {}

    # ── Chat Analysis ──────────────────────────────────────────────────────

    def analyze_chat(
        self,
        stream_id: str,
        messages: list[dict],
    ) -> dict[str, Any]:
        """Analyze live chat during a stream."""
        parsed = []
        sentiment_scores = []
        engagement_scores = []

        for msg in messages:
            chat = ChatMessage(
                user=msg.get("user", ""),
                text=msg.get("text", ""),
                timestamp=msg.get("timestamp", 0.0),
                is_mod=msg.get("is_mod", False),
                is_sub=msg.get("is_sub", False),
            )

            # Sentiment
            positive = ["love", "great", "amazing", "hype", "lol", "haha", "nice"]
            negative = ["bad", "hate", "boring", "trash", "worst"]

            text_lower = chat.text.lower()
            pos = sum(1 for w in positive if w in text_lower)
            neg = sum(1 for w in negative if w in text_lower)
            chat.sentiment = (pos - neg) / max(1, pos + neg)

            # Engagement
            chat.engagement = 1.0
            if chat.is_mod:
                chat.engagement *= 1.5
            if chat.is_sub:
                chat.engagement *= 1.3
            if "!" in chat.text:
                chat.engagement *= 1.2
            if len(chat.text) > 50:
                chat.engagement *= 1.1

            chat.engagement = min(3.0, chat.engagement)

            parsed.append(chat)
            sentiment_scores.append(chat.sentiment)
            engagement_scores.append(chat.engagement)

        # Store history
        if stream_id not in self._chat_history:
            self._chat_history[stream_id] = []
        self._chat_history[stream_id].extend(parsed)

        return {
            "stream_id": stream_id,
            "total_messages": len(parsed),
            "avg_sentiment": sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0,
            "avg_engagement": sum(engagement_scores) / len(engagement_scores) if engagement_scores else 0,
            "top_chatters": self._get_top_chatters(parsed),
            "sentiment_over_time": self._sentiment_over_time(parsed),
        }

    def _get_top_chatters(self, messages: list[ChatMessage]) -> list[dict]:
        """Get top chatters."""
        counts: dict[str, int] = {}
        for msg in messages:
            counts[msg.user] = counts.get(msg.user, 0) + 1

        return [
            {"user": user, "messages": count}
            for user, count in sorted(counts.items(), key=lambda x: -x[1])[:10]
        ]

    def _sentiment_over_time(self, messages: list[ChatMessage]) -> list[float]:
        """Get sentiment over time."""
        if not messages:
            return []

        # Bucket by minute
        buckets: dict[int, list[float]] = {}
        for msg in messages:
            minute = int(msg.timestamp / 60)
            buckets.setdefault(minute, []).append(msg.sentiment)

        return [
            sum(scores) / len(scores)
            for minute in sorted(buckets)
            for scores in [buckets[minute]]
        ]

    # ── Viewer Retention ───────────────────────────────────────────────────

    def predict_retention(
        self,
        stream_id: str,
        viewer_counts: list[int],
    ) -> dict[str, Any]:
        """Predict viewer retention during a stream."""
        if not viewer_counts:
            return {"retention_rate": 0.0, "predicted_drop_off": []}

        peak = max(viewer_counts)
        avg = sum(viewer_counts) / len(viewer_counts)
        retention = avg / peak if peak > 0 else 0.0

        # Find drop-off points
        drop_offs = []
        for i in range(1, len(viewer_counts)):
            if viewer_counts[i] < viewer_counts[i-1]:
                drop_pct = (viewer_counts[i-1] - viewer_counts[i]) / viewer_counts[i-1]
                if drop_pct > 0.1:  # 10% drop
                    drop_offs.append({
                        "timestamp": i * 60,  # Convert to minutes
                        "drop_pct": drop_pct,
                        "viewers_lost": viewer_counts[i-1] - viewer_counts[i],
                    })

        return {
            "stream_id": stream_id,
            "peak_viewers": peak,
            "avg_viewers": int(avg),
            "retention_rate": retention,
            "drop_off_points": drop_offs,
            "recommendation": (
                "Retention is good" if retention > 0.7 else
                "Retention needs improvement" if retention > 0.4 else
                "Retention is poor - consider shorter streams"
            ),
        }

    # ── Stream Schedule Optimization ────────────────────────────────────────

    def optimize_schedule(
        self,
        channel_subscribers: int,
        niche: str,
        timezone: str = "UTC",
        competitor_streams: list[dict] | None = None,
    ) -> StreamSchedule:
        """Optimize streaming schedule."""
        # Analyze best times
        best_times = []

        # Days of week
        days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

        for day in days:
            # Peak times based on niche
            if niche.lower() in ("gaming", "entertainment"):
                best_hours = [18, 19, 20, 21]  # Evening
            elif niche.lower() in ("education", "tech"):
                best_hours = [19, 20, 21, 22]
            else:
                best_hours = [17, 18, 19, 20]

            for hour in best_hours:
                # Estimate viewers
                base = channel_subscribers * 0.05
                day_factor = 1.3 if day in ("Friday", "Saturday", "Sunday") else 0.8
                hour_factor = 1.0 if hour in (19, 20) else 0.8

                estimated = int(base * day_factor * hour_factor)

                best_times.append({
                    "day": day,
                    "hour": hour,
                    "predicted_viewers": estimated,
                    "score": estimated,
                })

        # Sort by predicted viewers
        best_times.sort(key=lambda t: -t["predicted_viewers"])

        # Recommended duration
        if niche.lower() in ("gaming",):
            rec_duration = 3.0  # 3 hours
            rec_frequency = 4.0  # 4 streams per week
        elif niche.lower() in ("education", "tech"):
            rec_duration = 1.5
            rec_frequency = 3.0
        else:
            rec_duration = 2.0
            rec_frequency = 3.5

        # Competitor analysis
        competitor_text = ""
        if competitor_streams:
            competitor_text = (
                f"Analyzed {len(competitor_streams)} competitor streams. "
                f"Common times: {set(c.get('day', '') for c in competitor_streams)}. "
            )
            if competitor_streams:
                avg_duration = sum(c.get("duration", 2) for c in competitor_streams) / len(competitor_streams)
                competitor_text += f"Average duration: {avg_duration:.1f} hours."

        schedule = StreamSchedule(
            stream_id=f"schedule_{int(time.time())}",
            best_times=best_times[:10],
            recommended_duration=rec_duration,
            recommended_frequency=rec_frequency,
            competitor_analysis=competitor_text,
            predicted_growth=0.15 if rec_frequency >= 4 else 0.08,
        )

        return schedule

    # ── Moment Detection ───────────────────────────────────────────────────

    def detect_moments(
        self,
        stream_id: str,
        chat_messages: list[dict],
        viewer_counts: list[int],
    ) -> list[dict]:
        """Detect peak engagement moments."""
        if not chat_messages or not viewer_counts:
            return []

        moments = []

        # Bucket by minute
        minute_buckets: dict[int, dict] = {}

        for msg in chat_messages:
            minute = int(msg.get("timestamp", 0) / 60)
            if minute not in minute_buckets:
                minute_buckets[minute] = {"chat": 0, "sentiment": [], "viewers": 0}
            minute_buckets[minute]["chat"] += 1
            minute_buckets[minute]["sentiment"].append(
                1 if any(w in msg.get("text", "").lower() for w in ["!", "wow", "hype", "lol"]) else 0
            )

        for i, viewers in enumerate(viewer_counts):
            minute = i
            if minute not in minute_buckets:
                minute_buckets[minute] = {"chat": 0, "sentiment": [], "viewers": 0}
            minute_buckets[minute]["viewers"] = viewers

        # Find peaks
        for minute, data in sorted(minute_buckets.items()):
            chat_score = min(1.0, data["chat"] / 50)
            sentiment_score = sum(data["sentiment"]) / max(1, len(data["sentiment"]))
            viewer_score = data["viewers"] / max(1, max(v for v in viewer_counts) if viewer_counts else 1)

            overall = chat_score * 0.4 + sentiment_score * 0.3 + viewer_score * 0.3

            if overall > 0.6:
                moments.append({
                    "timestamp": minute * 60,
                    "score": overall,
                    "chat_count": data["chat"],
                    "viewers": data["viewers"],
                    "reason": "High engagement moment",
                })

        moments.sort(key=lambda m: -m["score"])
        return moments[:10]

    # ── Automated Clip Generation ──────────────────────────────────────────

    def suggest_clips(
        self,
        stream_id: str,
        moments: list[dict],
        channel_subscribers: int,
    ) -> list[ClipSuggestion]:
        """Suggest clips from best moments."""
        clips = []

        for moment in moments[:5]:
            clip = ClipSuggestion(
                clip_id=f"clip_{int(moment['timestamp'])}_{stream_id}",
                start_time=moment["timestamp"],
                end_time=moment["timestamp"] + 60,  # 60 second clip
                reason=moment["reason"],
                predicted_views=int(channel_subscribers * 0.02 * moment["score"]),
                engagement_score=moment["score"],
                title_suggestion=f"Best Moment at {moment['timestamp']//60}:{moment['timestamp']%60:02d}",
            )
            clips.append(clip)

        if stream_id not in self._clip_suggestions:
            self._clip_suggestions[stream_id] = []
        self._clip_suggestions[stream_id] = clips

        return clips

    # ── Stream Health Monitoring ───────────────────────────────────────────

    def monitor_health(
        self,
        stream_id: str,
        metrics: dict[str, Any],
    ) -> dict[str, Any]:
        """Monitor stream health in real-time."""
        health = {
            "stream_id": stream_id,
            "status": "healthy",
            "warnings": [],
            "critical": [],
        }

        # Check various metrics
        fps = metrics.get("fps", 60)
        if fps < 24:
            health["critical"].append(f"Low FPS: {fps}")
            health["status"] = "critical"
        elif fps < 30:
            health["warnings"].append(f"Low FPS: {fps}")

        bitrate = metrics.get("bitrate", 6000)
        if bitrate < 2500:
            health["warnings"].append(f"Low bitrate: {bitrate} kbps")

        audio_level = metrics.get("audio_level", 0.5)
        if audio_level < 0.1:
            health["critical"].append("Audio too low")
            health["status"] = "critical"
        elif audio_level > 0.95:
            health["warnings"].append("Audio may be clipping")

        dropped_frames = metrics.get("dropped_frames", 0)
        if dropped_frames > 100:
            health["warnings"].append(f"Dropped frames: {dropped_frames}")

        # Calculate overall health score
        health_score = 1.0
        health_score -= len(health["critical"]) * 0.5
        health_score -= len(health["warnings"]) * 0.1
        health_score = max(0.0, health_score)

        health["health_score"] = health_score

        return health

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_optimizer_report(self) -> dict[str, Any]:
        """Generate a live stream optimizer report."""
        return {
            "total_streams_analyzed": len(self._stream_analytics),
            "total_clip_suggestions": sum(
                len(clips) for clips in self._clip_suggestions.values()
            ),
            "chat_messages_analyzed": sum(
                len(msgs) for msgs in self._chat_history.values()
            ),
        }
