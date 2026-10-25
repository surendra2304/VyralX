"""
VyralX/app/agents/real_diagram_design.py — Real Diagram Design Engine.

Editorial diagram generation: pick a diagram type from a request, lay it out
with a real layout engine, render one self-contained HTML + SVG file in a
brand palette, and validate the result before handing it back.

Real working implementations:
- Color utilities: hex/RGB/HSL, relative luminance, WCAG contrast, palette
  derivation, contrast-safe text selection
- BrandPalette + Theme: brand tokens and the CSS they emit
- TextMeasurer: per-character width estimation and greedy line wrapping
- DiagramSpec / DiagramNode / DiagramEdge / DiagramGroup: the diagram model
- DIAGRAM_TYPES: 45 diagram types mapped to a layout engine and category
- DiagramSelector: request text -> diagram type
- Layout engines: layered (Sugiyama-lite with cycle removal, longest-path
  layering and barycentre ordering), tidy tree, sequence, quadrant, matrix,
  timeline, funnel, pyramid, venn, radial
- SvgRenderer: hairline-stroke SVG with edge routing, arrowheads and legends
- DiagramDocument: one self-contained HTML file, no external requests
- MermaidImporter: flowchart / sequenceDiagram source -> DiagramSpec
- DiagramValidator: overlaps, bounds, contrast, crossings, label overflow
- DiagramStudio: prompt -> type -> layout -> SVG/HTML -> validation report
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


# ── Colour ────────────────────────────────────────────────────────────────

@dataclass
class RGB:
    r: int
    g: int
    b: int

    def hex(self) -> str:
        return f"#{self.r:02x}{self.g:02x}{self.b:02x}"

    def as_tuple(self) -> tuple[int, int, int]:
        return (self.r, self.g, self.b)


def hex_to_rgb(value: str) -> RGB:
    raw = value.strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(c * 2 for c in raw)
    if len(raw) != 6 or not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raise ValueError(f"invalid hex colour: {value!r}")
    return RGB(int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def rgb_to_hsl(color: RGB) -> tuple[float, float, float]:
    r, g, b = color.r / 255.0, color.g / 255.0, color.b / 255.0
    high, low = max(r, g, b), min(r, g, b)
    lightness = (high + low) / 2.0
    if high == low:
        return 0.0, 0.0, lightness
    delta = high - low
    saturation = delta / (2.0 - high - low) if lightness > 0.5 else delta / (high + low)
    if high == r:
        hue = ((g - b) / delta) % 6.0
    elif high == g:
        hue = (b - r) / delta + 2.0
    else:
        hue = (r - g) / delta + 4.0
    return (hue * 60.0) % 360.0, saturation, lightness


def hsl_to_rgb(hue: float, saturation: float, lightness: float) -> RGB:
    hue = hue % 360.0
    saturation = min(max(saturation, 0.0), 1.0)
    lightness = min(max(lightness, 0.0), 1.0)
    c = (1 - abs(2 * lightness - 1)) * saturation
    h_prime = hue / 60.0
    x = c * (1 - abs(h_prime % 2 - 1))
    m = lightness - c / 2.0
    if h_prime < 1:
        r, g, b = c, x, 0.0
    elif h_prime < 2:
        r, g, b = x, c, 0.0
    elif h_prime < 3:
        r, g, b = 0.0, c, x
    elif h_prime < 4:
        r, g, b = 0.0, x, c
    elif h_prime < 5:
        r, g, b = x, 0.0, c
    else:
        r, g, b = c, 0.0, x
    return RGB(
        int(round((r + m) * 255)),
        int(round((g + m) * 255)),
        int(round((b + m) * 255)),
    )


def _channel_luminance(channel: int) -> float:
    value = channel / 255.0
    return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(color: str | RGB) -> float:
    rgb = hex_to_rgb(color) if isinstance(color, str) else color
    return (
        0.2126 * _channel_luminance(rgb.r)
        + 0.7152 * _channel_luminance(rgb.g)
        + 0.0722 * _channel_luminance(rgb.b)
    )


def contrast_ratio(foreground: str | RGB, background: str | RGB) -> float:
    """WCAG 2.x contrast ratio, 1.0 (none) to 21.0 (black on white)."""
    a = relative_luminance(foreground)
    b = relative_luminance(background)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def mix(color_a: str, color_b: str, amount: float = 0.5) -> str:
    """Linear sRGB mix; amount=0 returns a, amount=1 returns b."""
    a, b = hex_to_rgb(color_a), hex_to_rgb(color_b)
    t = min(max(amount, 0.0), 1.0)
    return RGB(
        int(round(a.r + (b.r - a.r) * t)),
        int(round(a.g + (b.g - a.g) * t)),
        int(round(a.b + (b.b - a.b) * t)),
    ).hex()


def lighten(color: str, amount: float = 0.2) -> str:
    hue, sat, light = rgb_to_hsl(hex_to_rgb(color))
    return hsl_to_rgb(hue, sat, min(1.0, light + amount)).hex()


def darken(color: str, amount: float = 0.2) -> str:
    hue, sat, light = rgb_to_hsl(hex_to_rgb(color))
    return hsl_to_rgb(hue, sat, max(0.0, light - amount)).hex()


def rotate_hue(color: str, degrees: float, lightness: float | None = None) -> str:
    hue, sat, light = rgb_to_hsl(hex_to_rgb(color))
    return hsl_to_rgb(hue + degrees, sat, light if lightness is None else lightness).hex()


def readable_text_on(background: str, light: str = "#fdfbf7", dark: str = "#161412") -> str:
    """Pick whichever candidate carries more contrast on this background."""
    return (
        light
        if contrast_ratio(light, background) >= contrast_ratio(dark, background)
        else dark
    )


def ensure_contrast(
    foreground: str, background: str, minimum: float = 4.5, steps: int = 24,
) -> str:
    """Push a foreground towards black or white until it clears ``minimum``."""
    if contrast_ratio(foreground, background) >= minimum:
        return foreground
    target = "#000000" if relative_luminance(background) > 0.4 else "#ffffff"
    best = foreground
    for i in range(1, steps + 1):
        candidate = mix(foreground, target, i / steps)
        best = candidate
        if contrast_ratio(candidate, background) >= minimum:
            return candidate
    return best


# ── Theme ─────────────────────────────────────────────────────────────────

@dataclass
class BrandPalette:
    """A brand palette derived from one seed colour."""

    seed: str
    name: str = "brand"
    ink: str = ""
    paper: str = ""
    muted: str = ""
    line: str = ""
    accent: str = ""
    surface: str = ""

    @classmethod
    def from_seed(cls, seed: str, name: str = "brand", paper: str = "#fdfbf7") -> "BrandPalette":
        seed = seed if seed.startswith("#") else f"#{seed}"
        hue, sat, light = rgb_to_hsl(hex_to_rgb(seed))
        primary = hsl_to_rgb(hue, max(0.35, min(0.85, sat)), max(0.30, min(0.55, light))).hex()
        ink = hsl_to_rgb(hue, min(0.18, sat * 0.3), 0.10).hex()
        accent = hsl_to_rgb(hue + 152.0, 0.62, 0.44).hex()
        muted = hsl_to_rgb(hue, 0.10, 0.44).hex()
        return cls(
            seed=primary,
            name=name,
            ink=ink,
            paper=paper,
            muted=ensure_contrast(muted, paper, 4.5),
            line=mix(ink, paper, 0.82),
            accent=accent,
            surface=mix(paper, primary, 0.07),
        )

    def tints(self, count: int = 5) -> list[str]:
        """Evenly spaced tints from surface to primary."""
        return [mix(self.surface, self.seed, (i + 1) / count) for i in range(count)]

    def categorical(self, count: int = 6) -> list[str]:
        """Categorical series derived by hue rotation, all contrast-safe on paper."""
        out = []
        for i in range(count):
            hue, sat, light = rgb_to_hsl(hex_to_rgb(self.seed))
            color = hsl_to_rgb(hue + i * (360.0 / max(1, count)), sat, min(0.62, light + 0.08)).hex()
            out.append(ensure_contrast(color, self.paper, 3.0))
        return out

    def as_dict(self) -> dict[str, str]:
        return {
            "seed": self.seed, "ink": self.ink, "paper": self.paper,
            "muted": self.muted, "line": self.line, "accent": self.accent,
            "surface": self.surface,
        }


@dataclass
class Theme:
    """Typography, spacing and colour tokens for the rendered document."""

    palette: BrandPalette
    font_stack: str = "'Inter', 'Helvetica Neue', Arial, sans-serif"
    mono_stack: str = "'IBM Plex Mono', ui-monospace, monospace"
    base_size: int = 14
    title_size: int = 30
    kicker_size: int = 10
    spacing: float = 24.0
    radius: float = 6.0
    stroke: float = 1.5

    def css(self) -> str:
        p = self.palette
        return (
            ":root{"
            f"--ink:{p.ink};--paper:{p.paper};--muted:{p.muted};"
            f"--line:{p.line};--surface:{p.surface};--accent:{p.accent};"
            f"--brand:{p.seed};--radius:{self.radius}px;"
            "}"
            "html,body{margin:0;padding:0;background:var(--paper);color:var(--ink);"
            f"font-family:{self.font_stack};font-size:{self.base_size}px;"
            "-webkit-font-smoothing:antialiased;}"
            ".sheet{max-width:1100px;margin:0 auto;padding:56px 40px 72px;}"
            ".kicker{font-size:" + str(self.kicker_size) + "px;letter-spacing:.14em;"
            "text-transform:uppercase;color:var(--muted);margin:0 0 10px;}"
            "h1{font-size:" + str(self.title_size) + "px;line-height:1.15;margin:0 0 8px;"
            "font-weight:640;letter-spacing:-.015em;}"
            ".deck{color:var(--muted);margin:0 0 28px;max-width:62ch;}"
            ".canvas{border-top:1px solid var(--line);padding-top:24px;overflow-x:auto;}"
            ".foot{margin-top:32px;padding-top:16px;border-top:1px solid var(--line);"
            "color:var(--muted);font-size:12px;display:flex;justify-content:space-between;}"
            "svg{max-width:100%;height:auto;display:block;}"
            ".legend{display:flex;gap:18px;flex-wrap:wrap;margin-top:20px;font-size:12px;"
            "color:var(--muted);}"
            ".legend span{display:inline-flex;align-items:center;gap:7px;}"
            ".swatch{width:11px;height:11px;border-radius:2px;display:inline-block;}"
            "text{font-family:" + self.font_stack + ";}"
        )

    def esc(self) -> str:
        return (
            f"<style>{self.css()}</style>"
        )


# ── Text measurement ──────────────────────────────────────────────────────

NARROW = set("iljtfr.,;:'|!()[]{}")
WIDE = set("mwMW@%&")
UPPER = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ")


class TextMeasurer:
    """Estimate rendered text width without a font engine, and wrap to width."""

    def __init__(self, average_ratio: float = 0.53) -> None:
        self.average_ratio = average_ratio

    def char_ratio(self, char: str) -> float:
        if char in NARROW:
            return 0.33
        if char in WIDE:
            return 0.92
        if char.isdigit():
            return 0.56
        if char in UPPER:
            return 0.66
        if char == " ":
            return 0.28
        return self.average_ratio

    def width(self, text: str, size: int) -> float:
        return sum(self.char_ratio(c) for c in text) * size

    def wrap(self, text: str, max_width: float, size: int) -> list[str]:
        words = (text or "").split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if self.width(candidate, size) <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines


# ── Diagram model ─────────────────────────────────────────────────────────

@dataclass
class DiagramNode:
    """One box / participant / point in a diagram."""

    node_id: str
    label: str
    kind: str = "step"          # step | decision | data | actor | note | metric
    group: str = ""
    weight: float = 1.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagramEdge:
    """A directed connection between two nodes."""

    source: str
    target: str
    label: str = ""
    style: str = "solid"        # solid | dashed | dotted
    kind: str = "flow"


@dataclass
class DiagramGroup:
    """A labelled band that contains several nodes."""

    group_id: str
    label: str
    node_ids: list[str] = field(default_factory=list)


@dataclass
class DiagramSpec:
    """The complete, layout-independent description of a diagram."""

    title: str
    diagram_type: str = "flowchart"
    subtitle: str = ""
    kicker: str = "DIAGRAM"
    nodes: list[DiagramNode] = field(default_factory=list)
    edges: list[DiagramEdge] = field(default_factory=list)
    groups: list[DiagramGroup] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def node(self, node_id: str) -> DiagramNode | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def node_ids(self) -> list[str]:
        return [n.node_id for n in self.nodes]

    def group_for(self, node_id: str) -> str:
        node = self.node(node_id)
        if node and node.group:
            return node.group
        for group in self.groups:
            if node_id in group.node_ids:
                return group.group_id
        return ""

    def validate_structure(self) -> list[str]:
        problems: list[str] = []
        ids = self.node_ids()
        if len(ids) != len(set(ids)):
            problems.append("duplicate node ids")
        if not self.nodes:
            problems.append("no nodes")
        for edge in self.edges:
            if edge.source not in ids:
                problems.append(f"edge source missing: {edge.source}")
            if edge.target not in ids:
                problems.append(f"edge target missing: {edge.target}")
        return problems

    def kinds(self) -> list[str]:
        seen: list[str] = []
        for node in self.nodes:
            if node.kind not in seen:
                seen.append(node.kind)
        return seen


# ── Diagram type catalogue ────────────────────────────────────────────────

@dataclass
class DiagramType:
    """A supported diagram type and the engine that lays it out."""

    type_id: str
    title: str
    category: str
    layout: str
    keywords: list[str] = field(default_factory=list)
    use_when: str = ""

    def score(self, request: str) -> float:
        terms = set(re.findall(r"[a-z0-9]+", request.lower()))
        if not terms:
            return 0.0
        hay = set(self.keywords) | set(re.findall(r"[a-z0-9]+", self.title.lower()))
        hay |= set(re.findall(r"[a-z0-9]+", self.type_id.replace("-", " ")))
        hay |= set(re.findall(r"[a-z0-9]+", self.category.lower()))
        overlap = terms & hay
        if not overlap:
            return 0.0
        return round(len(overlap) / math.sqrt(len(hay) + 1), 4)


def _type(type_id: str, title: str, category: str, layout: str,
          keywords: list[str], use_when: str = "") -> DiagramType:
    return DiagramType(type_id, title, category, layout, keywords, use_when)


DIAGRAM_TYPES: list[DiagramType] = [
    _type("flowchart", "Flowchart", "process", "layered",
          ["flow", "process", "steps", "workflow", "sequence", "pipeline"],
          "an ordered process with branches"),
    _type("process-map", "Process Map", "process", "layered",
          ["process", "map", "handoff", "operations"], "cross-team process steps"),
    _type("swimlane", "Swimlane", "process", "layered",
          ["swimlane", "lane", "owner", "team", "responsibility"], "who does what"),
    _type("bpmn", "BPMN", "process", "layered",
          ["bpmn", "business", "gateway", "event"], "formal business processes"),
    _type("decision-tree", "Decision Tree", "process", "tree",
          ["decision", "tree", "branch", "if", "choose"], "branching choices"),
    _type("state-machine", "State Machine", "process", "layered",
          ["state", "machine", "transition", "status"], "lifecycle states"),
    _type("data-flow", "Data Flow Diagram", "architecture", "layered",
          ["data", "flow", "dfd", "store", "transform"], "how data moves"),
    _type("architecture", "Architecture Diagram", "architecture", "layered",
          ["architecture", "service", "backend", "frontend", "database", "cache",
           "system", "infra"], "system components and calls"),
    _type("layer-stack", "Layer Stack", "architecture", "layered",
          ["layer", "stack", "tier", "abstraction"], "abstraction layers"),
    _type("network-topology", "Network Topology", "architecture", "radial",
          ["network", "topology", "nodes", "mesh", "hub"], "connected hosts"),
    _type("ecosystem", "Ecosystem Map", "architecture", "radial",
          ["ecosystem", "partners", "actors", "market"], "many-to-many actors"),
    _type("capability-map", "Capability Map", "architecture", "matrix",
          ["capability", "map", "maturity", "grid"], "capabilities by domain"),
    _type("er-diagram", "Entity Relationship", "architecture", "matrix",
          ["entity", "relationship", "erd", "schema", "table"], "data schema"),
    _type("class-diagram", "Class Diagram", "architecture", "layered",
          ["class", "object", "inheritance", "uml"], "object models"),
    _type("sitemap", "Sitemap", "architecture", "tree",
          ["sitemap", "pages", "hierarchy", "navigation", "site"], "page hierarchy"),
    _type("org-chart", "Org Chart", "hierarchy", "tree",
          ["org", "chart", "report", "team", "manager", "structure"], "reporting lines"),
    _type("hierarchy", "Hierarchy", "hierarchy", "tree",
          ["hierarchy", "parent", "child", "levels"], "nesting"),
    _type("mind-map", "Mind Map", "hierarchy", "radial",
          ["mind", "map", "brainstorm", "ideas", "theme"], "ideas around a theme"),
    _type("breakdown", "Work Breakdown", "hierarchy", "tree",
          ["breakdown", "work", "wbs", "tasks", "deliverable"], "task decomposition"),
    _type("sequence", "Sequence Diagram", "interaction", "sequence",
          ["sequence", "message", "call", "token", "refresh", "request", "api",
           "interaction"], "messages over time"),
    _type("user-journey", "User Journey", "interaction", "timeline",
          ["journey", "user", "experience", "touchpoint", "emotion"], "user steps"),
    _type("storyboard", "Storyboard", "interaction", "timeline",
          ["storyboard", "scenes", "frames", "narrative"], "scene-by-scene"),
    _type("flow-messages", "Message Flow", "interaction", "sequence",
          ["messages", "protocol", "handshake", "events"], "protocol exchange"),
    _type("quadrant", "Quadrant", "comparison", "quadrant",
          ["quadrant", "impact", "effort", "priority", "matrix", "position"],
          "two-axis positioning"),
    _type("priority-matrix", "Priority Matrix", "comparison", "quadrant",
          ["priority", "urgent", "important", "eisenhower"], "what to do next"),
    _type("swot", "SWOT", "comparison", "quadrant",
          ["swot", "strengths", "weaknesses", "opportunities", "threats"], "strategy scan"),
    _type("risk-matrix", "Risk Matrix", "comparison", "matrix",
          ["risk", "likelihood", "severity", "heatmap"], "risk scoring"),
    _type("comparison", "Comparison", "comparison", "matrix",
          ["compare", "versus", "options", "tradeoff", "pros", "cons"], "side-by-side options"),
    _type("before-after", "Before / After", "comparison", "matrix",
          ["before", "after", "change", "delta"], "state change"),
    _type("heatmap", "Heatmap", "data", "matrix",
          ["heatmap", "density", "colour", "grid", "values"], "values on a grid"),
    _type("bar-chart", "Bar Chart", "data", "matrix",
          ["bar", "chart", "count", "compare", "values"], "comparable counts"),
    _type("scatter", "Scatter Plot", "data", "quadrant",
          ["scatter", "plot", "correlation", "points", "x", "y"], "two variables"),
    _type("treemap", "Treemap", "data", "matrix",
          ["treemap", "area", "proportion", "share", "nested"], "part-to-whole"),
    _type("sankey", "Sankey", "data", "layered",
          ["sankey", "flow", "volume", "distribution", "split"], "quantities moving"),
    _type("funnel", "Funnel", "data", "funnel",
          ["funnel", "conversion", "dropoff", "stages", "signup"], "stage conversion"),
    _type("pyramid", "Pyramid", "data", "pyramid",
          ["pyramid", "levels", "foundation", "maslow", "hierarchy"], "stacked levels"),
    _type("venn", "Venn Diagram", "comparison", "venn",
          ["venn", "overlap", "intersection", "sets", "common"], "shared traits"),
    _type("timeline", "Timeline", "time", "timeline",
          ["timeline", "dates", "history", "milestones", "when"], "events in order"),
    _type("roadmap", "Roadmap", "time", "timeline",
          ["roadmap", "quarters", "phases", "plan", "release"], "planned work"),
    _type("gantt", "Gantt", "time", "timeline",
          ["gantt", "schedule", "duration", "tasks", "weeks"], "task durations"),
    _type("milestones", "Milestones", "time", "timeline",
          ["milestones", "checkpoints", "gates", "deadline"], "key checkpoints"),
    _type("cycle", "Cycle", "process", "radial",
          ["cycle", "loop", "iterate", "feedback", "sprint"], "repeating stages"),
    _type("flywheel", "Flywheel", "process", "radial",
          ["flywheel", "growth", "momentum", "compounding"], "self-reinforcing loops"),
    _type("fishbone", "Cause & Effect", "process", "radial",
          ["fishbone", "cause", "effect", "root", "ishikawa"], "root causes"),
    _type("kanban", "Kanban Board", "process", "matrix",
          ["kanban", "board", "columns", "backlog", "doing", "done"], "work in progress"),
    _type("value-chain", "Value Chain", "process", "layered",
          ["value", "chain", "margin", "activities", "porter"], "activity chain"),
]

TYPE_INDEX: dict[str, DiagramType] = {t.type_id: t for t in DIAGRAM_TYPES}

class DiagramSelector:
    """Choose the most appropriate diagram type for a natural-language request."""

    def __init__(self, types: list[DiagramType] | None = None) -> None:
        self.types = types or DIAGRAM_TYPES

    def rank(self, request: str, limit: int = 5) -> list[tuple[DiagramType, float]]:
        scored = [(t, t.score(request)) for t in self.types]
        scored = [(t, s) for t, s in scored if s > 0]
        scored.sort(key=lambda pair: (-pair[1], pair[0].type_id))
        return scored[:limit]

    def select(self, request: str, fallback: str = "flowchart") -> DiagramType:
        ranked = self.rank(request, limit=1)
        if ranked:
            return ranked[0][0]
        return TYPE_INDEX.get(fallback, DIAGRAM_TYPES[0])

    def explain(self, request: str) -> dict[str, Any]:
        chosen = self.select(request)
        return {
            "type": chosen.type_id,
            "title": chosen.title,
            "category": chosen.category,
            "layout": chosen.layout,
            "use_when": chosen.use_when,
            "alternatives": [
                {"type": t.type_id, "score": s} for t, s in self.rank(request, limit=4)[1:]
            ],
        }


# ── Layout geometry ───────────────────────────────────────────────────────

@dataclass
class Box:
    """An axis-aligned box in diagram coordinates."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    def intersection_area(self, other: "Box") -> float:
        dx = min(self.right, other.right) - max(self.x, other.x)
        dy = min(self.bottom, other.bottom) - max(self.y, other.y)
        return dx * dy if dx > 0 and dy > 0 else 0.0

    def overlaps(self, other: "Box") -> bool:
        return self.intersection_area(other) > 0.01

    def inflate(self, amount: float) -> "Box":
        return Box(self.x - amount, self.y - amount, self.width + 2 * amount, self.height + 2 * amount)

    def as_dict(self) -> dict[str, float]:
        return {
            "x": round(self.x, 2), "y": round(self.y, 2),
            "width": round(self.width, 2), "height": round(self.height, 2),
        }


@dataclass
class EdgeRoute:
    """A routed polyline for one edge."""

    edge: DiagramEdge
    points: list[tuple[float, float]]
    reversed: bool = False
    label_position: tuple[float, float] = (0.0, 0.0)

    @property
    def length(self) -> float:
        return sum(
            math.dist(self.points[i], self.points[i + 1])
            for i in range(len(self.points) - 1)
        )

    def segments(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        return [(self.points[i], self.points[i + 1]) for i in range(len(self.points) - 1)]


@dataclass
class LayoutResult:
    """Everything the renderer needs after layout."""

    boxes: dict[str, Box]
    routes: list[EdgeRoute]
    width: float
    height: float
    labels: dict[str, list[str]] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)

    def overlaps(self, tolerance: float = 0.5) -> list[tuple[str, str, float]]:
        names = sorted(self.boxes)
        found: list[tuple[str, str, float]] = []
        for i, a in enumerate(names):
            for b in names[i + 1:]:
                area = self.boxes[a].intersection_area(self.boxes[b])
                if area > tolerance:
                    found.append((a, b, round(area, 2)))
        return found


def _segments_intersect(
    p1: tuple[float, float], p2: tuple[float, float],
    p3: tuple[float, float], p4: tuple[float, float],
) -> bool:
    def orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> float:
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

    d1 = orientation(p3, p4, p1)
    d2 = orientation(p3, p4, p2)
    d3 = orientation(p1, p2, p3)
    d4 = orientation(p1, p2, p4)
    if ((d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0)) and (
        (d3 > 0 and d4 < 0) or (d3 < 0 and d4 > 0)
    ):
        return True
    return False


# ── Layout engines ────────────────────────────────────────────────────────

class LayoutEngine:
    """Base class for the layout engines."""

    margin: float = 48.0
    h_gap: float = 56.0
    v_gap: float = 64.0
    node_min_width: float = 128.0
    node_max_width: float = 240.0
    padding_x: float = 16.0
    padding_y: float = 13.0
    line_height: float = 1.35

    def __init__(self, theme: Theme, measurer: TextMeasurer | None = None) -> None:
        self.theme = theme
        self.measurer = measurer or TextMeasurer()
        self.font_size = theme.base_size + 1

    # ── helpers ──────────────────────────────────────────────────────

    def label_lines(self, node: DiagramNode) -> list[str]:
        return self.measurer.wrap(
            node.label, self.node_max_width - 2 * self.padding_x, self.font_size,
        )

    def node_size(self, node: DiagramNode) -> tuple[float, float, list[str]]:
        lines = self.label_lines(node)
        widest = max(self.measurer.width(line, self.font_size) for line in lines)
        width = min(self.node_max_width, max(self.node_min_width, widest + 2 * self.padding_x))
        height = len(lines) * self.font_size * self.line_height + 2 * self.padding_y
        if node.kind == "decision":
            height += 6.0
        return width, height, lines

    def layout(self, spec: DiagramSpec) -> LayoutResult:  # pragma: no cover - interface
        raise NotImplementedError


class LayeredLayout(LayoutEngine):
    """Sugiyama-lite: cycle removal, longest-path layering, barycentre ordering."""

    def __init__(self, theme: Theme, direction: str = "TD", **kwargs: Any) -> None:
        super().__init__(theme, **kwargs)
        self.direction = direction

    # ── graph preparation ────────────────────────────────────────────

    def _prepare(self, spec: DiagramSpec) -> tuple[dict[str, list[str]], set[int], dict[int, int]]:
        ids = spec.node_ids()
        outgoing: dict[str, list[tuple[int, DiagramEdge]]] = defaultdict(list)
        for index, edge in enumerate(spec.edges):
            if edge.source in ids and edge.target in ids:
                outgoing[edge.source].append((index, edge))

        # DFS back-edge detection for cycle removal.
        state: dict[str, int] = {}
        back_edges: set[int] = set()

        def visit(node_id: str) -> None:
            state[node_id] = 1
            for index, edge in outgoing.get(node_id, []):
                target = edge.target
                if state.get(target, 0) == 1:
                    back_edges.add(index)
                elif state.get(target, 0) == 0:
                    visit(target)
            state[node_id] = 2

        for node_id in ids:
            if state.get(node_id, 0) == 0:
                visit(node_id)

        dag: dict[str, list[str]] = {node_id: [] for node_id in ids}
        indegree: dict[str, int] = {node_id: 0 for node_id in ids}
        for index, edge in enumerate(spec.edges):
            if edge.source not in ids or edge.target not in ids:
                continue
            source, target = (
                (edge.target, edge.source) if index in back_edges else (edge.source, edge.target)
            )
            if target not in dag[source]:
                dag[source].append(target)
                indegree[target] += 1
        return dag, back_edges, indegree

    def _layers(
        self, ids: list[str], dag: dict[str, list[str]], indegree: dict[str, int],
    ) -> dict[str, int]:
        layer = {node_id: 0 for node_id in ids}
        remaining = dict(indegree)
        queue = [node_id for node_id in ids if remaining[node_id] == 0]
        while queue:
            current = queue.pop(0)
            for target in dag[current]:
                layer[target] = max(layer[target], layer[current] + 1)
                remaining[target] -= 1
                if remaining[target] == 0:
                    queue.append(target)
        return layer

    def _order(
        self, ids: list[str], layers: dict[int, list[str]], dag: dict[str, list[str]],
    ) -> None:
        predecessors: dict[str, list[str]] = defaultdict(list)
        for source, targets in dag.items():
            for target in targets:
                predecessors[target].append(source)
        keys = sorted(layers)
        for _ in range(3):
            for key in keys[1:]:
                previous = layers[keys[keys.index(key) - 1]]
                position = {node_id: i for i, node_id in enumerate(previous)}
                layers[key].sort(
                    key=lambda node_id: (
                        sum(position.get(p, len(previous)) for p in predecessors[node_id])
                        / max(1, len(predecessors[node_id])),
                        node_id,
                    )
                )

    # ── coordinates ──────────────────────────────────────────────────

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        ids = spec.node_ids()
        measured = {node_id: self.node_size(spec.node(node_id)) for node_id in ids}
        labels = {node_id: measured[node_id][2] for node_id in ids}
        sizes = {node_id: (measured[node_id][0], measured[node_id][1]) for node_id in ids}
        sizes = {node_id: (sizes[node_id][0], sizes[node_id][1]) for node_id in ids}
        if not ids:
            return LayoutResult({}, [], 640.0, 300.0, {}, {"empty": True})

        dag, back_edges, indegree = self._prepare(spec)
        layer_of = self._layers(ids, dag, indegree)
        layers: dict[int, list[str]] = defaultdict(list)
        for node_id in ids:
            layers[layer_of[node_id]].append(node_id)
        self._order(ids, layers, dag)

        boxes: dict[str, Box] = {}
        if self.direction == "LR":
            x_cursor = self.margin
            for depth in sorted(layers):
                members = layers[depth]
                total_height = sum(sizes[n][1] for n in members) + self.v_gap * (len(members) - 1)
                y = self.margin
                column_width = max(sizes[n][0] for n in members)
                for node_id in members:
                    width, height = sizes[node_id]
                    boxes[node_id] = Box(x_cursor + (column_width - width) / 2.0, y, width, height)
                    y += height + self.v_gap
                x_cursor += column_width + self.h_gap * 1.4
            width = x_cursor - self.h_gap * 1.4 + self.margin
            height = max(
                (box.bottom for box in boxes.values()), default=self.margin
            ) + self.margin
        else:
            y_cursor = self.margin
            row_widths: dict[int, float] = {}
            for depth in sorted(layers):
                members = layers[depth]
                total_width = sum(sizes[n][0] for n in members) + self.h_gap * (len(members) - 1)
                row_widths[depth] = total_width
            widest = max(row_widths.values()) if row_widths else 0.0
            for depth in sorted(layers):
                members = layers[depth]
                x = self.margin + (widest - row_widths[depth]) / 2.0
                layer_height = max(sizes[n][1] for n in members)
                for node_id in members:
                    node_width, node_height = sizes[node_id]
                    boxes[node_id] = Box(
                        x, y_cursor + (layer_height - node_height) / 2.0, node_width, node_height,
                    )
                    x += node_width + self.h_gap
                y_cursor += layer_height + self.v_gap
            width = widest + 2 * self.margin
            height = y_cursor - self.v_gap + self.margin

        routes = [
            self._route(edge, index, boxes, back_edges)
            for index, edge in enumerate(spec.edges)
            if edge.source in boxes and edge.target in boxes
        ]
        return LayoutResult(
            boxes=boxes, routes=routes, width=max(width, 320.0), height=max(height, 220.0),
            labels=labels,
            extras={
                "layers": {str(depth): members for depth, members in layers.items()},
                "direction": self.direction,
            },
        )

    def _route(
        self, edge: DiagramEdge, index: int, boxes: dict[str, Box], back_edges: set[int],
    ) -> EdgeRoute:
        source_box, target_box = boxes[edge.source], boxes[edge.target]
        s_cx, s_cy = source_box.center
        t_cx, t_cy = target_box.center
        points: list[tuple[float, float]]
        if self.direction == "LR":
            sx = source_box.right if target_box.x >= source_box.x else source_box.x
            tx = target_box.x if target_box.x >= source_box.x else target_box.right
            if target_box.x > source_box.right:
                mid = (sx + tx) / 2.0
                points = [(sx, s_cy), (mid, s_cy), (mid, t_cy), (tx, t_cy)]
            else:
                y = min(source_box.y, target_box.y) - 22.0
                points = [(s_cx, source_box.y), (s_cx, y), (t_cx, y), (t_cx, target_box.y)]
        else:
            if target_box.y > source_box.bottom:
                sy = source_box.bottom
                ty = target_box.y
                mid = (sy + ty) / 2.0
                points = [(s_cx, sy), (s_cx, mid), (t_cx, mid), (t_cx, ty)]
            elif target_box.y < source_box.y:
                side = max(source_box.right, target_box.right) + 26.0
                points = [(source_box.right, s_cy), (side, s_cy), (side, t_cy),
                          (target_box.right, t_cy)]
            else:
                sy = source_box.bottom
                points = [(s_cx, sy), (s_cx, sy + 26.0),
                          (t_cx, sy + 26.0), (t_cx, target_box.y)]
        mid_point = points[len(points) // 2]
        label_position = (
            (mid_point[0], mid_point[1] - 6.0) if self.direction == "TD"
            else (mid_point[0], mid_point[1] - 8.0)
        )
        return EdgeRoute(edge, points, reversed=index in back_edges, label_position=label_position)


class TreeLayout(LayoutEngine):
    """Tidy top-down tree: subtree widths computed bottom-up, parents centred."""

    def __init__(self, theme: Theme, **kwargs: Any) -> None:
        super().__init__(theme, **kwargs)
        self.level_gap = 72.0
        self.sibling_gap = 32.0

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        ids = spec.node_ids()
        if not ids:
            return LayoutResult({}, [], 640.0, 300.0, {}, {"empty": True})
        sizes = {}
        labels = {}
        for node_id in ids:
            width, height, lines = self.node_size(spec.node(node_id))
            sizes[node_id] = (width, height)
            labels[node_id] = lines

        children: dict[str, list[str]] = {node_id: [] for node_id in ids}
        has_parent: set[str] = set()
        for edge in spec.edges:
            if edge.source in children and edge.target in children:
                if edge.target not in children[edge.source]:
                    children[edge.source].append(edge.target)
                    has_parent.add(edge.target)
        roots = [node_id for node_id in ids if node_id not in has_parent]
        root = spec.meta.get("root")
        if root in children:
            roots = [root] + [r for r in roots if r != root]
        if not roots:
            roots = [ids[0]]

        boxes: dict[str, Box] = {}
        subtree_width_cached: dict[str, float] = {}
        in_progress: set[str] = set()

        def subtree_width(node_id: str) -> float:
            """Memoised subtree width, cycle-safe."""
            if node_id in subtree_width_cached:
                return subtree_width_cached[node_id]
            if node_id in in_progress:
                return sizes[node_id][0]
            in_progress.add(node_id)
            kids = [c for c in children[node_id] if c not in in_progress]
            own = sizes[node_id][0]
            if kids:
                total = sum(subtree_width(k) for k in kids) + self.sibling_gap * (len(kids) - 1)
                width = max(own, total)
            else:
                width = own
            in_progress.discard(node_id)
            subtree_width_cached[node_id] = width
            return width

        placed: set[str] = set()

        def place(node_id: str, left: float, depth: int) -> None:
            if node_id in placed:
                return
            placed.add(node_id)
            node_width, node_height = sizes[node_id]
            kids = [c for c in children[node_id] if c not in placed]
            kid_total = (
                sum(subtree_width(k) for k in kids) + self.sibling_gap * (len(kids) - 1)
                if kids else 0.0
            )
            block = max(node_width, kid_total)
            center = left + block / 2.0
            boxes[node_id] = Box(
                center - node_width / 2.0, self.margin + depth * self.level_gap,
                node_width, node_height,
            )
            cursor = left + max(0.0, (block - kid_total) / 2.0)
            for kid in kids:
                place(kid, cursor, depth + 1)
                cursor += subtree_width_cached.get(kid, sizes[kid][0]) + self.sibling_gap

        cursor = self.margin
        for root_id in roots:
            if root_id in placed:
                continue
            place(root_id, cursor, 0)
            cursor += subtree_width(root_id) + self.h_gap
        for node_id in ids:            # disconnected nodes fall back to a row
            if node_id in placed:
                continue
            width, height = sizes[node_id]
            boxes[node_id] = Box(cursor, self.margin, width, height)
            placed.add(node_id)
            cursor += width + self.sibling_gap

        routes = [self._route(edge, boxes) for edge in spec.edges
                  if edge.source in boxes and edge.target in boxes]
        width = max((box.right for box in boxes.values()), default=0.0) + self.margin
        height = max((box.bottom for box in boxes.values()), default=0.0) + self.margin
        return LayoutResult(
            boxes=boxes, routes=routes, width=max(width, 320.0), height=max(height, 220.0),
            labels=labels, extras={"roots": roots},
        )

    @staticmethod
    def _depth(boxes: dict[str, Box], root: str, children: dict[str, list[str]]) -> int:
        best = 0
        stack = [(root, 0)]
        while stack:
            node_id, depth = stack.pop()
            best = max(best, depth)
            for kid in children.get(node_id, []):
                stack.append((kid, depth + 1))
        return best

    def _route(self, edge: DiagramEdge, boxes: dict[str, Box]) -> EdgeRoute:
        s, t = boxes[edge.source], boxes[edge.target]
        s_cx, t_cx = s.center[0], t.center[0]
        if t.y >= s.bottom:
            mid = (s.bottom + t.y) / 2.0
            points = [(s_cx, s.bottom), (s_cx, mid), (t_cx, mid), (t_cx, t.y)]
        else:
            points = [(s_cx, s.bottom), (s_cx, s.bottom + 24), (t_cx, s.bottom + 24), (t_cx, t.bottom)]
        return EdgeRoute(edge, points, label_position=(points[1][0], points[1][1] - 6.0))


class SequenceLayout(LayoutEngine):
    """Participants on lifelines, messages ordered top to bottom."""

    def __init__(self, theme: Theme, **kwargs: Any) -> None:
        super().__init__(theme, **kwargs)
        self.message_gap = 46.0
        self.lifeline_top = 96.0

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        ids = spec.node_ids()
        if not ids:
            return LayoutResult({}, [], 640.0, 300.0, {}, {"empty": True})
        measured = {node_id: self.node_size(spec.node(node_id)) for node_id in ids}
        labels = {node_id: measured[node_id][2] for node_id in ids}
        sizes = {node_id: (measured[node_id][0], measured[node_id][1]) for node_id in ids}

        participant_width = max(140.0, max(s[0] for s in sizes.values()))
        spacing = participant_width + 52.0
        boxes: dict[str, Box] = {}
        centers: dict[str, float] = {}
        for index, node_id in enumerate(ids):
            width, height = sizes[node_id][0], sizes[node_id][1]
            x = self.margin + index * spacing + (participant_width - width) / 2.0
            boxes[node_id] = Box(x, self.margin, width, height)
            centers[node_id] = self.margin + index * spacing + participant_width / 2.0

        messages = [edge for edge in spec.edges if edge.source in centers and edge.target in centers]
        routes: list[EdgeRoute] = []
        message_rows: list[dict[str, Any]] = []
        y = self.margin + boxes[ids[0]].height + self.message_gap
        for edge in messages:
            sx, tx = centers[edge.source], centers[edge.target]
            points = [(sx, y), (tx, y)]
            routes.append(EdgeRoute(edge, points, label_position=((sx + tx) / 2.0, y - 9.0)))
            message_rows.append({"y": y, "label": edge.label, "source": edge.source,
                                 "target": edge.target, "self": edge.source == edge.target})
            if edge.source == edge.target:
                routes[-1].points = [(sx, y), (sx + 46, y), (sx + 46, y + 22), (sx, y + 22)]
                routes[-1].label_position = (sx + 52, y + 4)
            y += self.message_gap

        bottom = y + 24.0
        lifelines = [
            {"x": centers[node_id], "y1": boxes[node_id].bottom + 8.0, "y2": bottom}
            for node_id in ids
        ]
        width = self.margin * 2 + participant_width + spacing * (len(ids) - 1)
        return LayoutResult(
            boxes=boxes, routes=routes, width=width, height=bottom + self.margin, labels=labels,
            extras={"lifelines": lifelines, "messages": message_rows},
        )


class QuadrantLayout(LayoutEngine):
    """Two-axis positioning from node meta x/y in [0, 1]."""

    def __init__(self, theme: Theme, **kwargs: Any) -> None:
        super().__init__(theme, **kwargs)
        self.plot_width = 620.0
        self.plot_height = 440.0

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        ids = spec.node_ids()
        if not ids:
            return LayoutResult({}, [], 640.0, 300.0, {}, {"empty": True})
        measured = {node_id: self.node_size(spec.node(node_id)) for node_id in ids}
        labels = {node_id: measured[node_id][2] for node_id in ids}
        sizes = {node_id: (measured[node_id][0], measured[node_id][1]) for node_id in ids}
        origin_x = self.margin + 24.0
        origin_y = self.margin + 16.0
        boxes: dict[str, Box] = {}
        for node_id in ids:
            node = spec.node(node_id)
            px = float(node.meta.get("x", 0.5))
            py = float(node.meta.get("y", 0.5))
            px = min(max(px, 0.0), 1.0)
            py = min(max(py, 0.0), 1.0)
            width, height = sizes[node_id]
            cx = origin_x + px * self.plot_width
            cy = origin_y + (1.0 - py) * self.plot_height
            boxes[node_id] = Box(cx - width / 2.0, cy - height / 2.0, width, height)

        quadrants = [
            {"label": spec.meta.get("quadrant_labels", ["", "", "", ""])[0],
             "x": origin_x, "y": origin_y, "w": self.plot_width / 2, "h": self.plot_height / 2},
            {"label": spec.meta.get("quadrant_labels", ["", "", "", ""])[1],
             "x": origin_x + self.plot_width / 2, "y": origin_y,
             "w": self.plot_width / 2, "h": self.plot_height / 2},
            {"label": spec.meta.get("quadrant_labels", ["", "", "", ""])[2],
             "x": origin_x, "y": origin_y + self.plot_height / 2,
             "w": self.plot_width / 2, "h": self.plot_height / 2},
            {"label": spec.meta.get("quadrant_labels", ["", "", "", ""])[3],
             "x": origin_x + self.plot_width / 2, "y": origin_y + self.plot_height / 2,
             "w": self.plot_width / 2, "h": self.plot_height / 2},
        ]
        axis_lines = [
            {"x1": origin_x, "y1": origin_y + self.plot_height / 2,
             "x2": origin_x + self.plot_width, "y2": origin_y + self.plot_height / 2},
            {"x1": origin_x + self.plot_width / 2, "y1": origin_y,
             "x2": origin_x + self.plot_width / 2, "y2": origin_y + self.plot_height},
            {"x1": origin_x, "y1": origin_y, "x2": origin_x, "y2": origin_y + self.plot_height},
            {"x1": origin_x, "y1": origin_y + self.plot_height,
             "x2": origin_x + self.plot_width, "y2": origin_y + self.plot_height},
        ]
        axis_labels = [
            {"text": spec.meta.get("x_label", "x"), "x": origin_x + self.plot_width,
             "y": origin_y + self.plot_height + 34, "anchor": "end"},
            {"text": spec.meta.get("y_label", "y"), "x": origin_x - 26, "y": origin_y,
             "anchor": "middle", "rotate": -90},
        ]
        width = origin_x + self.plot_width + self.margin + 24
        height = origin_y + self.plot_height + self.margin + 32
        return LayoutResult(
            boxes=boxes, routes=[], width=width, height=height, labels=labels,
            extras={"quadrants": quadrants, "axis_lines": axis_lines,
                    "axis_labels": axis_labels, "plot": {
                        "x": origin_x, "y": origin_y,
                        "w": self.plot_width, "h": self.plot_height}},
        )


class MatrixLayout(LayoutEngine):
    """Grid cells driven by node meta row/col (or auto-flow)."""

    def __init__(self, theme: Theme, columns: int = 0, **kwargs: Any) -> None:
        super().__init__(theme, **kwargs)
        self.columns = columns
        self.cell_gap = 18.0

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        ids = spec.node_ids()
        if not ids:
            return LayoutResult({}, [], 640.0, 300.0, {}, {"empty": True})
        measured = {node_id: self.node_size(spec.node(node_id)) for node_id in ids}
        labels = {node_id: measured[node_id][2] for node_id in ids}
        sizes = {node_id: (measured[node_id][0], measured[node_id][1]) for node_id in ids}

        coordinates: dict[str, tuple[int, int]] = {}
        explicit = any(
            spec.node(node_id).meta.get("row") is not None
            or spec.node(node_id).meta.get("col") is not None
            for node_id in ids
        )
        columns = self.columns or int(spec.meta.get("columns", 0) or 0)
        if explicit:
            for node_id in ids:
                node = spec.node(node_id)
                coordinates[node_id] = (
                    int(node.meta.get("row", 0)), int(node.meta.get("col", 0)),
                )
            columns = max(col for _row, col in coordinates.values()) + 1
        else:
            columns = columns or max(1, math.ceil(math.sqrt(len(ids))))
            for index, node_id in enumerate(ids):
                coordinates[node_id] = (index // columns, index % columns)

        column_widths = [self.node_min_width] * columns
        row_heights = defaultdict(lambda: self.node_min_width * 0.5)
        for node_id in ids:
            row, col = coordinates[node_id]
            width, height = sizes[node_id]
            column_widths[col] = max(column_widths[col], width)
            row_heights[row] = max(row_heights[row], height)

        x_offsets = [self.margin]
        for width in column_widths[:-1]:
            x_offsets.append(x_offsets[-1] + width + self.cell_gap)
        y_offsets = [self.margin]
        for row in range(max(r for r, _c in coordinates.values())):
            y_offsets.append(y_offsets[-1] + row_heights[row] + self.cell_gap)

        boxes: dict[str, Box] = {}
        for node_id in ids:
            row, col = coordinates[node_id]
            width, height = sizes[node_id]
            boxes[node_id] = Box(
                x_offsets[col] + (column_widths[col] - width) / 2.0,
                y_offsets[row] + (row_heights[row] - height) / 2.0,
                width, height,
            )
        routes = [self._route(edge, boxes) for edge in spec.edges
                  if edge.source in boxes and edge.target in boxes]
        width = x_offsets[-1] + column_widths[-1] + self.margin
        height = y_offsets[-1] + row_heights[max(r for r, _c in coordinates.values())] + self.margin
        return LayoutResult(
            boxes=boxes, routes=routes, width=max(width, 320.0), height=max(height, 200.0),
            labels=labels, extras={"columns": columns,
                                   "grid": {node_id: coordinates[node_id] for node_id in ids}},
        )

    def _route(self, edge: DiagramEdge, boxes: dict[str, Box]) -> EdgeRoute:
        s, t = boxes[edge.source], boxes[edge.target]
        sx, sy = s.center
        tx, ty = t.center
        if abs(sx - tx) >= abs(sy - ty):
            start = (s.right, sy) if tx > sx else (s.x, sy)
            end = (t.x, ty) if tx > sx else (t.right, ty)
            mid = (start[0] + end[0]) / 2.0
            points = [start, (mid, sy), (mid, ty), end]
        else:
            start = (sx, s.bottom) if ty > sy else (sx, s.y)
            end = (tx, t.y) if ty > sy else (tx, t.bottom)
            mid = (start[1] + end[1]) / 2.0
            points = [start, (sx, mid), (tx, mid), end]
        return EdgeRoute(edge, points, label_position=(points[1][0], points[1][1] - 6.0))


class TimelineLayout(LayoutEngine):
    """Evenly spaced events on a horizontal axis, alternating above and below."""

    def __init__(self, theme: Theme, **kwargs: Any) -> None:
        super().__init__(theme, **kwargs)
        self.step = 220.0

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        ids = spec.node_ids()
        if not ids:
            return LayoutResult({}, [], 640.0, 300.0, {}, {"empty": True})
        measured = {node_id: self.node_size(spec.node(node_id)) for node_id in ids}
        labels = {node_id: measured[node_id][2] for node_id in ids}
        sizes = {node_id: (measured[node_id][0], measured[node_id][1]) for node_id in ids}
        ordered = sorted(
            ids,
            key=lambda n: (float(spec.node(n).meta.get("order", ids.index(n))), ids.index(n)),
        )
        axis_y = self.margin + 170.0
        boxes: dict[str, Box] = {}
        for index, node_id in enumerate(ordered):
            width, height = sizes[node_id]
            cx = self.margin + 40.0 + index * self.step
            above = index % 2 == 0
            y = axis_y - height - 44.0 if above else axis_y + 44.0
            boxes[node_id] = Box(cx - width / 2.0, y, width, height)
        nodes = [
            {"x": boxes[node_id].center[0], "y": axis_y,
             "above": boxes[node_id].bottom < axis_y, "id": node_id}
            for node_id in ordered
        ]
        width = self.margin * 2 + 40.0 + self.step * max(0, len(ordered) - 1) + self.step / 2
        height = axis_y + 44.0 + max(sizes[n][1] for n in ids) + self.margin
        return LayoutResult(
            boxes=boxes, routes=[], width=width, height=height, labels=labels,
            extras={"axis": {"x1": self.margin, "x2": width - self.margin, "y": axis_y},
                    "timeline_nodes": nodes},
        )


class FunnelLayout(LayoutEngine):
    """Stacked trapezoids narrowing towards the conversion point."""

    def __init__(self, theme: Theme, **kwargs: Any) -> None:
        super().__init__(theme, **kwargs)
        self.top_width = 520.0
        self.step_height = 78.0

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        ids = spec.node_ids()
        if not ids:
            return LayoutResult({}, [], 640.0, 300.0, {}, {"empty": True})
        measured = {node_id: self.node_size(spec.node(node_id)) for node_id in ids}
        labels = {node_id: measured[node_id][2] for node_id in ids}
        sizes = {node_id: (measured[node_id][0], measured[node_id][1]) for node_id in ids}
        count = len(ids)
        boxes: dict[str, Box] = {}
        bands: list[dict[str, Any]] = []
        y = self.margin
        for index, node_id in enumerate(ids):
            ratio_top = 1.0 - 0.62 * (index / max(1, count))
            ratio_bottom = 1.0 - 0.62 * ((index + 1) / max(1, count))
            top = self.top_width * ratio_top
            bottom = self.top_width * ratio_bottom
            height = self.step_height
            width = max(top, bottom)
            cx = self.margin + self.top_width / 2.0
            node_width = min(width - 28.0, max(120.0, sizes[node_id][0]))
            boxes[node_id] = Box(cx - node_width / 2.0, y + (height - sizes[node_id][1]) / 2.0,
                                 node_width, sizes[node_id][1])
            bands.append({"x": cx, "y": y, "top": top, "bottom": bottom, "h": height})
            y += height
        return LayoutResult(
            boxes=boxes, routes=[], width=self.top_width + 2 * self.margin, height=y + self.margin,
            labels=labels, extras={"funnel_bands": bands},
        )


class PyramidLayout(FunnelLayout):
    """Inverted funnel: narrow at the apex, widest at the foundation."""

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        result = super().layout(spec)
        bands = result.extras.get("funnel_bands", [])
        total = len(bands)
        original = [(band["y"], band["top"], band["bottom"]) for band in bands]
        for index, band in enumerate(bands):
            _y, top, bottom = original[total - index - 1]
            band["top"], band["bottom"] = bottom, top
        return result


class VennLayout(LayoutEngine):
    """Two or three overlapping circles with labels at the set edges."""

    RADIUS = 150.0

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        ids = spec.node_ids()
        if not ids:
            return LayoutResult({}, [], 640.0, 300.0, {}, {"empty": True})
        count = min(len(ids), 3)
        centers = {
            1: [(320.0, 240.0)],
            2: [(260.0, 240.0), (420.0, 240.0)],
            3: [(320.0, 190.0), (240.0, 320.0), (400.0, 320.0)],
        }[count]
        label_anchors = {
            1: [(320.0, 250.0)],
            2: [(260.0, 96.0), (420.0, 96.0)],
            3: [(320.0, 44.0), (190.0, 392.0), (450.0, 392.0)],
        }[count]

        circles: list[dict[str, Any]] = []
        boxes: dict[str, Box] = {}
        labels: dict[str, list[str]] = {}
        for index, node_id in enumerate(ids[:count]):
            node = spec.node(node_id)
            cx, cy = centers[index]
            circles.append({"cx": cx, "cy": cy, "r": self.RADIUS,
                            "label": node.label, "index": index})
            anchor_x, anchor_y = label_anchors[index]
            width = max(96.0, self.measurer.width(node.label, self.font_size) + 20.0)
            boxes[node_id] = Box(anchor_x - width / 2.0, anchor_y - 12.0, width, 24.0)
            labels[node_id] = [node.label]
        for offset, node_id in enumerate(ids[count:]):   # overflow nodes: caption strip
            node = spec.node(node_id)
            width = max(96.0, self.measurer.width(node.label, self.font_size) + 20.0)
            boxes[node_id] = Box(self.margin + offset * (width + 16.0), 468.0, width, 24.0)
            labels[node_id] = [node.label]
        return LayoutResult(
            boxes=boxes, routes=[], width=660.0, height=520.0, labels=labels,
            extras={"circles": circles},
        )


class RadialLayout(LayoutEngine):
    """Hub-and-spoke / cycle placement around a centre."""

    def __init__(self, theme: Theme, **kwargs: Any) -> None:
        super().__init__(theme, **kwargs)
        self.radius = 220.0

    def layout(self, spec: DiagramSpec) -> LayoutResult:
        ids = spec.node_ids()
        if not ids:
            return LayoutResult({}, [], 640.0, 300.0, {}, {"empty": True})
        measured = {node_id: self.node_size(spec.node(node_id)) for node_id in ids}
        labels = {node_id: measured[node_id][2] for node_id in ids}
        sizes = {node_id: (measured[node_id][0], measured[node_id][1]) for node_id in ids}
        hub = spec.meta.get("hub") or ids[0]
        if hub not in ids:
            hub = ids[0]
        cx, cy = 420.0, 360.0
        boxes: dict[str, Box] = {}
        hub_width, hub_height = sizes[hub]
        boxes[hub] = Box(cx - hub_width / 2.0, cy - hub_height / 2.0, hub_width, hub_height)
        spokes = [node_id for node_id in ids if node_id != hub]
        for index, node_id in enumerate(spokes):
            angle = 2 * math.pi * index / max(1, len(spokes)) - math.pi / 2.0
            width, height = sizes[node_id]
            node_cx = cx + self.radius * math.cos(angle) * 1.35
            node_cy = cy + self.radius * math.sin(angle)
            boxes[node_id] = Box(node_cx - width / 2.0, node_cy - height / 2.0, width, height)
        routes: list[EdgeRoute] = []
        for edge in spec.edges:
            if edge.source not in boxes or edge.target not in boxes:
                continue
            s, t = boxes[edge.source], boxes[edge.target]
            points = [s.center, t.center]
            routes.append(EdgeRoute(
                edge, points,
                label_position=((s.center[0] + t.center[0]) / 2.0,
                                (s.center[1] + t.center[1]) / 2.0 - 6.0),
            ))
        width = max((box.right for box in boxes.values()), default=0.0) + self.margin
        height = max((box.bottom for box in boxes.values()), default=0.0) + self.margin
        return LayoutResult(
            boxes=boxes, routes=routes, width=max(width, 640.0), height=max(height, 420.0),
            labels=labels, extras={"hub": hub, "center": (cx, cy)},
        )


LAYOUT_ENGINES = {
    "layered": LayeredLayout,
    "tree": TreeLayout,
    "sequence": SequenceLayout,
    "quadrant": QuadrantLayout,
    "matrix": MatrixLayout,
    "timeline": TimelineLayout,
    "funnel": FunnelLayout,
    "pyramid": PyramidLayout,
    "venn": VennLayout,
    "radial": RadialLayout,
}


# ── SVG rendering ─────────────────────────────────────────────────────────

def escape_xml(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


class SvgRenderer:
    """Render a laid-out diagram to one self-contained SVG string."""

    def __init__(self, theme: Theme) -> None:
        self.theme = theme
        p = theme.palette
        self.kind_colors = {
            "step": p.surface,
            "decision": mix(p.paper, p.accent, 0.16),
            "data": mix(p.paper, p.seed, 0.16),
            "actor": mix(p.paper, p.muted, 0.14),
            "note": p.paper,
            "metric": mix(p.paper, p.accent, 0.08),
        }

    def _node_fill(self, node: DiagramNode, index: int) -> str:
        if node.meta.get("color"):
            return str(node.meta["color"])
        tints = self.theme.palette.tints(6)
        return self.kind_colors.get(node.kind, tints[index % len(tints)])

    def render(
        self, spec: DiagramSpec, layout: LayoutResult, subtitle: str = "",
    ) -> str:
        theme = self.theme
        p = theme.palette
        width = layout.width
        legend_space = 34.0 if len(spec.kinds()) >= 2 else 0.0
        height = layout.height + (52 if spec.title else 0) + legend_space
        parts: list[str] = []
        parts.append(
            f'<svg xmlns="http://www.w3.org/2000/svg" role="img" '
            f'viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" '
            f'height="{height:.0f}" aria-label="{escape_xml(spec.title or "diagram")}">'
        )
        parts.append(
            "<defs>"
            '<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{p.muted}"/></marker>'
            "</defs>"
        )
        parts.append(f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="{p.paper}"/>')
        top = 0.0
        if spec.title:
            parts.append(
                f'<text x="{theme.spacing}" y="30" font-size="19" font-weight="640" '
                f'fill="{p.ink}">{escape_xml(spec.title)}</text>'
            )
            if subtitle:
                parts.append(
                    f'<text x="{theme.spacing}" y="50" font-size="12" '
                    f'fill="{p.muted}">{escape_xml(subtitle)}</text>'
                )
            top = 52.0
        parts.append(f'<g transform="translate(0,{top:.1f})">')

        parts.extend(self._render_extras_back(layout))
        parts.extend(self._render_routes(layout))
        parts.extend(self._render_nodes(spec, layout))
        parts.extend(self._render_extras_front(layout))
        parts.append("</g>")

        legend = self._legend(spec, layout, top)
        if legend:
            parts.append(legend)
        parts.append("</svg>")
        return "\n".join(parts)

    # ── pieces ───────────────────────────────────────────────────────

    def _render_extras_back(self, layout: LayoutResult) -> list[str]:
        p = self.theme.palette
        out: list[str] = []
        for quadrant in layout.extras.get("quadrants", []):
            x, y = quadrant["x"], quadrant["y"]
            w, h = quadrant["w"], quadrant["h"]
            index = layout.extras["quadrants"].index(quadrant)
            fill = p.surface if index % 2 == 0 else p.paper
            out.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                f'fill="{fill}" stroke="{p.line}" stroke-width="0.75"/>'
            )
            if quadrant.get("label"):
                out.append(
                    f'<text x="{x + 14:.1f}" y="{y + 24:.1f}" font-size="10" '
                    f'letter-spacing="1.4" fill="{p.muted}">'
                    f'{escape_xml(str(quadrant["label"]).upper())}</text>'
                )
        for line in layout.extras.get("axis_lines", []):
            out.append(
                f'<line x1="{line["x1"]:.1f}" y1="{line["y1"]:.1f}" '
                f'x2="{line["x2"]:.1f}" y2="{line["y2"]:.1f}" '
                f'stroke="{p.line}" stroke-width="1"/>'
            )
        for circle in layout.extras.get("circles", []):
            out.append(
                f'<circle cx="{circle["cx"]:.1f}" cy="{circle["cy"]:.1f}" '
                f'r="{circle["r"]:.1f}" fill="{p.surface}" fill-opacity="0.55" '
                f'stroke="{p.seed}" stroke-width="1.25"/>'
            )
        for band in layout.extras.get("funnel_bands", []):
            cx, y = band["x"], band["y"]
            top_w, bottom_w, h = band["top"], band["bottom"], band["h"]
            points = (
                f"{cx - top_w / 2:.1f},{y:.1f} {cx + top_w / 2:.1f},{y:.1f} "
                f"{cx + bottom_w / 2:.1f},{y + h:.1f} {cx - bottom_w / 2:.1f},{y + h:.1f}"
            )
            out.append(
                f'<polygon points="{points}" fill="{p.surface}" stroke="{p.line}" '
                f'stroke-width="1"/>'
            )
        axis = layout.extras.get("axis")
        if axis:
            out.append(
                f'<line x1="{axis["x1"]:.1f}" y1="{axis["y"]:.1f}" '
                f'x2="{axis["x2"]:.1f}" y2="{axis["y"]:.1f}" '
                f'stroke="{p.ink}" stroke-width="1.25"/>'
            )
        for lifeline in layout.extras.get("lifelines", []):
            out.append(
                f'<line x1="{lifeline["x"]:.1f}" y1="{lifeline["y1"]:.1f}" '
                f'x2="{lifeline["x"]:.1f}" y2="{lifeline["y2"]:.1f}" '
                f'stroke="{p.line}" stroke-width="1" stroke-dasharray="4 5"/>'
            )
        return out

    def _render_extras_front(self, layout: LayoutResult) -> list[str]:
        p = self.theme.palette
        out: list[str] = []
        for label in layout.extras.get("axis_labels", []):
            transform = ""
            if label.get("rotate"):
                transform = f' transform="rotate({label["rotate"]} {label["x"]:.1f} {label["y"]:.1f})"'
            out.append(
                f'<text x="{label["x"]:.1f}" y="{label["y"]:.1f}" font-size="11" '
                f'letter-spacing="0.8" text-anchor="{label.get("anchor", "start")}" '
                f'fill="{p.muted}"{transform}>{escape_xml(str(label["text"]).upper())}</text>'
            )
        for node in layout.extras.get("timeline_nodes", []):
            cy = node["y"]
            out.append(
                f'<circle cx="{node["x"]:.1f}" cy="{cy:.1f}" r="5" fill="{p.paper}" '
                f'stroke="{p.seed}" stroke-width="2"/>'
            )
            if node["above"]:
                out.append(
                    f'<line x1="{node["x"]:.1f}" y1="{cy - 5:.1f}" x2="{node["x"]:.1f}" '
                    f'y2="{cy - 34:.1f}" stroke="{p.line}" stroke-width="1"/>'
                )
        return out

    def _render_routes(self, layout: LayoutResult) -> list[str]:
        p = self.theme.palette
        out: list[str] = []
        for route in layout.routes:
            path = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in route.points)
            dash = ""
            if route.edge.style == "dashed":
                dash = ' stroke-dasharray="6 4"'
            elif route.edge.style == "dotted":
                dash = ' stroke-dasharray="2 4"'
            elif route.reversed:
                dash = ' stroke-dasharray="6 4"'
            color = p.seed if route.edge.kind == "flow" else p.muted
            out.append(
                f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.4"'
                f'{dash} marker-end="url(#arrow)"/>'
            )
            if route.edge.label:
                lx, ly = route.label_position
                text = escape_xml(route.edge.label)
                width = TextMeasurer().width(route.edge.label, 11) + 10
                out.append(
                    f'<rect x="{lx - width / 2:.1f}" y="{ly - 11:.1f}" width="{width:.1f}" '
                    f'height="15" fill="{p.paper}" fill-opacity="0.92"/>'
                )
                out.append(
                    f'<text x="{lx:.1f}" y="{ly:.1f}" font-size="11" text-anchor="middle" '
                    f'fill="{p.muted}">{text}</text>'
                )
        return out

    def _render_nodes(self, spec: DiagramSpec, layout: LayoutResult) -> list[str]:
        theme = self.theme
        p = theme.palette
        out: list[str] = []
        circles_only = spec.diagram_type == "venn"
        for index, node in enumerate(spec.nodes):
            box = layout.boxes.get(node.node_id)
            if box is None:
                continue
            fill = self._node_fill(node, index)
            stroke = p.line if node.kind == "step" else p.seed
            stroke_width = theme.stroke if node.kind != "step" else 1.0
            radius = theme.radius
            dash = ' stroke-dasharray="5 4"' if node.kind == "note" else ""
            if circles_only:
                pass    # venn sets are drawn as large circles in the back layer
            elif node.meta.get("shape") == "diamond" or node.kind == "decision":
                cx, cy = box.center
                points = (
                    f"{cx:.1f},{box.y:.1f} {box.right:.1f},{cy:.1f} "
                    f"{cx:.1f},{box.bottom:.1f} {box.x:.1f},{cy:.1f}"
                )
                out.append(
                    f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" '
                    f'stroke-width="{stroke_width}"{dash}/>'
                )
            elif node.meta.get("shape") == "circle":
                cx, cy = box.center
                out.append(
                    f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                    f'r="{min(box.width, box.height) / 2:.1f}" fill="{fill}" '
                    f'stroke="{stroke}" stroke-width="{stroke_width}"{dash}/>'
                )
            else:
                out.append(
                    f'<rect x="{box.x:.1f}" y="{box.y:.1f}" width="{box.width:.1f}" '
                    f'height="{box.height:.1f}" rx="{radius}" fill="{fill}" '
                    f'stroke="{stroke}" stroke-width="{stroke_width}"{dash}/>'
                )
            lines = layout.labels.get(node.node_id) or [node.label]
            line_height = (theme.base_size + 1) * 1.35
            block_height = len(lines) * line_height
            text_color = ensure_contrast(p.ink, fill, 4.5)
            start_y = box.center[1] - block_height / 2.0 + line_height * 0.78
            for line_index, line in enumerate(lines):
                y = start_y + line_index * line_height
                out.append(
                    f'<text x="{box.center[0]:.1f}" y="{y:.1f}" font-size="{theme.base_size + 1}" '
                    f'text-anchor="middle" fill="{text_color}">{escape_xml(line)}</text>'
                )
        return out

    def _legend(self, spec: DiagramSpec, layout: LayoutResult, top: float) -> str:
        """Legend drawn in SVG coordinates below the canvas (a div inside svg is invalid)."""
        kinds = spec.kinds()
        if len(kinds) < 2:
            return ""
        p = self.theme.palette
        y = top + layout.height + 20.0
        parts = [f'<g transform="translate({self.theme.spacing},0)">']
        x = 0.0
        for kind in kinds:
            color = self.kind_colors.get(kind, p.surface)
            parts.append(
                f'<rect x="{x:.1f}" y="{y - 9:.1f}" width="10" height="10" rx="2" '
                f'fill="{color}" stroke="{p.line}" stroke-width="0.75"/>'
            )
            parts.append(
                f'<text x="{x + 16:.1f}" y="{y:.1f}" font-size="11" '
                f'fill="{p.muted}">{escape_xml(kind)}</text>'
            )
            x += 26 + TextMeasurer().width(kind, 11)
        parts.append("</g>")
        return "\n".join(parts)


# ── Document ──────────────────────────────────────────────────────────────

class DiagramDocument:
    """A single self-contained HTML file containing the rendered SVG."""

    def __init__(self, theme: Theme) -> None:
        self.theme = theme

    def build(
        self, spec: DiagramSpec, svg: str, subtitle: str = "", footer: str = "",
    ) -> str:
        p = self.theme.palette
        return (
            "<!DOCTYPE html>\n"
            '<html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f"<title>{escape_xml(spec.title)}</title>"
            f"{self.theme.esc()}"
            "</head><body><main class=\"sheet\">"
            f'<p class="kicker">{escape_xml(spec.kicker)} · {escape_xml(spec.diagram_type)}</p>'
            f"<h1>{escape_xml(spec.title)}</h1>"
            f'<p class="deck">{escape_xml(subtitle or spec.subtitle or "")}</p>'
            f'<div class="canvas">{svg}</div>'
            f'<div class="foot"><span>{escape_xml(p.name)} · {escape_xml(p.seed)}</span>'
            f"<span>{escape_xml(footer)}</span></div>"
            "</main></body></html>"
        )

    @staticmethod
    def self_contained(html: str) -> bool:
        """No external requests: no remote assets, scripts or font imports."""
        lowered = html.lower().replace('xmlns="http://www.w3.org/2000/svg"', "")
        if re.search(r"https?://", lowered) or re.search(r"url\(\s*['\"]?https?:", lowered):
            return False
        if re.search(r"<(script|link|iframe)\b", lowered):
            return False
        return "@import" not in lowered


# ── Import ────────────────────────────────────────────────────────────────

class MermaidImporter:
    """Parse Mermaid flowchart / sequence diagrams into a DiagramSpec."""

    FLOW_EDGE = re.compile(
        r"^\s*([A-Za-z0-9_]+)(?:\[(.*?)\]|\{(.*?)\}|\((.*?)\))?\s*"
        r"(-->|---|-.->|==>)(?:\|(.*?)\|)?\s*"
        r"([A-Za-z0-9_]+)(?:\[(.*?)\]|\{(.*?)\}|\((.*?)\))?\s*$"
    )
    SEQ_EDGE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*(->>|-->>|-->|->|--x|-x)\s*([A-Za-z0-9_]+)\s*:\s*(.*)$")

    def parse(self, source: str, title: str = "Imported diagram") -> DiagramSpec:
        lines = [line for line in (source or "").splitlines()]
        header = ""
        body: list[str] = []
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("%%"):
                continue
            if not header:
                header = stripped
                continue
            body.append(stripped)
        if header.lower().startswith("sequencediagram"):
            return self._parse_sequence(header, body, title)
        return self._parse_flow(header, body, title)

    def _parse_flow(self, header: str, body: list[str], title: str) -> DiagramSpec:
        direction = "TD"
        match = re.search(r"\b(TD|TB|LR|RL|BT)\b", header, re.IGNORECASE)
        if match:
            direction = match.group(1).upper()
        nodes: dict[str, DiagramNode] = {}
        edges: list[DiagramEdge] = []

        def ensure(node_id: str, label: str = "", shape: str = "") -> None:
            if node_id in nodes and label:
                nodes[node_id] = DiagramNode(node_id=node_id, label=label,
                                             kind="decision" if shape == "diamond" else "step")
                return
            if node_id in nodes:
                return
            kind = "decision" if shape == "diamond" else "step"
            nodes[node_id] = DiagramNode(node_id=node_id, label=label or node_id, kind=kind)

        for line in body:
            match = self.FLOW_EDGE.match(line)
            if not match:
                # Bare node declaration: A[Label]
                bare = re.match(r"^([A-Za-z0-9_]+)(?:\[(.*?)\]|\{(.*?)\}|\((.*?)\))$", line)
                if bare:
                    ensure(
                        bare.group(1),
                        bare.group(2) or bare.group(3) or bare.group(4) or "",
                        "diamond" if bare.group(3) is not None else "",
                    )
                continue
            source, s_label, s_brace, s_paren, arrow, label, target, t_label, t_brace, t_paren = match.groups()
            ensure(source, s_label or s_brace or s_paren or "",
                   "diamond" if s_brace is not None else "")
            ensure(target, t_label or t_brace or t_paren or "",
                   "diamond" if t_brace is not None else "")
            style = "dashed" if arrow in ("-.->",) else "solid"
            edges.append(DiagramEdge(source=source, target=target, label=(label or "").strip(),
                                     style=style))

        return DiagramSpec(
            title=title,
            diagram_type="flowchart" if direction in ("TD", "TB") else "architecture",
            nodes=list(nodes.values()),
            edges=edges,
            meta={"direction": "TD" if direction in ("TD", "TB", "BT") else "LR",
                  "source": "mermaid"},
        )

    def _parse_sequence(self, header: str, body: list[str], title: str) -> DiagramSpec:
        participants: dict[str, DiagramNode] = {}
        edges: list[DiagramEdge] = []
        for line in body:
            declared = re.match(r"^(?:participant|actor)\s+([A-Za-z0-9_]+)(?:\s+as\s+(.*))?$", line)
            if declared:
                participants[declared.group(1)] = DiagramNode(
                    node_id=declared.group(1),
                    label=(declared.group(2) or declared.group(1)).strip(),
                    kind="actor",
                )
                continue
            match = self.SEQ_EDGE.match(line)
            if match:
                source, arrow, target, label = match.groups()
                for node_id in (source, target):
                    if node_id not in participants:
                        participants[node_id] = DiagramNode(node_id=node_id, label=node_id,
                                                            kind="actor")
                edges.append(DiagramEdge(
                    source=source, target=target, label=label.strip(),
                    style="dashed" if arrow in ("-->>", "-->") else "solid",
                ))
        return DiagramSpec(
            title=title, diagram_type="sequence",
            nodes=list(participants.values()), edges=edges, meta={"source": "mermaid"},
        )


# ── Validation ────────────────────────────────────────────────────────────

@dataclass
class DiagramIssue:
    """One validation finding."""

    severity: str        # error | warning | info
    code: str
    message: str
    nodes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "code": self.code,
                "message": self.message, "nodes": self.nodes}


@dataclass
class ValidationReport:
    """The result of validating a laid-out diagram."""

    issues: list[DiagramIssue] = field(default_factory=list)
    score: float = 1.0
    checks: int = 0

    @property
    def errors(self) -> list[DiagramIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> list[DiagramIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": round(self.score, 3),
            "checks": self.checks,
            "errors": [i.as_dict() for i in self.errors],
            "warnings": [i.as_dict() for i in self.warnings],
        }


class DiagramValidator:
    """Catch the failures that make generated diagrams look broken."""

    def __init__(self, theme: Theme, measurer: TextMeasurer | None = None) -> None:
        self.theme = theme
        self.measurer = measurer or TextMeasurer()

    def validate(self, spec: DiagramSpec, layout: LayoutResult) -> ValidationReport:
        issues: list[DiagramIssue] = []
        checks = 0

        for problem in spec.validate_structure():
            issues.append(DiagramIssue("error", "structure", problem))
        checks += 1

        if not spec.title.strip():
            issues.append(DiagramIssue("warning", "title", "diagram has no title"))
        checks += 1

        for a, b, area in layout.overlaps(tolerance=4.0):
            issues.append(DiagramIssue(
                "error", "overlap",
                f"nodes {a} and {b} overlap by {area:.0f}px²", [a, b],
            ))
        checks += 1

        for node_id, box in layout.boxes.items():
            if box.x < -1 or box.y < -1:
                issues.append(DiagramIssue(
                    "warning", "bounds", f"{node_id} starts outside the canvas", [node_id],
                ))
            if box.right > layout.width + 1 or box.bottom > layout.height + 1:
                issues.append(DiagramIssue(
                    "error", "bounds", f"{node_id} overflows the canvas", [node_id],
                ))
        checks += 1

        for node in spec.nodes:
            box = layout.boxes.get(node.node_id)
            if box is None:
                issues.append(DiagramIssue(
                    "error", "missing_box", f"{node.node_id} has no layout box", [node.node_id],
                ))
                continue
            lines = layout.labels.get(node.node_id) or self.measurer.wrap(
                node.label, box.width - 2, self.theme.base_size + 1,
            )
            widest = max((self.measurer.width(line, self.theme.base_size + 1) for line in lines),
                         default=0.0)
            if widest > box.width + 0.5:
                issues.append(DiagramIssue(
                    "warning", "label_overflow",
                    f"label of {node.node_id} is wider than its box", [node.node_id],
                ))
            fill = node.meta.get("color") or self.theme.palette.surface
            if contrast_ratio(self.theme.palette.ink, fill) < 4.5:
                issues.append(DiagramIssue(
                    "warning", "contrast",
                    f"label on {node.node_id} may fail WCAG AA", [node.node_id],
                ))
        checks += 1

        crossings = self.count_crossings(layout)
        if crossings > max(2, len(layout.routes) // 2):
            issues.append(DiagramIssue(
                "warning", "edge_crossing",
                f"{crossings} edge crossings — consider another layout", [],
            ))
        checks += 1

        connected = {e.source for e in spec.edges} | {e.target for e in spec.edges}
        orphans = [n.node_id for n in spec.nodes if n.node_id not in connected]
        if spec.edges and len(orphans) == len(spec.nodes):
            issues.append(DiagramIssue(
                "error", "disconnected", "no edges connect the nodes", orphans,
            ))
        elif spec.edges and orphans:
            issues.append(DiagramIssue(
                "info", "orphans", f"{len(orphans)} node(s) have no edges", orphans,
            ))
        checks += 1

        errors = len([i for i in issues if i.severity == "error"])
        warnings = len([i for i in issues if i.severity == "warning"])
        score = max(0.0, 1.0 - errors * 0.25 - warnings * 0.05)
        return ValidationReport(issues=issues, score=score, checks=checks)

    @staticmethod
    def count_crossings(layout: LayoutResult) -> int:
        segments = []
        for route in layout.routes:
            segments.extend(route.segments())
        crossings = 0
        for i, (a1, a2) in enumerate(segments):
            for b1, b2 in segments[i + 1:]:
                if _segments_intersect(a1, a2, b1, b2):
                    crossings += 1
        return crossings


# ── Studio ────────────────────────────────────────────────────────────────

@dataclass
class DiagramArtifact:
    """Everything produced for one diagram request."""

    spec: DiagramSpec
    layout: LayoutResult
    svg: str
    html: str
    report: ValidationReport
    theme: Theme

    @property
    def width(self) -> float:
        return round(self.layout.width, 1)

    @property
    def height(self) -> float:
        return round(self.layout.height, 1)

    def summary(self) -> dict[str, Any]:
        return {
            "type": self.spec.diagram_type,
            "title": self.spec.title,
            "nodes": len(self.spec.nodes),
            "edges": len(self.spec.edges),
            "width": self.width,
            "height": self.height,
            "self_contained": DiagramDocument.self_contained(self.html),
            "validation": self.report.as_dict(),
        }


class DiagramStudio:
    """Orchestrate: request -> type -> layout -> SVG/HTML -> validation."""

    def __init__(self, palette: BrandPalette | None = None, theme: Theme | None = None) -> None:
        self.palette = palette or BrandPalette.from_seed("#bf4520")
        self.theme = theme or Theme(palette=self.palette)
        self.selector = DiagramSelector()
        self.renderer = SvgRenderer(self.theme)
        self.document = DiagramDocument(self.theme)
        self.validator = DiagramValidator(self.theme)
        self.importer = MermaidImporter()

    def layout_for(self, spec: DiagramSpec) -> LayoutResult:
        type_info = TYPE_INDEX.get(spec.diagram_type)
        family = type_info.layout if type_info else "layered"
        engine_class = LAYOUT_ENGINES.get(family, LayeredLayout)
        if engine_class is LayeredLayout:
            direction = "LR" if spec.meta.get("direction") == "LR" else "TD"
            engine = engine_class(self.theme, direction=direction)
        elif engine_class is MatrixLayout:
            engine = engine_class(self.theme, columns=int(spec.meta.get("columns", 0) or 0))
        else:
            engine = engine_class(self.theme)
        return engine.layout(spec)

    def build(self, spec: DiagramSpec, subtitle: str = "", footer: str = "diagram-design") -> DiagramArtifact:
        layout = self.layout_for(spec)
        svg = self.renderer.render(spec, layout, subtitle=subtitle)
        html = self.document.build(spec, svg, subtitle=subtitle, footer=footer)
        report = self.validator.validate(spec, layout)
        return DiagramArtifact(spec=spec, layout=layout, svg=svg, html=html,
                               report=report, theme=self.theme)

    def from_request(self, request: str, nodes: list[DiagramNode] | None = None,
                     edges: list[DiagramEdge] | None = None, **spec_kwargs: Any) -> DiagramArtifact:
        choice = self.selector.select(request)
        spec = DiagramSpec(
            title=spec_kwargs.pop("title", request.strip().capitalize()),
            diagram_type=choice.type_id,
            nodes=nodes or [],
            edges=edges or [],
            **spec_kwargs,
        )
        return self.build(spec)

    def from_mermaid(self, source: str, title: str = "Imported diagram") -> DiagramArtifact:
        spec = self.importer.parse(source, title=title)
        direction = spec.meta.get("direction", "TD")
        spec.meta["direction"] = direction
        return self.build(spec)

    def restyle(self, artifact: DiagramArtifact, seed: str) -> DiagramArtifact:
        """Rebuild with a new brand seed, keeping the spec and layout intent."""
        palette = BrandPalette.from_seed(seed, name=self.palette.name)
        return DiagramStudio(palette=palette).build(
            artifact.spec, subtitle=artifact.spec.subtitle,
        )


# ── Module-level engine ───────────────────────────────────────────────────

class DiagramDesignEngine:
    """Facade used by VyralX content pipelines."""

    def __init__(self) -> None:
        self.studio = DiagramStudio()

    def catalogue(self) -> dict[str, Any]:
        categories: dict[str, list[str]] = defaultdict(list)
        for diagram_type in DIAGRAM_TYPES:
            categories[diagram_type.category].append(diagram_type.type_id)
        return {
            "types": len(DIAGRAM_TYPES),
            "categories": {k: v for k, v in sorted(categories.items())},
        }

    def choose(self, request: str) -> dict[str, Any]:
        return self.studio.selector.explain(request)

    def palette_for(self, seed: str) -> dict[str, Any]:
        palette = BrandPalette.from_seed(seed)
        return {
            **palette.as_dict(),
            "tints": palette.tints(4),
            "categorical": palette.categorical(4),
            "contrast_ink_paper": round(contrast_ratio(palette.ink, palette.paper), 2),
        }

    def render_flowchart(self, title: str, steps: list[str], **kwargs: Any) -> dict[str, Any]:
        nodes = [DiagramNode(f"n{i}", label, kind="step") for i, label in enumerate(steps, 1)]
        edges = [
            DiagramEdge(nodes[i].node_id, nodes[i + 1].node_id)
            for i in range(len(nodes) - 1)
        ]
        artifact = self.studio.build(
            DiagramSpec(title=title, diagram_type="flowchart", nodes=nodes, edges=edges),
            **kwargs,
        )
        return {**artifact.summary(), "svg": artifact.svg, "html": artifact.html}

    def render_sequence(self, title: str, participants: list[str],
                        messages: list[tuple[str, str, str]]) -> dict[str, Any]:
        nodes = [DiagramNode(p.lower().replace(" ", "-"), p, kind="actor") for p in participants]
        lookup = {p.lower().replace(" ", "-"): p for p in participants}
        edges = []
        for source, target, label in messages:
            s = source.lower().replace(" ", "-")
            t = target.lower().replace(" ", "-")
            if s in lookup and t in lookup:
                edges.append(DiagramEdge(s, t, label=label))
        artifact = self.studio.build(
            DiagramSpec(title=title, diagram_type="sequence", nodes=nodes, edges=edges)
        )
        return artifact.summary()


# Module-level instance
engine = DiagramDesignEngine()
