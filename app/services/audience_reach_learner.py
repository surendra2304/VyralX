"""VyralX Audience & Reach Reinforcement Learning Engine.

Continuously tracks YouTube performance metrics (views, likes, comments, retention velocity),
analyzes audience cohorts, dynamically adjusts topic sampling weights based on reach,
and calculates optimal posting times and publication schedules for drafted Shorts.
"""
from __future__ import annotations

import json
import logging
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("vyralx.audience_learner")

STATE_FILE = Path("data/audience_learning_state.json")

# Core Audience Cohorts with peak global distribution windows
AUDIENCE_COHORTS = {
    "finance_and_wealth": {
        "name": "High-Intent Finance & Wealth Enthusiasts",
        "topics": [
            "extreme wealth and cash",
            "stock market crash and trading",
            "day trading profit surge",
            "billionaire cash counting",
            "billion dollar algorithm",
            "financial market crash"
        ],
        "optimal_utc_hour": 14,  # 14:30 UTC -> 10:30 AM EST (US Market open) / 8:00 PM IST
        "optimal_utc_minute": 30,
        "rationale": "Aligns with US market open momentum and evening financial recap in Asia/Europe."
    },
    "psychology_and_tension": {
        "name": "Curiosity & High-Tension Observers",
        "topics": [
            "psychology and tension",
            "police interrogation drama",
            "true crime investigation"
        ],
        "optimal_utc_hour": 18,  # 18:30 UTC -> 2:30 PM EST / 12:00 AM IST
        "optimal_utc_minute": 30,
        "rationale": "Peak evening mobile engagement window when viewers seek high-dopamine narrative tension."
    },
    "satisfying_precision": {
        "name": "Industrial & Precision Craft Lovers",
        "topics": [
            "satisfying molten metal",
            "satisfying precision cnc",
            "hypnotic science reaction",
            "hydraulic press destruction",
            "satisfying glass crafting",
            "satisfying woodturning craft",
            "precision domino physics",
            "kinetic sand slicing",
            "hypercar extreme drift"
        ],
        "optimal_utc_hour": 19,  # 19:00 UTC -> 3:00 PM EST / 12:30 AM IST
        "optimal_utc_minute": 0,
        "rationale": "Late-afternoon / evening global relaxation window with maximum viral algorithmic reach."
    },
    "cyber_and_tech": {
        "name": "Tech Innovators & Cyber Enthusiasts",
        "topics": [
            "high tech server room",
            "elite coding cyber heist",
            "cyber security breakthrough"
        ],
        "optimal_utc_hour": 15,  # 15:00 UTC -> 11:00 AM EST / 8:30 PM IST
        "optimal_utc_minute": 0,
        "rationale": "High developer/tech worker overlap during mid-day coffee breaks and post-work browsing."
    }
}


def find_cohort_for_topic(topic: str) -> tuple[str, dict[str, Any]]:
    """Identifies the audience cohort for a given content topic."""
    topic_lower = topic.lower()
    for cohort_id, cohort_info in AUDIENCE_COHORTS.items():
        for t in cohort_info["topics"]:
            if t.lower() in topic_lower or topic_lower in t.lower():
                return cohort_id, cohort_info
    # Default to satisfying precision
    return "satisfying_precision", AUDIENCE_COHORTS["satisfying_precision"]


def calculate_optimal_post_time(topic: str) -> dict[str, Any]:
    """Calculates the exact upcoming optimal posting timestamp (UTC, IST, EST) based on audience reach telemetry."""
    cohort_id, cohort = find_cohort_for_topic(topic)
    target_hour = cohort["optimal_utc_hour"]
    target_minute = cohort["optimal_utc_minute"]

    now = datetime.now(timezone.utc)
    # Determine the next occurrence of the optimal window
    candidate = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)

    # Calculate IST (UTC + 5:30) and EST (UTC - 4 or -5, standard EST is UTC - 5)
    ist_offset = timedelta(hours=5, minutes=30)
    ist_time = candidate + ist_offset
    est_offset = timedelta(hours=-4)  # EDT or -5 EST
    est_time = candidate + est_offset

    return {
        "cohort_id": cohort_id,
        "target_audience_cohort": cohort["name"],
        "optimal_post_time_utc": candidate.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "optimal_post_time_ist": ist_time.strftime("%A, %b %d at %I:%M %p IST"),
        "optimal_post_time_est": est_time.strftime("%A, %b %d at %I:%M %p EST/EDT"),
        "posting_rationale": cohort["rationale"]
    }


def fetch_live_youtube_telemetry(video_ids: list[str]) -> list[dict[str, Any]]:
    """Fetches real-time view, like, and comment telemetry from YouTube Data API / OAuth."""
    clean_ids = list(dict.fromkeys(v.strip() for v in video_ids if v and len(v.strip()) >= 6))
    if not clean_ids:
        return []

    telemetry = []
    # 1. Try authenticated OAuth service first (has access to private/draft and public videos)
    try:
        from app.services.youtube import youtube_service
        yt = youtube_service()
        for i in range(0, len(clean_ids), 50):
            batch = clean_ids[i:i + 50]
            req = yt.videos().list(part="snippet,statistics,status", id=",".join(batch))
            resp = req.execute()
            for item in resp.get("items", []):
                stats = item.get("statistics", {})
                status = item.get("status", {})
                snippet = item.get("snippet", {})
                views = int(stats.get("viewCount", 0))
                likes = int(stats.get("likeCount", 0))
                comments = int(stats.get("commentCount", 0))
                privacy = status.get("privacyStatus", "unknown")
                rate = ((likes + comments) / max(1, views)) * 100.0 if views > 0 else 0.0

                telemetry.append({
                    "yt_id": item.get("id"),
                    "title": snippet.get("title", ""),
                    "views": views,
                    "likes": likes,
                    "comments": comments,
                    "privacy": privacy,
                    "engagement_rate": round(rate, 2),
                    "published_at": snippet.get("publishedAt", "")
                })
        if telemetry:
            return telemetry
    except Exception as exc:
        log.warning("OAuth telemetry query failed, falling back to public API key: %s", exc)

    # 2. Fallback to public Data API
    try:
        from app.services.youtube_analytics import fetch_video_metrics
        records = fetch_video_metrics(clean_ids)
        for r in records:
            telemetry.append({
                "yt_id": r.get("youtube_video_id"),
                "title": r.get("title", ""),
                "views": r.get("view_count", 0),
                "likes": r.get("like_count", 0),
                "comments": r.get("comment_count", 0),
                "privacy": "public",
                "engagement_rate": r.get("engagement_rate", 0.0),
                "published_at": ""
            })
    except Exception as exc2:
        log.warning("Public metrics query failed: %s", exc2)

    return telemetry


class AudienceReachLearner:
    """Manages reinforcement learning across content topics and audience segments."""

    def __init__(self, state_file: Path | None = None):
        self.state_file = state_file or STATE_FILE
        self.state: dict[str, Any] = self._load_state()

    def _load_state(self) -> dict[str, Any]:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("Could not read learning state file: %s", e)
        return {
            "total_cycles": 0,
            "total_drafts_created": 0,
            "topic_performance": {},
            "cohort_performance": {},
            "history": []
        }

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.state, indent=2), encoding="utf-8")

    def refresh_and_learn(self, manifest_items: list[dict[str, Any]]) -> dict[str, Any]:
        """Refreshes YouTube metrics and updates topic sampling weights based on audience reach."""
        self.state["total_cycles"] += 1

        yt_ids = []
        video_to_manifest = {}
        for item in manifest_items:
            yid = item.get("yt_id") or item.get("youtube_id")
            if yid:
                yt_ids.append(yid)
                video_to_manifest[yid] = item

        telemetry = fetch_live_youtube_telemetry(yt_ids)
        log.info("Audience telemetry refreshed: %d videos evaluated from YouTube.", len(telemetry))

        topic_stats: dict[str, dict[str, Any]] = self.state.setdefault("topic_performance", {})

        for t in telemetry:
            yid = t["yt_id"]
            man_item = video_to_manifest.get(yid, {})
            # Infer topic from manifest or title
            topic = man_item.get("topic")
            if not topic:
                for cohort_info in AUDIENCE_COHORTS.values():
                    for cand_topic in cohort_info["topics"]:
                        if cand_topic.lower() in man_item.get("title", "").lower():
                            topic = cand_topic
                            break
                    if topic:
                        break
            if not topic:
                topic = "general viral visual"

            stats = topic_stats.setdefault(topic, {
                "impressions_views": 0,
                "likes": 0,
                "comments": 0,
                "drafts_count": 0,
                "avg_engagement_rate": 0.0,
                "learned_weight": 1.0,
                "last_seen_yt_id": yid
            })

            views = t.get("views", 0)
            likes = t.get("likes", 0)
            comments = t.get("comments", 0)
            eng_rate = t.get("engagement_rate", 0.0)

            stats["impressions_views"] = max(stats["impressions_views"], views)
            stats["likes"] = max(stats["likes"], likes)
            stats["comments"] = max(stats["comments"], comments)
            stats["drafts_count"] = max(stats["drafts_count"], 1)
            stats["avg_engagement_rate"] = round((stats["avg_engagement_rate"] + eng_rate) / 2.0, 2)

            # Reinforcement formula:
            # Base weight 1.0, increased if engagement > 3.0% or views > 1000
            # weight clamped between 0.5 (low performing) and 3.5 (viral breakout)
            weight = 1.0 + (stats["avg_engagement_rate"] / 4.0) * 0.4
            if stats["impressions_views"] > 1000:
                weight += math.log10(stats["impressions_views"]) * 0.25
            stats["learned_weight"] = round(max(0.5, min(3.5, weight)), 3)

        self._save_state()
        return self.get_summary()

    def select_weighted_candidate(
        self,
        catalog: list[dict[str, Any]],
        processed_stems: set[str]
    ) -> tuple[dict[str, Any] | None, float]:
        """Selects the next viral candidate using learned reach weights with softmax exploration."""
        eligible = [c for c in catalog if f"mixkit_{c['id']}" not in processed_stems]
        if not eligible:
            return None, 1.0

        topic_stats = self.state.get("topic_performance", {})

        # Compute sampling weights
        weights = []
        for c in eligible:
            topic = c.get("topic", "")
            stat = topic_stats.get(topic, {})
            # Thompson sampling / exploration bonus: unattempted topics get 1.25 bonus weight
            w = stat.get("learned_weight", 1.25)
            weights.append(w)

        # 10% epsilon random exploration to discover new viral trends
        if random.random() < 0.10:
            chosen = random.choice(eligible)
            log.info("Audience Learner: Selected candidate via epsilon exploration: '%s'", chosen["title"])
            return chosen, 1.0

        chosen = random.choices(eligible, weights=weights, k=1)[0]
        chosen_weight = weights[eligible.index(chosen)]
        log.info(
            "Audience Learner: Selected candidate via reach reinforcement: '%s' (topic: '%s', weight: %.2f)",
            chosen["title"], chosen.get("topic"), chosen_weight
        )
        return chosen, chosen_weight

    def record_draft_created(self, video_id: str, topic: str, target_time: dict[str, Any]) -> None:
        """Records a newly drafted video into learning history."""
        self.state["total_drafts_created"] = self.state.get("total_drafts_created", 0) + 1
        history = self.state.setdefault("history", [])
        history.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "video_id": video_id,
            "topic": topic,
            "target_schedule": target_time
        })
        # Keep last 50 history entries
        self.state["history"] = history[-50:]
        self._save_state()

    def get_summary(self) -> dict[str, Any]:
        """Returns high-level summary of the audience learning state."""
        return {
            "total_cycles": self.state.get("total_cycles", 0),
            "total_drafts_created": self.state.get("total_drafts_created", 0),
            "active_topic_weights": {
                k: v.get("learned_weight", 1.0) for k, v in self.state.get("topic_performance", {}).items()
            }
        }
