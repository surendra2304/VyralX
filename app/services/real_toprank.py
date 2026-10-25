"""
VyralX — toprank Engine

SEO, GEO, and marketing ranking for AI agents. Analytics, MCP surfaces,
safety rules, and agent marketing skills.

Tests: tests/test_real_batch4a.py
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SEORanker:
    """Search engine optimization ranker."""
    @staticmethod
    def keyword_density(text: str, keywords: list[str]) -> dict[str, float]:
        if not text:
            return {kw: 0.0 for kw in keywords}
        words = text.lower().split()
        total_words = len(words)
        if total_words == 0:
            return {kw: 0.0 for kw in keywords}
        result = {}
        for kw in keywords:
            count = sum(1 for w in words if kw.lower() in w)
            result[kw] = count / total_words
        return result

    @staticmethod
    def word_count(text: str) -> int:
        return len(text.split())

    @staticmethod
    def readability_score(text: str) -> float:
        words = text.split()
        sentences = re.split(r'[.!?]+', text)
        sentences = [s for s in sentences if s.strip()]
        if len(words) == 0 or len(sentences) == 0:
            return 0.0
        syllables = sum(SEORanker._count_syllables(w) for w in words)
        score = 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words))
        return max(0.0, min(100.0, score))

    @staticmethod
    def _count_syllables(word: str) -> int:
        word = re.sub(r'[^a-z]', '', word.lower())
        if not word:
            return 0
        vowels = "aeiouy"
        count = 0
        prev_vowel = False
        for c in word:
            is_vowel = c in vowels
            if is_vowel and not prev_vowel:
                count += 1
            prev_vowel = is_vowel
        if word.endswith("e"):
            count = max(1, count - 1)
        return max(1, count)

    @staticmethod
    def meta_description_score(description: str) -> float:
        length = len(description)
        if length < 120:
            return 0.5
        elif length > 160:
            return 0.5
        return 1.0

    @staticmethod
    def heading_structure(html_content: str) -> dict[str, int]:
        headings = re.findall(r'<h([1-6])[^>]*>(.*?)</h\1>', html_content, re.DOTALL)
        counts = defaultdict(int)
        for level, content in headings:
            counts[int(level)] += 1
        return dict(counts)

    @staticmethod
    def alt_text_score(html_content: str) -> float:
        imgs = re.findall(r'<img[^>]*>', html_content)
        if not imgs:
            return 1.0
        with_alt = sum(1 for img in imgs if 'alt=' in img and 'alt=""' not in img and 'alt=' not in img.split('alt=')[1][:5])
        return with_alt / len(imgs)

    @staticmethod
    def internal_link_structure(html_content: str) -> dict[str, Any]:
        links = re.findall(r'href="([^"]*)"', html_content)
        internal = [l for l in links if not l.startswith("http") and not l.startswith("//")]
        external = [l for l in links if l.startswith("http") or l.startswith("//")]
        return {
            "internal_count": len(internal),
            "external_count": len(external),
            "total": len(links),
        }

    @staticmethod
    def content_score(text: str, keywords: list[str]) -> float:
        wc = SEORanker.word_count(text)
        if wc == 0:
            return 0.0
        density = SEORanker.keyword_density(text, keywords)
        readability = SEORanker.readability_score(text)
        return (sum(density.values()) / len(keywords) * 0.4 + readability / 100 * 0.3 + min(wc / 1000, 1.0) * 0.3)

    @staticmethod
    def url_score(url: str) -> float:
        score = 0.0
        if len(url) < 80:
            score += 0.3
        if "-" in url:
            score += 0.2
        if re.search(r'\.com|\.org|\.net', url):
            score += 0.2
        if not re.search(r'[0-9]{4,}', url):
            score += 0.15
        if not url.endswith("/"):
            score += 0.15
        return min(1.0, score)

    @staticmethod
    def schema_markup_score(html_content: str) -> float:
        schema_types = ["Article", "Product", "FAQPage", "HowTo", "BreadcrumbList", "LocalBusiness"]
        found = sum(1 for st in schema_types if st.lower() in html_content.lower())
        return found / len(schema_types)


@dataclass
class GEORanker:
    """Generative Engine Optimization ranker."""
    @staticmethod
    def ai_visibility_score(text: str) -> float:
        if not text:
            return 0.0
        sentences = re.split(r'[.!?]', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        if not sentences:
            return 0.0
        answer_like = sum(1 for s in sentences if len(s) < 200 and len(s) > 20)
        structured = sum(1 for s in sentences if ":" in s or " - " in s)
        return (answer_like / len(sentences) * 0.5 + structured / len(sentences) * 0.5)

    @staticmethod
    def llm_friendliness(text: str) -> dict[str, float]:
        if not text:
            return {"score": 0.0, "structured_ratio": 0.0, "length_score": 0.0}
        sentences = [s.strip() for s in re.split(r'[.!?]', text) if s.strip()]
        total = len(sentences)
        if total == 0:
            return {"score": 0.0, "structured_ratio": 0.0, "length_score": 0.0}
        structured = sum(1 for s in sentences if len(s.split()) <= 30)
        short = sum(1 for s in sentences if len(s) < 150)
        score = (structured / total * 0.4 + short / total * 0.3 + min(len(text) / 2000, 1.0) * 0.3)
        return {
            "score": score,
            "structured_ratio": structured / total,
            "length_score": short / total,
        }

    @staticmethod
    def citation_density(text: str) -> float:
        numbers = re.findall(r'\d+', text)
        if not text:
            return 0.0
        return len(numbers) / max(len(text.split()), 1)

    @staticmethod
    def authoritative_signals(text: str) -> float:
        signals = []
        if "according to" in text.lower():
            signals.append(True)
        if "research" in text.lower() or "study" in text.lower():
            signals.append(True)
        if "source" in text.lower() or "cited" in text.lower():
            signals.append(True)
        if "expert" in text.lower():
            signals.append(True)
        return len(signals) / 4

    @staticmethod
    def entity_density(text: str) -> float:
        entities = re.findall(r'\b[A-Z][a-z]+(?:\s[A-Z][a-z]+)*\b', text)
        if not text:
            return 0.0
        return len(set(entities)) / max(len(text.split()) / 100, 1)

    @staticmethod
    def topic_authority(contents: list[str], topic: str) -> float:
        if not contents:
            return 0.0
        topic_count = sum(1 for c in contents if topic.lower() in c.lower())
        return topic_count / len(contents)

    @staticmethod
    def generative_answer_score(text: str, query: str) -> float:
        if not text or not query:
            return 0.0
        text_lower = text.lower()
        query_words = query.lower().split()
        matched = sum(1 for qw in query_words if qw in text_lower)
        if not query_words:
            return 0.0
        return matched / len(query_words)


@dataclass
class AnalyticsTracker:
    """Marketing analytics tracker."""
    events: dict[str, list[dict]] = field(default_factory=dict)

    def track_event(self, event_type: str, user_id: str, metadata: dict[str, Any] | None = None) -> None:
        if metadata is None:
            metadata = {}
        event = {
            "type": event_type,
            "user_id": user_id,
            "timestamp": time.time(),
            "metadata": metadata,
        }
        self.events.setdefault(event_type, []).append(event)

    @property
    def event_count(self) -> int:
        return sum(len(v) for v in self.events.values())

    @property
    def event_types(self) -> list[str]:
        return list(self.events.keys())

    def event_count_by_type(self, event_type: str) -> int:
        return len(self.events.get(event_type, []))

    def unique_users(self) -> int:
        users = set()
        for events in self.events.values():
            for e in events:
                users.add(e["user_id"])
        return len(users)

    def conversion_rate(self, visits: int, conversions: int) -> float:
        if visits <= 0:
            return 0.0
        return conversions / visits

    def bounce_rate(self, visits: int, bounces: int) -> float:
        if visits <= 0:
            return 0.0
        return bounces / visits

    def engagement_rate(self, interactions: int, visits: int) -> float:
        if visits <= 0:
            return 0.0
        return interactions / visits

    def click_through_rate(self, clicks: int, impressions: int) -> float:
        if impressions <= 0:
            return 0.0
        return clicks / impressions

    def average_session_duration(self, durations: list[float]) -> float:
        if not durations:
            return 0.0
        return sum(durations) / len(durations)

    def funnel_analysis(self, stages: dict[str, int]) -> dict[str, float]:
        stages_list = list(stages.items())
        result = {}
        for i in range(len(stages_list)):
            name, count = stages_list[i]
            if i == 0:
                result[name] = 1.0 if count > 0 else 0.0
            else:
                prev_count = stages_list[i - 1][1]
                result[name] = count / prev_count if prev_count > 0 else 0.0
        return result

    def cohort_retention(self, cohorts: dict[str, list[int]]) -> dict[str, list[float]]:
        result = {}
        for cohort_id, counts in cohorts.items():
            if not counts or counts[0] == 0:
                result[cohort_id] = []
                continue
            retention = [c / counts[0] for c in counts]
            result[cohort_id] = retention
        return result

    def attribution_model(self, touchpoints: list[dict]) -> dict[str, float]:
        if not touchpoints:
            return {}
        total_value = sum(tp.get("value", 0) for tp in touchpoints)
        if total_value <= 0:
            even_split = 1.0 / len(touchpoints)
            return {tp["channel"]: even_split for tp in touchpoints}
        result = {}
        for tp in touchpoints:
            result[tp["channel"]] = tp.get("value", 0) / total_value
        return result


@dataclass
class MCPSurface:
    """Model Context Protocol surface for agent marketing."""
    surface_id: str
    name: str
    description: str
    tools: list[dict] = field(default_factory=list)

    @staticmethod
    def create_surface(name: str, description: str) -> MCPSurface:
        sid = hashlib.md5(name.encode()).hexdigest()[:12]
        return MCPSurface(surface_id=f"mcp-{sid}", name=name, description=description)

    def add_tool(self, tool_name: str, tool_description: str, input_schema: dict | None = None) -> None:
        if input_schema is None:
            input_schema = {"type": "object", "properties": {}}
        self.tools.append({
            "name": tool_name,
            "description": tool_description,
            "input_schema": input_schema,
        })

    @property
    def tool_count(self) -> int:
        return len(self.tools)

    def list_tools(self) -> list[str]:
        return [t["name"] for t in self.tools]

    def to_manifest(self) -> dict[str, Any]:
        return {
            "surface_id": self.surface_id,
            "name": self.name,
            "description": self.description,
            "tools": self.tools,
        }


@dataclass
class SafetyRuleEngine:
    """Safety rules for agent marketing operations."""
    rules: list[dict] = field(default_factory=list)

    @staticmethod
    def create_rule(rule_id: str, description: str, pattern: str, action: str) -> dict:
        return {
            "rule_id": rule_id,
            "description": description,
            "pattern": pattern,
            "action": action,
        }

    def add_rule(self, rule: dict) -> None:
        self.rules.append(rule)

    def check_text(self, text: str) -> list[dict]:
        violations = []
        for rule in self.rules:
            try:
                if re.search(rule["pattern"], text, re.IGNORECASE):
                    violations.append({
                        "rule_id": rule["rule_id"],
                        "description": rule["description"],
                        "action": rule["action"],
                    })
            except re.error:
                pass
        return violations

    def is_safe(self, text: str) -> bool:
        return len(self.check_text(text)) == 0

    def risk_score(self, text: str) -> float:
        violations = self.check_text(text)
        if not violations:
            return 0.0
        severity_map = {"block": 1.0, "warn": 0.5, "flag": 0.25}
        return sum(severity_map.get(v["action"], 0.5) for v in violations) / len(violations)

    @staticmethod
    def default_rules() -> list[dict]:
        return [
            SafetyRuleEngine.create_rule("r001", "No false claims", r"guaranteed|100% sure|no risk", "block"),
            SafetyRuleEngine.create_rule("r002", "No competitor mentions", r"(?i)(?:better than|superior to|beats)\s+(competitor)", "warn"),
            SafetyRuleEngine.create_rule("r003", "No missing disclosures", r"#ad|#sponsored", "warn"),
            SafetyRuleEngine.create_rule("r004", "No prohibited products", r"weapons|drugs|illegal", "block"),
        ]


@dataclass
class AgentMarketingSkill:
    """Marketing skill for AI agents."""
    skill_id: str
    name: str
    description: str
    inputs: dict[str, str] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)

    @staticmethod
    def create_skill(name: str, description: str, skill_type: str = "general") -> AgentMarketingSkill:
        sid = hashlib.md5(f"{name}:{skill_type}".encode()).hexdigest()[:12]
        return AgentMarketingSkill(
            skill_id=f"skill-{sid}",
            name=name,
            description=description,
        )

    def add_input(self, name: str, description: str, required: bool = True) -> None:
        self.inputs[name] = f"{description} (required: {required})"

    def add_output(self, name: str, description: str) -> None:
        self.outputs[name] = description

    def add_step(self, description: str) -> None:
        self.steps.append(description)

    @property
    def input_count(self) -> int:
        return len(self.inputs)

    @property
    def output_count(self) -> int:
        return len(self.outputs)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def to_manifest(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "steps": self.steps,
        }


@dataclass
class TopRankManager:
    """Unified SEO/GEO ranking manager."""
    seo: SEORanker = field(default_factory=SEORanker)
    geo: GEORanker = field(default_factory=GEORanker)
    analytics: AnalyticsTracker = field(default_factory=AnalyticsTracker)
    safety: SafetyRuleEngine = field(default_factory=SafetyRuleEngine)

    def __post_init__(self) -> None:
        for rule in SafetyRuleEngine.default_rules():
            self.safety.add_rule(rule)

    def analyze_content(self, text: str, keywords: list[str]) -> dict[str, Any]:
        seo_score = self.seo.content_score(text, keywords)
        geo_score = self.geo.ai_visibility_score(text)
        wc = self.seo.word_count(text)
        readability = self.seo.readability_score(text)
        return {
            "seo_score": seo_score,
            "geo_score": geo_score,
            "word_count": wc,
            "readability": readability,
            "overall": (seo_score + geo_score) / 2,
        }

    def audit_page(self, html_content: str, text: str, keywords: list[str]) -> dict[str, Any]:
        headings = self.seo.heading_structure(html_content)
        links = self.seo.internal_link_structure(html_content)
        alt_score = self.seo.alt_text_score(html_content)
        schema_score = self.seo.schema_markup_score(html_content)
        content = self.analyze_content(text, keywords)
        violations = self.safety.check_text(text)
        return {
            "headings": headings,
            "links": links,
            "alt_score": alt_score,
            "schema_score": schema_score,
            "content": content,
            "safety_violations": violations,
            "safe": len(violations) == 0,
        }

    def track_user_journey(self, user_id: str, events: list[tuple[str, dict | None]]) -> None:
        for event_type, metadata in events:
            self.analytics.track_event(event_type, user_id, metadata)

    def create_marketing_skill(self, name: str, description: str, inputs: list[str], outputs: list[str], steps: list[str]) -> AgentMarketingSkill:
        skill = AgentMarketingSkill.create_skill(name, description)
        for inp in inputs:
            skill.add_input(inp, inp)
        for out in outputs:
            skill.add_output(out, out)
        for step in steps:
            skill.add_step(step)
        return skill

    def rank_content(self, contents: list[tuple[str, str, list[str]]]) -> list[dict[str, Any]]:
        results = []
        for url, text, keywords in contents:
            analysis = self.analyze_content(text, keywords)
            url_score = self.seo.url_score(url)
            results.append({
                "url": url,
                "seo_score": analysis["seo_score"],
                "geo_score": analysis["geo_score"],
                "url_score": url_score,
                "overall": (analysis["overall"] + url_score) / 2,
            })
        results.sort(key=lambda x: x["overall"], reverse=True)
        return results

    def geo_optimize(self, text: str, query: str) -> dict[str, Any]:
        llm_score = self.geo.llm_friendliness(text)
        citation = self.geo.citation_density(text)
        authority = self.geo.authoritative_signals(text)
        entity = self.geo.entity_density(text)
        answer_score = self.geo.generative_answer_score(text, query)
        return {
            "llm_friendliness": llm_score,
            "citation_density": citation,
            "authority_signals": authority,
            "entity_density": entity,
            "answer_score": answer_score,
            "overall": (llm_score["score"] + answer_score) / 2,
        }

    @property
    def tracked_events(self) -> int:
        return self.analytics.event_count

    @property
    def unique_users(self) -> int:
        return self.analytics.unique_users()
