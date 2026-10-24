"""
VyralX/app/services/creator_collaboration_manager.py — VyralX Creator Collaboration Manager.

Manages creator collaborations: collab matching, partnership tracking,
cross-promotion campaigns, revenue splitting, and collaboration analytics.
Provides tools for creators to find and manage partnerships.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()


@dataclass
class CreatorProfile:
    """A creator profile for collaboration."""
    creator_id: str
    name: str
    platform: str
    niche: str = ""
    audience_size: int = 0
    engagement_rate: float = 0.0
    avg_views: int = 0
    collaboration_count: int = 0
    rating: float = 0.0
    created_at: float = 0.0


@dataclass
class CollaborationProposal:
    """A collaboration proposal."""
    proposal_id: str
    creator_a: str
    creator_b: str
    proposal_type: str = ""  # collab_video, shoutout, sponsorship, cross_promo
    status: str = "pending"  # pending, accepted, rejected, completed
    revenue_split: str = "50/50"
    proposed_at: float = 0.0
    responded_at: float = 0.0


@dataclass
class Collaboration:
    """An active collaboration."""
    collaboration_id: str
    creator_a: str
    creator_b: str
    type: str = ""
    content_url: str = ""
    views: int = 0
    engagement: float = 0.0
    revenue: float = 0.0
    revenue_split_a: float = 0.0
    revenue_split_b: float = 0.0
    status: str = "active"  # active, completed, archived
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class MatchScore:
    """Collaboration match score between two creators."""
    creator_a: str
    creator_b: str
    score: float = 0.0
    factors: dict = field(default_factory=dict)  # {niche_match, audience_overlap, engagement_parity}
    reasons: list[str] = field(default_factory=list)


@dataclass
class CrossPromoCampaign:
    """A cross-promotion campaign."""
    campaign_id: str
    name: str
    creators: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    content_schedule: list[dict] = field(default_factory=list)
    estimated_reach: int = 0
    actual_reach: int = 0
    status: str = "planning"  # planning, active, completed
    started_at: float = 0.0
    completed_at: float = 0.0


@dataclass
class CollaborationAnalytics:
    """Analytics for collaborations."""
    creator_id: str
    total_collabs: int = 0
    successful_collabs: int = 0
    avg_views_per_collab: int = 0
    total_revenue: float = 0.0
    avg_rating: float = 0.0
    best_partner: str = ""
    top_content: str = ""


class CreatorCollaborationManager:
    """Creator collaboration management engine."""

    def __init__(self):
        self._creators: dict[str, CreatorProfile] = {}
        self._proposals: list[CollaborationProposal] = []
        self._collabs: dict[str, Collaboration] = {}
        self._matches: list[MatchScore] = []
        self._campaigns: dict[str, CrossPromoCampaign] = {}
        self._analytics: dict[str, CollaborationAnalytics] = {}

    def register_creator(
        self,
        name: str,
        platform: str,
        niche: str,
        audience_size: int,
        engagement_rate: float = 0.05,
        avg_views: int = 1000,
    ) -> CreatorProfile:
        """Register a creator."""
        creator = CreatorProfile(
            creator_id=hashlib.md5(
                f"creator:{name}:{platform}:{time.time()}".encode()
            ).hexdigest()[:12],
            name=name,
            platform=platform,
            niche=niche,
            audience_size=audience_size,
            engagement_rate=engagement_rate,
            avg_views=avg_views,
            rating=4.0 + (ord(hashlib.md5(name.encode()).hexdigest()[:1]) % 10) / 10,
            created_at=time.time(),
        )
        self._creators[creator.creator_id] = creator
        return creator

    def propose_collab(
        self,
        creator_a_id: str,
        creator_b_id: str,
        proposal_type: str,
        revenue_split: str = "50/50",
    ) -> CollaborationProposal:
        """Propose a collaboration."""
        proposal = CollaborationProposal(
            proposal_id=hashlib.md5(
                f"proposal:{creator_a_id}:{creator_b_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            creator_a=creator_a_id,
            creator_b=creator_b_id,
            proposal_type=proposal_type,
            revenue_split=revenue_split,
            proposed_at=time.time(),
        )
        self._proposals.append(proposal)
        return proposal

    def accept_proposal(self, proposal_id: str) -> Collaboration:
        """Accept a collaboration proposal and create a collaboration."""
        proposal = None
        for p in self._proposals:
            if p.proposal_id == proposal_id:
                proposal = p
                break

        if not proposal:
            raise HTTPException(404, f"Proposal {proposal_id} not found")

        proposal.status = "accepted"
        proposal.responded_at = time.time()

        # Create collaboration
        collab = Collaboration(
            collaboration_id=hashlib.md5(
                f"collab:{proposal_id}:{time.time()}".encode()
            ).hexdigest()[:12],
            creator_a=proposal.creator_a,
            creator_b=proposal.creator_b,
            type=proposal.proposal_type,
            started_at=time.time(),
        )

        # Parse revenue split
        parts = proposal.revenue_split.split("/")
        if len(parts) == 2:
            collab.revenue_split_a = float(parts[0]) / 100
            collab.revenue_split_b = float(parts[1]) / 100

        self._collabs[collab.collaboration_id] = collab
        return collab

    def calculate_match(self, creator_a_id: str, creator_b_id: str) -> MatchScore:
        """Calculate match score between two creators."""
        a = self._creators.get(creator_a_id)
        b = self._creators.get(creator_b_id)

        if not a or not b:
            return MatchScore(creator_a=creator_a_id, creator_b=creator_b_id, score=0.0)

        # Niche match
        niche_match = 1.0 if a.niche == b.niche else 0.3

        # Audience overlap (simplified)
        audience_match = 1.0 if abs(a.audience_size - b.audience_size) / max(1, a.audience_size) < 0.5 else 0.5

        # Engagement parity
        engagement_match = 1.0 - abs(a.engagement_rate - b.engagement_rate) * 10

        # Overall score
        score = (niche_match * 0.4 + audience_match * 0.3 + engagement_match * 0.3)

        match = MatchScore(
            creator_a=creator_a_id,
            creator_b=creator_b_id,
            score=round(score, 3),
            factors={
                "niche_match": niche_match,
                "audience_overlap": audience_match,
                "engagement_parity": round(engagement_match, 3),
            },
            reasons=[
                f"Niche match: {niche_match:.0%}",
                f"Audience size parity: {audience_match:.0%}",
                f"Engagement rate match: {engagement_match:.0%}",
            ],
        )

        self._matches.append(match)
        return match

    def create_campaign(self, name: str, creators: list[str], platforms: list[str]) -> CrossPromoCampaign:
        """Create a cross-promotion campaign."""
        campaign = CrossPromoCampaign(
            campaign_id=hashlib.md5(
                f"campaign:{name}:{time.time()}".encode()
            ).hexdigest()[:12],
            name=name,
            creators=creators,
            platforms=platforms,
            estimated_reach=sum(
                self._creators.get(c, CreatorProfile("", "", "", 0)).audience_size
                for c in creators
            ),
            started_at=time.time(),
        )

        # Create content schedule
        for i, creator in enumerate(creators):
            campaign.content_schedule.append({
                "creator": creator,
                "content_type": "collab_video",
                "scheduled_at": time.time() + (i + 1) * 86400,
            })

        self._campaigns[campaign.campaign_id] = campaign
        return campaign

    def complete_collaboration(self, collaboration_id: str, views: int, revenue: float = 0.0) -> Collaboration:
        """Mark a collaboration as complete with results."""
        collab = self._collabs.get(collaboration_id)
        if not collab:
            raise HTTPException(404, f"Collaboration {collaboration_id} not found")

        collab.views = views
        collab.engagement = views * 0.05
        collab.revenue = revenue
        collab.revenue_split_a = revenue * collab.revenue_split_a
        collab.revenue_split_b = revenue * collab.revenue_split_b
        collab.status = "completed"
        collab.completed_at = time.time()
        collab.content_url = f"https://collab.example.com/{collaboration_id}"

        # Update analytics
        for creator_id in [collab.creator_a, collab.creator_b]:
            analytics = self._analytics.get(creator_id)
            if not analytics:
                analytics = CollaborationAnalytics(creator_id=creator_id)
                self._analytics[creator_id] = analytics

            analytics.total_collabs += 1
            analytics.successful_collabs += 1
            analytics.avg_views_per_collab = (
                analytics.avg_views_per_collab * 0.9 + views * 0.1
            )
            analytics.total_revenue += revenue

        return collab

    def get_analytics(self, creator_id: str) -> CollaborationAnalytics:
        """Get collaboration analytics for a creator."""
        analytics = self._analytics.get(creator_id)
        if not analytics:
            analytics = CollaborationAnalytics(creator_id=creator_id)
            self._analytics[creator_id] = analytics

        # Get creator's collaborations
        cretor_collabs = [c for c in self._collabs.values() if creator_id in [c.creator_a, c.creator_b]]
        analytics.total_collabs = len(cretor_collabs)
        analytics.successful_collabs = sum(1 for c in cretor_collabs if c.status == "completed")

        if cretor_collabs:
            analytics.avg_views_per_collab = sum(c.views for c in cretor_collabs) / len(cretor_collabs)
            analytics.total_revenue = sum(c.revenue for c in cretor_collabs)

        return analytics

    def get_report(self) -> dict:
        """Get creator collaboration manager report."""
        return {
            "total_creators": len(self._creators),
            "total_proposals": len(self._proposals),
            "total_collabs": len(self._collabs),
            "total_matches": len(self._matches),
            "total_campaigns": len(self._campaigns),
            "total_analytics": len(self._analytics),
            "accepted_proposals": sum(1 for p in self._proposals if p.status == "accepted"),
            "completed_collabs": sum(1 for c in self._collabs.values() if c.status == "completed"),
            "active_collabs": sum(1 for c in self._collabs.values() if c.status == "active"),
            "platforms": list(set(c.platform for c in self._creators.values())),
            "niches": list(set(c.niche for c in self._creators.values())),
            "recent_matches": [
                {"a": m.creator_a, "b": m.creator_b, "score": m.score, "reasons": m.reasons[:2]}
                for m in self._matches[-5:]
            ],
            "recent_collabs": [
                {"type": c.type, "views": c.views, "revenue": c.revenue, "status": c.status}
                for c in list(self._collabs.values())[-5:]
            ],
        }


collab_manager = CreatorCollaborationManager()


@router.post("/api/v1/vyralx/collab/creators")
async def register_creator(payload: dict):
    """Register a creator."""
    creator = collab_manager.register_creator(
        name=payload["name"],
        platform=payload["platform"],
        niche=payload["niche"],
        audience_size=payload["audience_size"],
        engagement_rate=payload.get("engagement_rate", 0.05),
        avg_views=payload.get("avg_views", 1000),
    )
    return {"creator_id": creator.creator_id, "name": creator.name, "platform": creator.platform}


@router.post("/api/v1/vyralx/collab/match")
async def calculate_match(payload: dict):
    """Calculate match between two creators."""
    match = collab_manager.calculate_match(
        creator_a_id=payload["creator_a"],
        creator_b_id=payload["creator_b"],
    )
    return {"score": match.score, "factors": match.factors, "reasons": match.reasons}


@router.post("/api/v1/vyralx/collab/proposals")
async def propose_collab(payload: dict):
    """Propose a collaboration."""
    proposal = collab_manager.propose_collab(
        creator_a_id=payload["creator_a"],
        creator_b_id=payload["creator_b"],
        proposal_type=payload["proposal_type"],
        revenue_split=payload.get("revenue_split", "50/50"),
    )
    return {"proposal_id": proposal.proposal_id, "type": proposal.proposal_type, "status": proposal.status}


@router.post("/api/v1/vyralx/collab/proposals/{proposal_id}/accept")
async def accept_proposal(proposal_id: str):
    """Accept a collaboration proposal."""
    collab = collab_manager.accept_proposal(proposal_id)
    return {"collaboration_id": collab.collaboration_id, "type": collab.type, "status": collab.status}


@router.post("/api/v1/vyralx/collab/collabs/{collab_id}/complete")
async def complete_collaboration(collab_id: str, payload: dict):
    """Complete a collaboration with results."""
    collab = collab_manager.complete_collaboration(
        collaboration_id=collab_id,
        views=payload.get("views", 0),
        revenue=payload.get("revenue", 0.0),
    )
    return {"collaboration_id": collab.collaboration_id, "views": collab.views, "revenue": collab.revenue, "status": collab.status}


@router.get("/api/v1/vyralx/collab/report")
async def get_report():
    """Get creator collaboration manager report."""
    return collab_manager.get_report()
