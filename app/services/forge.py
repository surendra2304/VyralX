"""Client integration for Forge, the tool synthesis, code execution, and asset builder of the FRIDAY Universe."""
from __future__ import annotations

import html
import logging
from pathlib import Path
from typing import Any

from app.services.peers import configured_peers, post_peer_json

log = logging.getLogger("vyralx.forge")


def synthesize_visual_badge(
    text: str,
    destination: str | Path,
    *,
    width: int = 1080,
    height: int = 240,
    theme: str = "neon",
) -> Path:
    """Synthesize an SVG graphic lower-third or title badge for video overlays."""
    target = Path(destination).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    clean_text = html.escape(str(text).strip()[:80])

    if "forge" in configured_peers():
        try:
            payload = {
                "source_agent": "vyralx",
                "action": "asset.synthesize_badge",
                "text": clean_text,
                "width": width,
                "height": height,
                "theme": theme,
            }
            response = post_peer_json("forge", "/v1/assets/badge", payload, timeout_seconds=6.0)
            svg_content = response.get("svg")
            if svg_content and "<svg" in svg_content:
                target.write_text(svg_content, encoding="utf-8")
                log.info("Forge visual badge written to %s", target)
                return target
        except Exception as exc:
            log.warning("Forge badge generation failed; generating local SVG: %s", exc)

    # Local high-quality SVG badge generation
    if theme == "gold":
        accent = "#f59e0b"
        bg = "rgba(17, 24, 39, 0.88)"
        border = "#d97706"
    elif theme == "neon":
        accent = "#06b6d4"
        bg = "rgba(15, 23, 42, 0.90)"
        border = "#0ea5e9"
    else:
        accent = "#10b981"
        bg = "rgba(6, 78, 59, 0.90)"
        border = "#059669"

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:{accent};stop-opacity:1" />
      <stop offset="100%" style="stop-color:{border};stop-opacity:1" />
    </linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="120%">
      <feDropShadow dx="0" dy="4" stdDeviation="6" flood-color="#000000" flood-opacity="0.6"/>
    </filter>
  </defs>
  <rect x="60" y="30" width="{width - 120}" height="{height - 60}" rx="24" fill="{bg}" stroke="url(#grad)" stroke-width="4" filter="url(#shadow)" />
  <text x="50%" y="54%" font-family="Montserrat, Arial, sans-serif" font-size="48" font-weight="800" fill="#ffffff" text-anchor="middle" dominant-baseline="middle" letter-spacing="1">
    {clean_text}
  </text>
</svg>"""
    target.write_text(svg, encoding="utf-8")
    return target


def validate_filter_graph(filter_steps: list[str]) -> dict[str, Any]:
    """Validate FFmpeg filtergraph step syntax before execution."""
    if not filter_steps:
        return {"valid": False, "error": "filter_steps cannot be empty"}

    invalid_chars = {";", "\n", "\r"}
    for step in filter_steps:
        if any(c in step for c in invalid_chars):
            return {"valid": False, "error": f"Invalid character in filter step: {step[:30]}"}

    combined = ";".join(filter_steps)
    return {"valid": True, "combined_graph": combined, "steps_count": len(filter_steps)}
