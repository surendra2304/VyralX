from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

try:
    from app.services.real_claude_ads import (
        MultiPlatformAdManager,
        AdComplianceChecker,
        AdAccount,
        Campaign,
        AdCreative,
    )
    from app.services.real_toprank import (
        TopRankManager,
        SEORanker,
        GEORanker,
        AnalyticsTracker,
        SafetyRuleEngine,
    )
    from app.services.real_open_higgsfield import (
        MultiModelStudio,
        GenerationRequest,
        PromptEnhancer,
    )
    from app.services.real_hyperframes import (
        HyperframesManager,
        HTMLScene,
        SceneTransition,
        AspectRatioHandler,
    )
except ImportError:
    from VyralX.app.services.real_claude_ads import (
        MultiPlatformAdManager,
        AdComplianceChecker,
        AdAccount,
        Campaign,
        AdCreative,
    )
    from VyralX.app.services.real_toprank import (
        TopRankManager,
        SEORanker,
        GEORanker,
        AnalyticsTracker,
        SafetyRuleEngine,
    )
    from VyralX.app.services.real_open_higgsfield import (
        MultiModelStudio,
        GenerationRequest,
        PromptEnhancer,
    )
    from VyralX.app.services.real_hyperframes import (
        HyperframesManager,
        HTMLScene,
        SceneTransition,
        AspectRatioHandler,
    )

logger = logging.getLogger("vyralx.real_media_routes")
router = APIRouter(prefix="/engines", tags=["Real Media & Growth Engines"])

_ad_manager = MultiPlatformAdManager()
_toprank_manager = TopRankManager()
_studio = MultiModelStudio()
_hyperframes = HyperframesManager()


# ── CLAUDE-ADS ENDPOINTS ─────────────────────────────────────────────────────

class CampaignCreateRequest(BaseModel):
    account_id: str = "acc_vyralx_001"
    name: str = "Q4 Omnichannel Growth"
    platform: str = "google_ads"
    objective: str = "conversions"
    budget_daily: float = 100.0
    budget_total: float = 5000.0


class ComplianceCheckRequest(BaseModel):
    title: str = "AI Agent Growth Suite"
    description: str = "Autonomous video marketing pipeline #ad"
    cta: str = "Get Started"
    platform: str = "google_ads"
    destination_url: str = "https://vyralx.ai/suite"
    landing_url: str = "https://vyralx.ai/pricing"


@router.post("/ads/campaign")
def create_ad_campaign(req: CampaignCreateRequest):
    """Create and register an advertising campaign across 12 supported platforms."""
    if req.account_id not in _ad_manager.accounts:
        _ad_manager.register_account(
            AdAccount(
                platform=req.platform,
                account_id=req.account_id,
                name=f"Account {req.account_id}",
            )
        )

    cid = f"camp_{uuid.uuid4().hex[:8]}"
    camp = Campaign(
        platform=req.platform,
        account_id=req.account_id,
        campaign_id=cid,
        name=req.name,
        objective=req.objective,
        budget_daily=req.budget_daily,
        budget_total=req.budget_total,
    )
    _ad_manager.create_campaign(camp)

    return {
        "status": "success",
        "engine": "ClaudeAds",
        "campaign_id": cid,
        "name": camp.name,
        "platform": camp.platform,
        "objective": camp.objective,
        "budget_daily": camp.budget_daily,
        "budget_total": camp.budget_total,
        "total_campaigns": _ad_manager.campaign_count,
        "total_accounts": _ad_manager.account_count,
    }


@router.post("/ads/compliance")
def check_ad_compliance(req: ComplianceCheckRequest):
    """Check creative text compliance against platform advertising safety guidelines."""
    creative = AdCreative(
        creative_id=f"c_{uuid.uuid4().hex[:6]}",
        platform=req.platform,
        name="Creative Verification",
        format="responsive_display",
        title=req.title,
        description=req.description,
        cta=req.cta,
        created_at="2026-10-25",
        status="active",
        approval_status="pending",
    )
    policy_res = AdComplianceChecker.check_platform_policies(creative, req.platform)
    disclosure = AdComplianceChecker.check_disclosure(creative)
    landing_check = AdComplianceChecker.check_landing_page_consistency(req.destination_url, req.landing_url)

    is_compliant = bool(policy_res.get("passed", True) and disclosure and landing_check)

    return {
        "status": "success",
        "engine": "ClaudeAds",
        "platform_policies": policy_res,
        "disclosure_check": disclosure,
        "landing_page_consistency": landing_check,
        "compliant": is_compliant,
    }


@router.get("/ads/report/{platform}")
def get_platform_ad_report(platform: str, start: str = "2026-01-01", end: str = "2026-12-31"):
    """Generate consolidated multi-platform ad report."""
    report = _ad_manager.generate_report(platform=platform, period_start=start, period_end=end)
    return {
        "status": "success",
        "engine": "ClaudeAds",
        "platform": platform,
        "report_id": report.report_id,
        "report_hash": report.report_hash,
        "metrics": report.metrics,
        "roas": report.metrics.get("roas", 0.0),
        "total_spend": report.metrics.get("total_spend", 0.0),
        "total_impressions": report.metrics.get("total_impressions", 0),
        "total_clicks": report.metrics.get("total_clicks", 0),
        "total_conversions": report.metrics.get("total_conversions", 0),
    }


# ── TOPRANK ENDPOINTS ────────────────────────────────────────────────────────

class SEOContentRequest(BaseModel):
    content: str
    keywords: List[str] = ["ai agent", "video generation", "growth"]
    url: str = "https://vyralx.ai/growth-engine"


class GEOOptimizeRequest(BaseModel):
    content: str
    query: str = "what is the best autonomous video generation engine"


@router.post("/toprank/analyze")
def analyze_content_seo(req: SEOContentRequest):
    """Analyze text content for keyword density, readability, and SEO score."""
    analysis = _toprank_manager.analyze_content(req.content, req.keywords)
    ranker = SEORanker()
    readability = ranker.readability_score(req.content)
    wc = ranker.word_count(req.content)

    return {
        "status": "success",
        "engine": "TopRank",
        "analysis": analysis,
        "readability_score": readability,
        "word_count": wc,
    }


@router.post("/toprank/geo-optimize")
def optimize_geo(req: GEOOptimizeRequest):
    """Run Generative Engine Optimization (GEO) scoring for AI agents & LLMs."""
    geo_res = _toprank_manager.geo_optimize(req.content, req.query)
    ai_vis = GEORanker.ai_visibility_score(req.content)
    llm_friendliness = GEORanker.llm_friendliness(req.content)

    return {
        "status": "success",
        "engine": "TopRank",
        "geo_analysis": geo_res,
        "ai_visibility_score": ai_vis,
        "llm_friendliness": llm_friendliness,
    }


@router.post("/toprank/safety")
def evaluate_marketing_safety(text: str):
    """Evaluate marketing content against safety and spam rules."""
    engine = SafetyRuleEngine()
    risk = engine.risk_score(text)
    is_safe = engine.is_safe(text)
    violations = engine.check_text(text)

    return {
        "status": "success",
        "engine": "TopRank",
        "is_safe": is_safe,
        "risk_score": risk,
        "violations": violations,
    }


# ── OPEN-HIGGSFIELD-AI ENDPOINTS ─────────────────────────────────────────────

class HiggsfieldGenRequest(BaseModel):
    prompt: str = "Cinematic 8k render of FRIDAY Universe multi-agent orchestrator"
    model: str = "Flux.1-dev"
    negative_prompt: str = "blurry, low quality"
    width: int = 1024
    height: int = 1024
    num_steps: int = 25


@router.post("/studio/generate")
def higgsfield_generate(req: HiggsfieldGenRequest):
    """Route and synthesize visual media across 600+ AI generation models."""
    rid = f"gen_{uuid.uuid4().hex[:8]}"
    gen_req = GenerationRequest(
        request_id=rid,
        model=req.model,
        prompt=req.prompt,
        negative_prompt=req.negative_prompt,
        width=req.width,
        height=req.height,
        num_steps=req.num_steps,
    )
    result = _studio.generate(gen_req)
    return {
        "status": "success",
        "engine": "OpenHiggsfieldAI",
        "generation_id": result.request_id,
        "model": result.model,
        "output_path": result.output_path,
        "elapsed_seconds": result.elapsed,
        "quality_score": result.quality_score,
        "seed": result.seed,
        "total_studio_generations": _studio.total_generations,
    }


@router.get("/studio/capabilities")
def higgsfield_capabilities():
    """Retrieve multi-model studio capacity, active models, and statistics."""
    caps = _studio.studio_capabilities()
    stats = _studio.model_statistics()
    return {
        "status": "success",
        "engine": "OpenHiggsfieldAI",
        "capabilities": caps,
        "model_statistics": stats,
    }


# ── HYPERFRAMES ENDPOINTS ────────────────────────────────────────────────────

class HyperframesScriptRequest(BaseModel):
    title: str = "Autonomous Video Pipeline"
    text: str = "FRIDAY Universe coordinates ten specialized agents. Each engine operates autonomously."


@router.post("/hyperframes/create-script")
def create_hyperframes_script(req: HyperframesScriptRequest):
    """Create video script and compose HTML scenes."""
    script = _hyperframes.create_script(req.title, req.text)
    manifest = _hyperframes.export_manifest(req.title)
    pacing = _hyperframes.optimize_scenes(req.title)

    return {
        "status": "success",
        "engine": "Hyperframes",
        "title": script.title,
        "scene_count": script.scene_count(),
        "total_duration": script.total_duration(),
        "manifest": manifest,
        "pacing_optimization": pacing,
        "total_scenes_in_manager": _hyperframes.total_scenes,
    }


@router.get("/hyperframes/aspect-ratios")
def get_supported_aspect_ratios():
    """List supported aspect ratios and compute standard resolutions."""
    aspects = ["16:9", "9:16", "1:1", "4:5"]
    resolutions = {a: AspectRatioHandler.resolution_for(a) for a in aspects}
    return {
        "status": "success",
        "engine": "Hyperframes",
        "supported_aspect_ratios": aspects,
        "resolutions": resolutions,
    }
