"""
VyralX/app/services/diagram_service.py — Diagram Design Service.

VyralX produces explainers, not just video. This service makes the
diagram-design engine a first-class part of the content pipeline:

* ``DiagramService`` — pick a diagram type for a brief, derive a brand palette,
  render one self-contained HTML+SVG file, validate it, restyle it for a new
  brand seed, or import an existing Mermaid/drawio graph.
* ``attach_explainer`` — the hook the content pipeline calls so every generated
  content pack can carry an explainer diagram (markdown + inline SVG + HTML).
* ``router`` — ``/api/v1/diagrams/*`` endpoints mounted by ``app/main.py``.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Iterable

_MODULE_PATH = Path(__file__).resolve().parents[1] / "agents" / "real_diagram_design.py"

if "vyralx_diagram_design" in sys.modules:
    dd = sys.modules["vyralx_diagram_design"]
else:
    _spec = importlib.util.spec_from_file_location("vyralx_diagram_design", _MODULE_PATH)
    dd = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
    sys.modules["vyralx_diagram_design"] = dd
    _spec.loader.exec_module(dd)  # type: ignore[union-attr]

try:  # pragma: no cover - only when FastAPI is installed
    from fastapi import APIRouter, HTTPException
    from fastapi.responses import HTMLResponse
    from pydantic import BaseModel, Field

    _ROUTER_AVAILABLE = True
except Exception:  # pragma: no cover
    APIRouter = None  # type: ignore[assignment]
    HTTPException = None  # type: ignore[assignment]
    HTMLResponse = None  # type: ignore[assignment]
    BaseModel = object  # type: ignore[assignment]

    def Field(*_args: Any, **_kwargs: Any) -> Any:  # type: ignore[misc]
        return None

    _ROUTER_AVAILABLE = False


class DiagramService:
    """Render, validate, restyle and import diagrams for VyralX content."""

    def __init__(self, engine: Any | None = None) -> None:
        self.engine = engine or dd.DiagramDesignEngine()
        self.studio = self.engine.studio
        self.cache: dict[str, Any] = {}

    # -- discovery --------------------------------------------------------
    def catalogue(self) -> dict[str, Any]:
        return self.engine.catalogue()

    def choose(self, brief: str) -> dict[str, Any]:
        if not brief.strip():
            raise ValueError("brief must not be empty")
        return self.engine.choose(brief)

    def palette(self, seed: str) -> dict[str, Any]:
        if not seed.strip():
            raise ValueError("seed must not be empty")
        return self.engine.palette_for(seed)

    # -- rendering --------------------------------------------------------
    def flowchart(self, title: str, steps: Iterable[str], seed: str = "",
                  subtitle: str = "") -> dict[str, Any]:
        clean = [step.strip() for step in steps if step and step.strip()]
        if not clean:
            raise ValueError("at least one step is required")
        nodes = [dd.DiagramNode(f"n{index}", label, kind="step")
                 for index, label in enumerate(clean, start=1)]
        edges = [dd.DiagramEdge(nodes[i].node_id, nodes[i + 1].node_id)
                 for i in range(len(nodes) - 1)]
        artifact = self.studio.build(
            dd.DiagramSpec(title=title or "Flowchart", diagram_type="flowchart",
                           nodes=nodes, edges=edges, subtitle=subtitle),
        )
        return self._package(artifact, seed)

    def from_brief(self, brief: str, nodes: Iterable[dict[str, Any]],
                   edges: Iterable[dict[str, Any]] = (),
                   title: str = "", seed: str = "") -> dict[str, Any]:
        """Choose the diagram family from the brief, then render supplied nodes."""
        choice = self.choose(brief)
        built_nodes = [
            dd.DiagramNode(str(node.get("id") or f"n{i}"),
                           str(node.get("label", node.get("id", ""))),
                           kind=str(node.get("kind", "step")))
            for i, node in enumerate(nodes, start=1)
        ]
        if not built_nodes:
            raise ValueError("at least one node is required")
        built_edges = [
            dd.DiagramEdge(str(edge["source"]), str(edge["target"]),
                           label=str(edge.get("label", "")),
                           style=str(edge.get("style", "solid")))
            for edge in edges
        ]
        artifact = self.studio.build(dd.DiagramSpec(
            title=title or brief.strip().capitalize(),
            diagram_type=choice["type"],
            nodes=built_nodes, edges=built_edges,
        ))
        packaged = self._package(artifact, seed)
        packaged["selection"] = choice
        return packaged

    def from_mermaid(self, source: str, title: str = "Imported diagram") -> dict[str, Any]:
        if "graph" not in source and "flowchart" not in source:
            raise ValueError("mermaid source must contain a graph/flowchart header")
        return self._package(self.studio.from_mermaid(source, title=title))

    def restyle(self, diagram_id: str, seed: str) -> dict[str, Any]:
        artifact = self.cache.get(diagram_id)
        if artifact is None:
            raise KeyError(diagram_id)
        restyled = self.studio.restyle(artifact, seed)
        packaged = self._package(restyled, seed)
        self.cache[packaged["diagram_id"]] = restyled
        return packaged

    def _package(self, artifact: Any, seed: str = "") -> dict[str, Any]:
        diagram_id = f"dg-{len(self.cache) + 1:04d}"
        self.cache[diagram_id] = artifact
        payload = artifact.summary()
        payload.update({
            "diagram_id": diagram_id,
            "svg": artifact.svg,
            "html": artifact.html,
            "theme": {"seed": seed or artifact.theme.palette.seed,
                      "paper": artifact.theme.palette.paper,
                      "ink": artifact.theme.palette.ink},
            "validation": {"passed": artifact.report.passed,
                           "score": artifact.report.score,
                           "issues": [issue.as_dict() for issue in artifact.report.issues]},
            "self_contained": "<script src" not in artifact.html
                              and 'xmlns="http://www.w3.org/2000/svg"' in artifact.svg,
        })
        return payload


def attach_explainer(pack: dict[str, Any], topic: str,
                     service: DiagramService | None = None) -> dict[str, Any]:
    """Attach one explainer diagram to a generated content pack.

    Called by ``app.services.content.generate_content_pack`` so the diagram is
    part of the pack rather than a separate request the operator has to make.
    Failures never block content generation.
    """
    service = service or get_service()
    scene_plan = pack.get("scene_plan") or []
    steps = [
        str(scene.get("visual") or scene.get("on_screen_text") or "").strip()[:48]
        for scene in scene_plan
        if isinstance(scene, dict)
    ]
    steps = [step for step in steps if step][:6]
    if not steps:
        steps = [f"{topic} explained", "Key evidence", "What it means for you"]
    try:
        diagram = service.flowchart(f"{topic} — explainer", steps)
    except Exception as exc:  # pragma: no cover - never block content
        return {**pack, "explainer_diagram": {"error": f"{type(exc).__name__}: {exc}"}}
    return {
        **pack,
        "explainer_diagram": {
            "diagram_id": diagram["diagram_id"],
            "type": diagram["type"],
            "title": diagram["title"],
            "nodes": diagram["nodes"],
            "svg": diagram["svg"],
            "html": diagram["html"],
            "markdown": f"![{diagram['title']}](data:image/svg+xml;utf8,{diagram['svg']})",
            "validation": diagram["validation"],
        },
    }


_service: DiagramService | None = None


def get_service() -> DiagramService:
    global _service
    if _service is None:
        _service = DiagramService()
    return _service


def reset_service(service: DiagramService | None = None) -> DiagramService:
    global _service
    _service = service or DiagramService()
    return _service


# ── REST surface ──────────────────────────────────────────────────────────

if _ROUTER_AVAILABLE:

    class NodeModel(BaseModel):  # type: ignore[misc]
        id: str = Field(min_length=1)
        label: str = ""
        kind: str = "step"

    class EdgeModel(BaseModel):  # type: ignore[misc]
        source: str = Field(min_length=1)
        target: str = Field(min_length=1)
        label: str = ""
        style: str = "solid"

    class FlowchartRequest(BaseModel):  # type: ignore[misc]
        title: str = Field(min_length=1)
        steps: list[str] = Field(min_length=1)
        seed: str = ""
        subtitle: str = ""

    class BriefRequest(BaseModel):  # type: ignore[misc]
        brief: str = Field(min_length=3)
        nodes: list[NodeModel] = Field(default_factory=list)
        edges: list[EdgeModel] = Field(default_factory=list)
        title: str = ""
        seed: str = ""

    class MermaidRequest(BaseModel):  # type: ignore[misc]
        source: str = Field(min_length=3)
        title: str = "Imported diagram"

    class RestyleRequest(BaseModel):  # type: ignore[misc]
        diagram_id: str = Field(min_length=1)
        seed: str = Field(min_length=1)

    router = APIRouter(prefix="/api/v1/diagrams", tags=["VyralX Diagram Design"])

    @router.get("/catalogue")
    def catalogue() -> dict[str, Any]:
        return get_service().catalogue()

    @router.get("/choose")
    def choose(brief: str) -> dict[str, Any]:
        try:
            return get_service().choose(brief)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/palette")
    def palette(seed: str) -> dict[str, Any]:
        try:
            return get_service().palette(seed)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/flowchart")
    def flowchart(request: FlowchartRequest) -> dict[str, Any]:
        try:
            return get_service().flowchart(request.title, request.steps,
                                           seed=request.seed,
                                           subtitle=request.subtitle)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/render")
    def render(request: BriefRequest) -> dict[str, Any]:
        try:
            return get_service().from_brief(
                request.brief,
                [node.model_dump() for node in request.nodes],
                [edge.model_dump() for edge in request.edges],
                title=request.title, seed=request.seed,
            )
        except (ValueError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/mermaid")
    def mermaid(request: MermaidRequest) -> dict[str, Any]:
        try:
            return get_service().from_mermaid(request.source, title=request.title)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/restyle")
    def restyle(request: RestyleRequest) -> dict[str, Any]:
        try:
            return get_service().restyle(request.diagram_id, request.seed)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/{diagram_id}/html", response_class=HTMLResponse)
    def diagram_html(diagram_id: str) -> Any:
        artifact = get_service().cache.get(diagram_id)
        if artifact is None:
            raise HTTPException(status_code=404, detail=diagram_id)
        return HTMLResponse(content=artifact.html)

else:  # pragma: no cover
    router = None


__all__ = [
    "DiagramService",
    "attach_explainer",
    "dd",
    "get_service",
    "reset_service",
    "router",
]
