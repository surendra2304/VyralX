"""
VyralX/app/services/community_manager.py — VyralX Community Manager.

Extends VyralX's capabilities with:
1. Community Engagement: track and boost community engagement
2. Comment Analysis: analyze comments for sentiment and insights
3. Moderation Tools: automated comment moderation
4. Community Growth: strategies for growing communities
5. Leaderboard Management: manage community leaderboards
6. Event Planning: plan and manage community events
7. Feedback Collection: collect and analyze community feedback
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommunityMember:
    """A community member."""
    member_id: str
    username: str
    join_date: float
    contribution_score: float = 0.0
    engagement_score: float = 0.0
    reputation: int = 1
    badges: list[str] = field(default_factory=list)
    role: str = "member"  # member, moderator, admin, creator
    is_active: bool = True
    last_active: float = 0.0


@dataclass
class Comment:
    """A comment in the community."""
    comment_id: str
    author: str
    text: str
    timestamp: float
    video_id: str = ""
    likes: int = 0
    replies: int = 0
    sentiment: float = 0.0
    flagged: bool = False
    flag_reason: str = ""


@dataclass
class EngagementMetrics:
    """Community engagement metrics."""
    total_members: int
    active_members: int
    new_members_7d: int
    total_comments: int
    avg_comments_per_video: float
    engagement_rate: float
    top_contributors: list[str]
    growth_rate: float


@dataclass
class GrowthStrategy:
    """A community growth strategy."""
    strategy_id: str
    name: str
    description: str
    expected_growth: float
    effort_level: float
    recommended: bool
    actions: list[str]


class CommunityManager:
    """Community management engine."""

    def __init__(self):
        self._members: dict[str, CommunityMember] = {}
        self._comments: dict[str, Comment] = {}
        self._engagement: dict[str, EngagementMetrics] = {}
        self._growth_strategies: list[GrowthStrategy] = []

    # ── Community Engagement ───────────────────────────────────────────────

    def add_member(
        self,
        username: str,
        video_id: str = "",
    ) -> CommunityMember:
        """Add a new community member."""
        member_id = f"member_{len(self._members) + 1}"

        member = CommunityMember(
            member_id=member_id,
            username=username,
            join_date=time.time(),
            last_active=time.time(),
        )

        self._members[member_id] = member

        # Add welcome comment
        self.add_comment(
            author=member.username,
            text="Thanks for joining the community!",
            video_id=video_id,
        )

        return member

    def update_engagement(
        self,
        member_id: str,
        engagement_delta: float = 0.1,
    ) -> CommunityMember | None:
        """Update member engagement."""
        member = self._members.get(member_id)
        if not member:
            return None

        member.engagement_score = min(1.0, member.engagement_score + engagement_delta)
        member.contribution_score += engagement_delta * 10
        member.last_active = time.time()

        # Update reputation
        if member.contribution_score > 100 and member.reputation < 5:
            member.reputation += 1

        return member

    def calculate_engagement_metrics(self, channel_id: str) -> EngagementMetrics:
        """Calculate engagement metrics for a channel."""
        total = len(self._members)
        active = sum(1 for m in self._members.values() if m.is_active and time.time() - m.last_active < 86400 * 7)

        # Calculate 7-day new members
        cutoff = time.time() - 86400 * 7
        new_7d = sum(1 for m in self._members.values() if m.join_date > cutoff)

        # Total comments
        total_comments = len(self._comments)

        # Engagement rate
        engagement_rate = active / max(1, total)

        # Top contributors
        contributors = sorted(
            self._members.values(),
            key=lambda m: -m.contribution_score
        )[:5]

        growth_rate = new_7d / max(1, total)

        metrics = EngagementMetrics(
            total_members=total,
            active_members=active,
            new_members_7d=new_7d,
            total_comments=total_comments,
            avg_comments_per_video=total_comments / max(1, len(set(c.video_id for c in self._comments.values()))),
            engagement_rate=engagement_rate,
            top_contributors=[m.username for m in contributors],
            growth_rate=growth_rate,
        )

        self._engagement[channel_id] = metrics
        return metrics

    # ── Comment Analysis ─────────────────────────────────────────────────────

    def add_comment(
        self,
        author: str,
        text: str,
        video_id: str = "",
    ) -> Comment:
        """Add a comment to the community."""
        comment_id = f"comment_{len(self._comments) + 1}"

        # Analyze sentiment
        positive = ["love", "great", "amazing", "hype", "awesome", "nice"]
        negative = ["bad", "trash", "hate", "boring", "worst", "dislike"]

        text_lower = text.lower()
        pos = sum(1 for w in positive if w in text_lower)
        neg = sum(1 for w in negative if w in text_lower)
        sentiment = (pos - neg) / max(1, pos + neg)

        comment = Comment(
            comment_id=comment_id,
            author=author,
            text=text,
            timestamp=time.time(),
            video_id=video_id,
            sentiment=sentiment,
        )

        self._comments[comment_id] = comment

        # Update member engagement
        for member in self._members.values():
            if member.username == author:
                self.update_engagement(member.member_id, 0.05)
                break

        return comment

    def analyze_comments(
        self,
        video_id: str = "",
    ) -> dict[str, Any]:
        """Analyze comments for sentiment and insights."""
        comments = [
            c for c in self._comments.values()
            if not video_id or c.video_id == video_id
        ]

        if not comments:
            return {"total": 0, "sentiment": 0.0}

        sentiments = [c.sentiment for c in comments]
        avg_sentiment = sum(sentiments) / len(sentiments)

        # Top topics
        word_freq: dict[str, int] = {}
        for c in comments:
            for word in c.text.lower().split():
                if len(word) > 4:
                    word_freq[word] = word_freq.get(word, 0) + 1

        top_words = sorted(word_freq.items(), key=lambda x: -x[1])[:10]

        return {
            "total_comments": len(comments),
            "avg_sentiment": avg_sentiment,
            "sentiment_distribution": {
                "positive": sum(1 for s in sentiments if s > 0.3),
                "neutral": sum(1 for s in sentiments if -0.3 <= s <= 0.3),
                "negative": sum(1 for s in sentiments if s < -0.3),
            },
            "top_topics": [w for w, _ in top_words],
            "most_liked": sorted(comments, key=lambda c: -c.likes)[:5],
        }

    # ── Moderation Tools ────────────────────────────────────────────────────

    def flag_comment(
        self,
        comment_id: str,
        reason: str,
    ) -> bool:
        """Flag a comment for moderation."""
        comment = self._comments.get(comment_id)
        if comment:
            comment.flagged = True
            comment.flag_reason = reason
            return True
        return False

    def moderate_comments(self) -> dict[str, Any]:
        """Auto-moderate comments."""
        flagged = []
        spam_patterns = ["http://", "https://", "free money", "click here", "buy now"]

        for comment in self._comments.values():
            text_lower = comment.text.lower()

            # Check for spam
            if any(pattern in text_lower for pattern in spam_patterns):
                self.flag_comment(comment.comment_id, "spam")
                flagged.append(comment.comment_id)

            # Check for negative sentiment
            if comment.sentiment < -0.5:
                # Flag only if very negative
                if len(comment.text) > 200:
                    self.flag_comment(comment.comment_id, "potentially_inappropriate")
                    flagged.append(comment.comment_id)

        return {
            "flagged_count": len(flagged),
            "flagged_ids": flagged,
            "total_comments": len(self._comments),
        }

    # ── Community Growth ────────────────────────────────────────────────────

    def generate_growth_strategies(
        self,
        current_members: int,
        niche: str,
    ) -> list[GrowthStrategy]:
        """Generate community growth strategies."""
        strategies = []

        # Strategy 1: Challenges and giveaways
        strategies.append(GrowthStrategy(
            strategy_id="strategy_1",
            name="Community Challenge",
            description="Launch a community challenge with rewards",
            expected_growth=0.25,
            effort_level=0.6,
            recommended=True,
            actions=[
                "Create a monthly challenge",
                "Offer prizes for top contributors",
                "Promote challenge in videos",
                "Track participation and announce winners",
            ],
        ))

        # Strategy 2: Live Q&A
        strategies.append(GrowthStrategy(
            strategy_id="strategy_2",
            name="Live Q&A Sessions",
            description="Host regular live Q&A sessions",
            expected_growth=0.15,
            effort_level=0.4,
            recommended=True,
            actions=[
                "Schedule weekly live Q&A",
                "Promote upcoming sessions",
                "Collect questions in advance",
                "Follow up with answered questions in community",
            ],
        ))

        # Strategy 3: Community Discord/Server
        strategies.append(GrowthStrategy(
            strategy_id="strategy_3",
            name="Community Server",
            description="Create a Discord or similar community server",
            expected_growth=0.30,
            effort_level=0.8,
            recommended=True,
            actions=[
                "Set up Discord server",
                "Create channels for different topics",
                "Establish server rules",
                "Host events and activities",
                "Regularly engage with members",
            ],
        ))

        # Strategy 4: User-Generated Content
        strategies.append(GrowthStrategy(
            strategy_id="strategy_4",
            name="User-Generated Content",
            description="Encourage members to create content",
            expected_growth=0.20,
            effort_level=0.5,
            recommended=True,
            actions=[
                "Create a content creation challenge",
                "Feature user content in videos",
                "Provide content creation tips",
                "Reward top content creators",
            ],
        ))

        self._growth_strategies = strategies
        return strategies

    # ── Leaderboard Management ───────────────────────────────────────────────

    def get_leaderboard(self, limit: int = 10) -> list[dict]:
        """Get community leaderboard."""
        sorted_members = sorted(
            self._members.values(),
            key=lambda m: -m.contribution_score
        )[:limit]

        return [
            {
                "rank": i + 1,
                "username": m.username,
                "contribution_score": m.contribution_score,
                "reputation": m.reputation,
                "badges": m.badges,
                "role": m.role,
            }
            for i, m in enumerate(sorted_members)
        ]

    def assign_badge(
        self,
        member_id: str,
        badge: str,
    ) -> bool:
        """Assign a badge to a member."""
        member = self._members.get(member_id)
        if member:
            member.badges.append(badge)
            return True
        return False

    # ── Event Planning ───────────────────────────────────────────────────────

    def plan_event(
        self,
        event_name: str,
        event_type: str,
        description: str,
        target_attendees: int = 50,
    ) -> dict[str, Any]:
        """Plan a community event."""
        event = {
            "event_id": f"event_{int(time.time())}",
            "name": event_name,
            "type": event_type,
            "description": description,
            "target_attendees": target_attendees,
            "created_at": time.time(),
            "status": "planning",
            "actions": [
                "Create event announcement",
                "Schedule event date and time",
                "Promote event in community",
                "Prepare event materials",
                "Assign moderators for event",
            ],
        }

        return event

    # ── Feedback Collection ─────────────────────────────────────────────────

    def collect_feedback(
        self,
        topic: str,
        feedback_items: list[dict],
    ) -> dict[str, Any]:
        """Collect and analyze community feedback."""
        positive = sum(1 for f in feedback_items if f.get("rating", 0) > 3)
        neutral = sum(1 for f in feedback_items if f.get("rating", 0) == 3)
        negative = sum(1 for f in feedback_items if f.get("rating", 0) < 3)

        avg_rating = sum(f.get("rating", 0) for f in feedback_items) / max(1, len(feedback_items))

        # Extract common themes
        themes: dict[str, int] = {}
        for f in feedback_items:
            text = f.get("comment", "").lower()
            for word in text.split():
                if len(word) > 5:
                    themes[word] = themes.get(word, 0) + 1

        top_themes = sorted(themes.items(), key=lambda x: -x[1])[:5]

        return {
            "topic": topic,
            "total_feedback": len(feedback_items),
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "avg_rating": avg_rating,
            "top_themes": [t for t, _ in top_themes],
            "recommendation": (
                "Overall positive feedback" if avg_rating > 3.5 else
                "Mixed feedback - review concerns" if avg_rating > 2.5 else
                "Negative feedback - address issues"
            ),
        }

    # ── Reporting ──────────────────────────────────────────────────────────

    def get_community_report(self) -> dict[str, Any]:
        """Generate a community report."""
        return {
            "total_members": len(self._members),
            "total_comments": len(self._comments),
            "flagged_comments": sum(1 for c in self._comments.values() if c.flagged),
            "growth_strategies": len(self._growth_strategies),
            "avg_engagement": sum(m.engagement_score for m in self._members.values()) / max(1, len(self._members)),
        }
