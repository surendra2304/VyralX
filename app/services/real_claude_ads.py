"""
VyralX — claude-ads Engine

Claude-first paid-media ops across 12 ad platforms (Google, Meta, YouTube,
LinkedIn, TikTok, Microsoft, Apple, Amazon, Reddit, Pinterest, Snapchat, X).
Source-grounded audits, versioned JSON reports, capability-gated account
changes.

Tests: tests/test_real_batch4a.py
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


PLATFORMS = [
    "google_ads", "meta_ads", "youtube_ads", "linkedin_ads",
    "tiktok_ads", "microsoft_ads", "apple_ads", "amazon_ads",
    "reddit_ads", "pinterest_ads", "snapchat_ads", "x_ads",
]


@dataclass
class AdAccount:
    """Single ad account on a platform."""
    platform: str
    account_id: str
    name: str
    currency: str = "USD"
    timezone: str = "UTC"
    status: str = "active"
    spend_cap: float = 100000.0
    daily_spend: float = 0.0
    lifetime_spend: float = 0.0

    @property
    def remaining_cap(self) -> float:
        return max(self.spend_cap - self.lifetime_spend, 0.0)

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    def record_spend(self, amount: float) -> None:
        self.daily_spend += amount
        self.lifetime_spend += amount


@dataclass
class Campaign:
    """Ad campaign."""
    platform: str
    account_id: str
    campaign_id: str
    name: str
    objective: str = "conversions"
    status: str = "draft"
    budget_daily: float = 100.0
    budget_total: float = 10000.0
    spend: float = 0.0
    impressions: int = 0
    clicks: int = 0
    conversions: int = 0

    @property
    def ctr(self) -> float:
        if self.impressions <= 0:
            return 0.0
        return self.clicks / self.impressions

    @property
    def cpa(self) -> float:
        if self.conversions <= 0:
            return 0.0
        return self.spend / self.conversions

    @property
    def roas(self) -> float:
        if self.spend <= 0:
            return 0.0
        return self.conversions * 100 / self.spend if self.objective == "conversions" else 0.0

    def record_impression(self) -> None:
        self.impressions += 1

    def record_click(self) -> None:
        self.clicks += 1

    def record_conversion(self) -> None:
        self.conversions += 1

    def record_spend(self, amount: float) -> None:
        self.spend += amount

    def remaining_budget(self) -> float:
        return max(self.budget_total - self.spend, 0.0)


@dataclass
class AdCreative:
    """Ad creative asset."""
    creative_id: str
    platform: str
    name: str
    format: str = "image"
    title: str = ""
    description: str = ""
    cta: str = "learn_more"
    created_at: str = ""
    status: str = "draft"
    approval_status: str = "pending"

    @property
    def is_approved(self) -> bool:
        return self.approval_status == "approved"

    @property
    def cta_label(self) -> str:
        cta_map = {
            "learn_more": "Learn More",
            "buy_now": "Buy Now",
            "sign_up": "Sign Up",
            "subscribe": "Subscribe",
            "download": "Download",
            "contact_us": "Contact Us",
        }
        return cta_map.get(self.cta, self.cta)

    def approve(self) -> None:
        self.approval_status = "approved"
        self.status = "active"

    def reject(self, reason: str = "") -> None:
        self.approval_status = "rejected"
        self.status = "inactive"


@dataclass
class PlatformAdapter:
    """Adapter for a specific ad platform."""
    platform: str
    api_version: str = "v1"

    @property
    def supported_objectives(self) -> list[str]:
        objective_map = {
            "google_ads": ["search", "display", "video", "shopping", "app"],
            "meta_ads": ["awareness", "consideration", "conversion"],
            "youtube_ads": ["awareness", "consideration", "conversion"],
            "linkedin_ads": ["brand", "lead_gen", "website_traffic"],
            "tiktok_ads": ["awareness", "consideration", "conversion"],
            "microsoft_ads": ["search", "display", "video"],
            "apple_ads": ["app_install", "website_traffic"],
            "amazon_ads": ["product_awareness", "sales"],
            "reddit_ads": ["awareness", "traffic", "conversions"],
            "pinterest_ads": ["awareness", "traffic", "conversions"],
            "snapchat_ads": ["awareness", "consideration", "conversion"],
            "x_ads": ["awareness", "traffic", "conversions"],
        }
        return objective_map.get(self.platform, [])

    @property
    def supported_formats(self) -> list[str]:
        format_map = {
            "google_ads": ["text", "image", "video", "responsive"],
            "meta_ads": ["image", "video", "carousel", "story", "reels"],
            "youtube_ads": ["video", "bumper", "overlay"],
            "linkedin_ads": ["image", "video", "carousel", "document"],
            "tiktok_ads": ["video", "image", "spark_ads"],
            "microsoft_ads": ["text", "image", "video"],
            "apple_ads": ["image", "video", "native"],
            "amazon_ads": ["image", "video", "sponsored"],
            "reddit_ads": ["image", "video", "text", "carousel"],
            "pinterest_ads": ["image", "video", "carousel"],
            "snapchat_ads": ["image", "video", "story"],
            "x_ads": ["image", "video", "text"],
        }
        return format_map.get(self.platform, [])

    def can_target(self, objective: str) -> bool:
        return objective in self.supported_objectives

    def can_render(self, fmt: str) -> bool:
        return fmt in self.supported_formats

    def rate_limit(self) -> int:
        rl_map = {
            "google_ads": 10000,
            "meta_ads": 5000,
            "youtube_ads": 2000,
            "linkedin_ads": 1000,
            "tiktok_ads": 3000,
            "microsoft_ads": 8000,
            "apple_ads": 5000,
            "amazon_ads": 2000,
            "reddit_ads": 1000,
            "pinterest_ads": 2000,
            "snapchat_ads": 2000,
            "x_ads": 500,
        }
        return rl_map.get(self.platform, 1000)


@dataclass
class AdAudit:
    """Source-grounded ad account audit."""
    audit_id: str
    platform: str
    account_id: str
    audited_at: str
    findings: list[dict] = field(default_factory=list)

    @staticmethod
    def create_audit_id(platform: str, account_id: str) -> str:
        raw = f"{platform}:{account_id}:{hashlib.md5((platform + account_id).encode()).hexdigest()[:8]}"
        return raw

    def add_finding(self, severity: str, category: str, message: str) -> None:
        self.findings.append({
            "severity": severity,
            "category": category,
            "message": message,
        })

    def summary(self) -> dict[str, Any]:
        critical = sum(1 for f in self.findings if f["severity"] == "critical")
        warning = sum(1 for f in self.findings if f["severity"] == "warning")
        info = sum(1 for f in self.findings if f["severity"] == "info")
        return {
            "audit_id": self.audit_id,
            "platform": self.platform,
            "total_findings": len(self.findings),
            "critical": critical,
            "warning": warning,
            "info": info,
        }

    def to_json(self) -> str:
        return json.dumps(self.findings, indent=2, sort_keys=True)

    @staticmethod
    def version_hash(data: str) -> str:
        return hashlib.sha256(data.encode()).hexdigest()[:16]


@dataclass
class CapabilityGate:
    """Capability-gated account change system."""
    gate_id: str
    required_capability: str
    description: str = ""

    @staticmethod
    def check_capability(user_capabilities: list[str], required: str) -> bool:
        return required in user_capabilities

    @staticmethod
    def can_modify_budget(user_capabilities: list[str]) -> bool:
        return CapabilityGate.check_capability(user_capabilities, "budget_modification")

    @staticmethod
    def can_modify_creative(user_capabilities: list[str]) -> bool:
        return CapabilityGate.check_capability(user_capabilities, "creative_modification")

    @staticmethod
    def can_pause_campaign(user_capabilities: list[str]) -> bool:
        return CapabilityGate.check_capability(user_capabilities, "campaign_control")

    @staticmethod
    def can_edit_targeting(user_capabilities: list[str]) -> bool:
        return CapabilityGate.check_capability(user_capabilities, "targeting_modification")

    @staticmethod
    def required_capabilities_for_action(action: str) -> list[str]:
        action_map = {
            "budget_change": ["budget_modification"],
            "creative_change": ["creative_modification"],
            "campaign_pause": ["campaign_control"],
            "campaign_delete": ["campaign_control", "account_management"],
            "targeting_change": ["targeting_modification"],
            "account_link": ["account_management"],
        }
        return action_map.get(action, [])

    @staticmethod
    def authorize_action(user_capabilities: list[str], action: str) -> dict[str, Any]:
        required = CapabilityGate.required_capabilities_for_action(action)
        missing = [r for r in required if r not in user_capabilities]
        return {
            "action": action,
            "authorized": len(missing) == 0,
            "required": required,
            "missing": missing,
        }


@dataclass
class AdReport:
    """Versioned JSON ad performance report."""
    report_id: str
    platform: str
    period_start: str
    period_end: str
    metrics: dict[str, float] = field(default_factory=dict)
    version: int = 1

    def add_metric(self, name: str, value: float) -> None:
        self.metrics[name] = value

    def to_json(self) -> str:
        return json.dumps(self.metrics, indent=2, sort_keys=True)

    @property
    def report_hash(self) -> str:
        return hashlib.sha256(self.to_json().encode()).hexdigest()[:16]

    def diff_metrics(self, other: AdReport) -> dict[str, dict[str, float]]:
        diff = {}
        for key in set(self.metrics.keys()) | set(other.metrics.keys()):
            v1 = self.metrics.get(key, 0.0)
            v2 = other.metrics.get(key, 0.0)
            diff[key] = {"previous": v1, "current": v2, "change": v2 - v1}
        return diff

    @staticmethod
    def create_report_id(platform: str, period_start: str) -> str:
        return f"report-{platform}-{period_start}"


@dataclass
class CrossPlatformAnalyzer:
    """Cross-platform ad performance analysis."""
    @staticmethod
    def platform_performance(campaigns: list[Campaign]) -> dict[str, dict[str, float]]:
        by_platform: dict[str, list[Campaign]] = defaultdict(list)
        for c in campaigns:
            by_platform[c.platform].append(c)
        result = {}
        for platform, pcampaigns in by_platform.items():
            total_spend = sum(c.spend for c in pcampaigns)
            total_impressions = sum(c.impressions for c in pcampaigns)
            total_clicks = sum(c.clicks for c in pcampaigns)
            total_conversions = sum(c.conversions for c in pcampaigns)
            result[platform] = {
                "spend": total_spend,
                "impressions": total_impressions,
                "clicks": total_clicks,
                "conversions": total_conversions,
                "ctr": total_clicks / total_impressions if total_impressions > 0 else 0.0,
                "cpa": total_spend / total_conversions if total_conversions > 0 else 0.0,
                "campaign_count": len(pcampaigns),
            }
        return result

    @staticmethod
    def find_best_platform(campaigns: list[Campaign]) -> str:
        perf = CrossPlatformAnalyzer.platform_performance(campaigns)
        if not perf:
            return "unknown"
        return max(perf, key=lambda k: perf[k]["ctr"])

    @staticmethod
    def find_worst_platform(campaigns: list[Campaign]) -> str:
        perf = CrossPlatformAnalyzer.platform_performance(campaigns)
        if not perf:
            return "unknown"
        return min(perf, key=lambda k: perf[k]["ctr"])

    @staticmethod
    def budget_allocation(performance: dict[str, dict[str, float]], total_budget: float) -> dict[str, float]:
        total_spend = sum(p["spend"] for p in performance.values())
        if total_spend <= 0:
            alloc = len(performance)
            return {k: total_budget / alloc for k in performance}
        return {k: (total_budget * p["spend"] / total_spend) for k, p in performance.items()}

    @staticmethod
    def efficiency_score(platform: str, performance: dict[str, dict[str, float]]) -> float:
        if platform not in performance:
            return 0.0
        p = performance[platform]
        ctr_score = p["ctr"] / 0.05 if p["ctr"] > 0 else 0.0
        cpa_score = 0.1 / p["cpa"] if p["cpa"] > 0 else 0.0
        return ctr_score + cpa_score


@dataclass
class AdComplianceChecker:
    """Ad compliance verification."""
    @staticmethod
    def check_landing_page_consistency(ad_url: str, landing_url: str) -> bool:
        return ad_url.split("://")[-1].split("/")[0] == landing_url.split("://")[-1].split("/")[0]

    @staticmethod
    def check_disclosure(creative: AdCreative) -> bool:
        return "#ad" in creative.description or "#sponsored" in creative.description or "sponsored" in creative.description.lower()

    @staticmethod
    def check_targeting_compliance(targeting: dict[str, Any]) -> bool:
        sensitive = targeting.get("sensitive_categories", [])
        excluded = targeting.get("excluded_categories", [])
        return len(sensitive) == 0 and len(excluded) >= 0

    @staticmethod
    def check_budget_compliance(campaign: Campaign) -> bool:
        return campaign.spend <= campaign.budget_total

    @staticmethod
    def check_platform_policies(creative: AdCreative, platform: str) -> dict[str, Any]:
        results = {}
        if platform == "meta_ads":
            results["text_ratio"] = len(creative.title) / max(len(creative.title) + len(creative.description), 1)
            results["passed"] = results["text_ratio"] < 0.5
        elif platform == "google_ads":
            results["passed"] = len(creative.title) <= 30
        elif platform == "linkedin_ads":
            results["passed"] = len(creative.description) <= 2000
        elif platform == "tiktok_ads":
            results["passed"] = len(creative.title) <= 51
        else:
            results["passed"] = True
        return results


@dataclass
class MultiPlatformAdManager:
    """Unified ad management across all platforms."""
    accounts: dict[str, AdAccount] = field(default_factory=dict)
    campaigns: dict[str, Campaign] = field(default_factory=dict)
    creatives: dict[str, AdCreative] = field(default_factory=dict)
    adapters: dict[str, PlatformAdapter] = field(default_factory=dict)

    def register_account(self, account: AdAccount) -> None:
        self.accounts[account.account_id] = account
        if account.platform not in self.adapters:
            self.adapters[account.platform] = PlatformAdapter(platform=account.platform)

    def create_campaign(self, campaign: Campaign) -> None:
        self.campaigns[campaign.campaign_id] = campaign

    def add_creative(self, creative: AdCreative) -> None:
        self.creatives[creative.creative_id] = creative

    def audit_account(self, account_id: str) -> AdAudit:
        account = self.accounts.get(account_id)
        if not account:
            audit = AdAudit(
                audit_id="unknown",
                platform="unknown",
                account_id=account_id,
                audited_at="",
            )
            audit.add_finding("critical", "account", "Account not found")
            return audit
        audit = AdAudit(
            audit_id=AdAudit.create_audit_id(account.platform, account.account_id),
            platform=account.platform,
            account_id=account.account_id,
            audited_at="",
        )
        if account.remaining_cap <= 0:
            audit.add_finding("critical", "budget", "Spend cap exceeded")
        if not account.is_active:
            audit.add_finding("warning", "status", "Account inactive")
        platform_campaigns = [c for c in self.campaigns.values() if c.account_id == account_id]
        if not platform_campaigns:
            audit.add_finding("info", "campaigns", "No campaigns found")
        return audit

    def generate_report(self, platform: str, period_start: str, period_end: str) -> AdReport:
        report = AdReport(
            report_id=AdReport.create_report_id(platform, period_start),
            platform=platform,
            period_start=period_start,
            period_end=period_end,
        )
        platform_campaigns = [c for c in self.campaigns.values() if c.platform == platform]
        total_spend = sum(c.spend for c in platform_campaigns)
        total_impressions = sum(c.impressions for c in platform_campaigns)
        total_clicks = sum(c.clicks for c in platform_campaigns)
        total_conversions = sum(c.conversions for c in platform_campaigns)
        report.add_metric("total_spend", total_spend)
        report.add_metric("total_impressions", total_impressions)
        report.add_metric("total_clicks", total_clicks)
        report.add_metric("total_conversions", total_conversions)
        report.add_metric("avg_ctr", total_clicks / total_impressions if total_impressions > 0 else 0.0)
        report.add_metric("avg_cpa", total_spend / total_conversions if total_conversions > 0 else 0.0)
        return report

    def manage_campaign(self, campaign_id: str, action: str, user_capabilities: list[str]) -> dict[str, Any]:
        campaign = self.campaigns.get(campaign_id)
        if not campaign:
            return {"success": False, "error": "Campaign not found"}
        auth = CapabilityGate.authorize_action(user_capabilities, action)
        if not auth["authorized"]:
            return {"success": False, "error": "Insufficient capabilities", "missing": auth["missing"]}
        if action == "pause":
            campaign.status = "paused"
        elif action == "activate":
            campaign.status = "active"
        elif action == "budget_change":
            campaign.budget_total *= 1.1
        return {"success": True, "campaign_id": campaign_id, "action": action}

    def total_portfolio_spend(self) -> float:
        return sum(c.spend for c in self.campaigns.values())

    def total_portfolio_impressions(self) -> int:
        return sum(c.impressions for c in self.campaigns.values())

    def total_portfolio_clicks(self) -> int:
        return sum(c.clicks for c in self.campaigns.values())

    def total_portfolio_conversions(self) -> int:
        return sum(c.conversions for c in self.campaigns.values())

    @property
    def platform_count(self) -> int:
        return len(self.adapters)

    @property
    def account_count(self) -> int:
        return len(self.accounts)

    @property
    def campaign_count(self) -> int:
        return len(self.campaigns)
