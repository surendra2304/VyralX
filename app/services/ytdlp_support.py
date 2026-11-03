"""Shared yt-dlp option helpers.

YouTube challenges datacenter IPs with "Sign in to confirm you're not a bot".
There is no client-side switch that clears it: the request has to carry a
cookie jar from a signed-in browser. Every yt-dlp call site resolves that jar
through :func:`cookies_file` so a single file enables the whole pipeline.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT = Path("./data/youtube_cookies.txt")


def _usable(path: Path) -> bool:
    """True when *path* looks like a real Netscape cookie jar.

    An empty template (header line only) is not usable and would otherwise make
    every yt-dlp call fail with a confusing parser error.
    """
    try:
        if not path.is_file() or path.stat().st_size < 64:
            return False
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for _ in range(50):
                line = handle.readline()
                if not line:
                    break
                if line.startswith("#") or not line.strip():
                    continue
                if line.count("\t") >= 6:
                    return True
        return False
    except OSError:
        return False


def cookies_file() -> str | None:
    """Return the path to a usable Netscape cookie jar, or ``None``.

    ``YOUTUBE_COOKIES_FILE`` wins over the app setting so an operator can point
    a single host at a rotated jar without editing ``.env``.
    """
    override = os.environ.get("YOUTUBE_COOKIES_FILE", "").strip()
    if override:
        candidate = Path(override).expanduser()
        if _usable(candidate):
            return str(candidate)
        log.warning("YOUTUBE_COOKIES_FILE is set but unusable: %s", candidate)

    candidate = _DEFAULT
    try:
        from app.config import get_settings

        candidate = Path(get_settings().youtube_cookies_file).expanduser()
    except Exception:  # settings unavailable (script context, partial config)
        pass
    if _usable(candidate):
        return str(candidate)
    return None


def with_cookies(opts: dict[str, Any]) -> dict[str, Any]:
    """Inject ``cookiefile`` into a yt-dlp options dict when a jar exists."""
    jar = cookies_file()
    if jar:
        opts.setdefault("cookiefile", jar)
    return opts
