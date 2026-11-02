"""Discovery of viral Shorts that match the VyralX channel style.

VyralX's four live uploads are all the same format: a 15-55 second vertical
clip that lands one payoff - an unexpected plot twist, a precision stunt,
relatable school comedy, or a luxury/restaurant parody - re-cut with commentary
and subtitles.

This module finds that exact style of clip. Three source pools are combined, in
priority order:

* the Shorts tabs of the five creators the channel's first uploads came from;
* YouTube's recommendation graph rooted at those exact clips;
* style searches and clip channels, only as a top-up.

Candidates are ranked by demonstrated reach, momentum, engagement and format
fit. Two rights policies are supported:

``reuse_licensed`` (strict)
    Only clips published under a Creative Commons reuse licence.
``transformative`` (default)
    Follow the channel's existing model - original commentary, subtitles and
    attribution on every clip - and record the operator's policy attestation on
    the source row instead of pretending a licence exists.
"""
from __future__ import annotations

import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

import httpx
import yt_dlp

from app.config import get_settings

log = logging.getLogger("vyralx.viral_discovery")

# YouTube search filters.
CC_FILTER = "EgIwAQ%3D%3D"

STYLE_LANES: list[dict[str, Any]] = [
    {"query": "#shorts unexpected plot twist", "category": "VIRAL",
     "hook": "WAIT FOR THE PLOT TWIST",
     "keywords": {"plot twist", "unexpected", "wait for it", "twist", "ending"}},
    {"query": "#shorts insane stunt", "category": "VIRAL",
     "hook": "MILLIMETER PERFECT",
     "keywords": {"stunt", "precision", "insane", "perfect", "parkour", "jump"}},
    {"query": "#shorts funny school moment", "category": "COMEDY",
     "hook": "MAIN CHARACTER ENERGY",
     "keywords": {"school", "class", "teacher", "student", "relatable", "funny"}},
    {"query": "#shorts expensive restaurant", "category": "COMEDY",
     "hook": "THE BILL WAS HOW MUCH",
     "keywords": {"expensive", "restaurant", "luxury", "rich", "bill", "dinner"}},
    {"query": "#shorts wait for it", "category": "VIRAL",
     "hook": "WAIT FOR IT",
     "keywords": {"wait for it", "moment", "unexpected", "ending"}},
    {"query": "#shorts perfect timing", "category": "VIRAL",
     "hook": "PERFECTLY TIMED",
     "keywords": {"perfect", "timing", "satisfying", "smooth"}},
    {"query": "#shorts crazy moment caught on camera", "category": "VIRAL",
     "hook": "NOBODY SAW THIS COMING",
     "keywords": {"caught on camera", "crazy", "moment", "unbelievable"}},
    {"query": "#shorts instant regret", "category": "COMEDY",
     "hook": "INSTANT REGRET",
     "keywords": {"regret", "fail", "oops", "funny"}},
    {"query": "#shorts oddly satisfying", "category": "VIRAL",
     "hook": "ODDLY SATISFYING",
     "keywords": {"satisfying", "oddly", "smooth", "asmr"}},
    {"query": "#shorts extreme sports", "category": "SPORTS",
     "hook": "DO NOT TRY THIS",
     "keywords": {"extreme", "sports", "trick", "skills", "insane"}},
    {"query": "#shorts magic trick revealed", "category": "VIRAL",
     "hook": "HOW IS THAT POSSIBLE",
     "keywords": {"magic", "trick", "illusion", "revealed"}},
    {"query": "#shorts funny reaction", "category": "COMEDY",
     "hook": "HIS REACTION SAYS IT ALL",
     "keywords": {"reaction", "funny", "laugh", "shock"}},
    {"query": "#shorts viral funny moment", "category": "COMEDY",
     "hook": "WAIT FOR IT",
     "keywords": {"viral", "funny", "moment", "comedy"}},
    {"query": "#shorts fail", "category": "COMEDY",
     "hook": "HE REALLY DID THAT",
     "keywords": {"fail", "funny", "oops", "crash"}},
]

STYLE_CHANNELS: list[tuple[str, str]] = [
    ("failarmy", "COMEDY"),
    ("peopleareawesome", "VIRAL"),
    ("ViralHog", "VIRAL"),
    ("TheFails", "COMEDY"),
    ("StoryfulViral", "VIRAL"),
]

REUSE_LICENSE_MARKERS = ("creative commons",)

# The clips the channel's first four uploads were built from. Their YouTube
# recommendation graph is the most accurate "more videos like this" signal we
# have, so every cycle walks it for new candidates.
SEED_VIDEO_IDS = (
    "sOZrJUkCLYU",   # Wait For The Most Unexpected Plot Twist
    "k--pkJcePTM",   # Millimeter-Perfect Extreme Stunt
    "heI4DLab-l8",   # Maximum Main Character Energy In School
    "A_Q2qpbHrqo",   # The $9,999,999 Michelin Restaurant
    "hx265ujsLVU",   # Pure Chaos Caught on Camera
)

# The creators behind those four uploads. Their Shorts tabs are the highest
# signal pool there is: same format, same pacing, same payoff, and their
# back-catalogue is deep. Every cycle reads these first.
SEED_CREATOR_CHANNELS: tuple[tuple[str, str, str], ...] = (
    ("CuRe 구래", "UCkLNHZZsC3LKdUAroKNwOOw", "COMEDY"),
    ("Red Bull", "UCblfuW_4rakIf2h6aqANefA", "SPORTS"),
    ("nishi tiwari", "UC8238GT1G2CmJ9bsmKpL-jw", "COMEDY"),
    ("boxtoxtv", "UCCfKlFlKYBxZ-UU2dWc17IQ", "VIRAL"),
    ("H&T Official", "UCYCh5_-In6wtzWR-s_kM03w", "VIRAL"),
)

_RELATED_PATTERN = re.compile(r'"videoId":"([A-Za-z0-9_-]{11})"')


@dataclass
class Candidate:
    video_id: str
    title: str
    channel: str
    duration: float
    view_count: int
    like_count: int
    upload_date: str
    license: str
    category: str
    hook: str
    score: float
    tags: list[str] = field(default_factory=list)
    description: str = ""
    webpage_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "video_id": self.video_id,
            "title": self.title,
            "channel": self.channel,
            "duration": self.duration,
            "view_count": self.view_count,
            "category": self.category,
            "hook": self.hook,
            "score": self.score,
            "url": self.webpage_url or f"https://www.youtube.com/watch?v={self.video_id}",
        }


def _parse_upload_date(raw: str) -> date | None:
    try:
        return datetime.strptime(str(raw), "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def is_reusable(info: dict[str, Any]) -> bool:
    """True only when the uploader published the clip under a reuse licence."""
    license_name = str(info.get("license") or "").strip().casefold()
    return any(marker in license_name for marker in REUSE_LICENSE_MARKERS)


def score_candidate(info: dict[str, Any], keywords: set[str]) -> float:
    """Rank by demonstrated reach, momentum, engagement and format fit."""
    views = int(info.get("view_count") or 0)
    likes = int(info.get("like_count") or 0)
    comments = int(info.get("comment_count") or 0)
    duration = float(info.get("duration") or 0.0)
    uploaded = _parse_upload_date(info.get("upload_date") or "")
    age_days = max(1, (date.today() - uploaded).days) if uploaded else 365
    velocity = views / age_days

    score = 0.55 * math.log10(max(views, 10))
    score += 0.35 * math.log10(max(velocity, 1))
    if views:
        score += min(0.5, (likes / views) * 20)
        score += min(0.3, (comments / views) * 120)
    # The channel's sweet spot is 18-50 seconds with a single payoff.
    if 18 <= duration <= 50:
        score += 0.6
    elif 12 <= duration <= 58:
        score += 0.25
    elif duration > 60:
        score -= 1.5

    title = str(info.get("title") or "").casefold()
    if any(word in title for word in keywords):
        score += 0.4
    if "#short" in title or "shorts" in title:
        score += 0.1
    # Compilations are long-form; a clip title never says "compilation".
    if any(word in title for word in ("compilation", "best of", "try not to laugh", "part ")):
        score -= 0.8
    return round(score, 3)


def _extract(url: str, limit: int) -> list[dict[str, Any]]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "playlistend": max(1, min(int(limit), 30)),
        "noplaylist": False,
        "ignoreerrors": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        payload = ydl.extract_info(url, download=False)
    if not payload:
        return []
    return [entry for entry in (payload.get("entries") or []) if entry]


def related_video_ids(seed_id: str) -> list[str]:
    """Walk YouTube's recommendation graph from a known-style clip."""
    url = f"https://www.youtube.com/watch?v={seed_id}"
    try:
        response = httpx.get(
            url,
            timeout=30,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            follow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:
        log.info("Related lookup failed for %s: %s", seed_id, type(exc).__name__)
        return []
    ids: list[str] = []
    for match in _RELATED_PATTERN.findall(response.text):
        if match != seed_id and match not in ids:
            ids.append(match)
    return ids


def _video_metadata(video_id: str) -> dict[str, Any] | None:
    try:
        with yt_dlp.YoutubeDL(
            {"quiet": True, "no_warnings": True, "skip_download": True, "ignoreerrors": True}
        ) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
    except Exception:
        return None
    if not isinstance(info, dict):
        return None
    info.setdefault("id", video_id)
    return info


def _lane_for(info: dict[str, Any]) -> dict[str, Any]:
    """Pick the style lane whose keywords best describe a clip."""
    title = str(info.get("title") or "").casefold()
    best = STYLE_LANES[0]
    best_hits = -1
    for lane in STYLE_LANES:
        hits = sum(1 for word in lane["keywords"] if word in title)
        if hits > best_hits:
            best, best_hits = lane, hits
    if best_hits <= 0:
        # Nothing in the title: default to the channel's most common format.
        return next(lane for lane in STYLE_LANES if lane["category"] == "VIRAL")
    return best


def _search(query: str, limit: int, reuse_only: bool) -> list[dict[str, Any]]:
    url = (
        "https://www.youtube.com/results?search_query="
        + query.replace(" ", "%20").replace("#", "%23")
    )
    if reuse_only:
        url += "&sp=" + CC_FILTER
    return _extract(url, limit)


def _channel_shorts(handle: str, limit: int) -> list[dict[str, Any]]:
    return _extract(f"https://www.youtube.com/@{handle}/shorts", limit)


def _channel_shorts_by_id(channel_id: str, limit: int) -> list[dict[str, Any]]:
    return _extract(f"https://www.youtube.com/channel/{channel_id}/shorts", limit)


def _lane_by_category(category: str) -> dict[str, Any]:
    return next(
        (lane for lane in STYLE_LANES if lane["category"] == category), STYLE_LANES[0]
    )


def _candidate_from(info: dict[str, Any], lane: dict[str, Any], reuse_only: bool) -> Candidate | None:
    video_id = str(info.get("id") or "").strip()
    if not video_id:
        return None
    license_name = str(info.get("license") or "").strip()
    if reuse_only and not is_reusable(info):
        return None
    return Candidate(
        video_id=video_id,
        title=str(info.get("title") or "").strip(),
        channel=str(info.get("uploader") or info.get("channel") or "").strip(),
        duration=round(float(info.get("duration") or 0.0), 2),
        view_count=int(info.get("view_count") or 0),
        like_count=int(info.get("like_count") or 0),
        upload_date=str(info.get("upload_date") or ""),
        license=license_name or "transformative_commentary",
        category=lane["category"],
        hook=lane["hook"],
        score=score_candidate(info, lane["keywords"]),
        tags=[str(t) for t in (info.get("tags") or [])][:8],
        description=str(info.get("description") or "")[:1200],
        webpage_url=str(info.get("webpage_url") or ""),
    )


def _accept(
    info: dict[str, Any],
    lane: dict[str, Any],
    reuse_only: bool,
    found: dict[str, Candidate],
    exclude: set[str],
    min_seconds: float,
    max_seconds: float,
    min_views: int,
    bonus: float = 0.0,
) -> bool:
    candidate = _candidate_from(info, lane, reuse_only)
    if candidate is None or candidate.video_id in exclude:
        return False
    if not (min_seconds <= candidate.duration <= max_seconds):
        return False
    if candidate.view_count < min_views:
        return False
    if bonus:
        candidate.score = round(candidate.score + bonus, 3)
    existing = found.get(candidate.video_id)
    if existing is None or candidate.score > existing.score:
        found[candidate.video_id] = candidate
        return True
    return False


def _seed_channel_pool(
    category: str,
    channel_id: str,
    limit: int,
    reuse_only: bool,
    found: dict[str, Candidate],
    exclude: set[str],
    min_seconds: float,
    max_seconds: float,
    min_views: int,
) -> int:
    """Read one seed creator's Shorts tab. Returns how many were accepted."""
    lane = _lane_by_category(category)
    try:
        results = _channel_shorts_by_id(channel_id, limit)
    except Exception as exc:
        log.info("Seed channel %s unavailable: %s", channel_id, type(exc).__name__)
        return 0
    accepted = 0
    for info in results:
        # Proven format: the clip stream is literally the one the channel copies.
        if _accept(
            info, lane, reuse_only, found, exclude,
            min_seconds, max_seconds, min_views, bonus=0.5,
        ):
            accepted += 1
    return accepted


def discover_candidates(
    limit: int = 12,
    exclude_ids: set[str] | None = None,
    seed_ids: set[str] | None = None,
    min_views: int = 500_000,
    max_seconds: float = 58.0,
    min_seconds: float = 10.0,
) -> list[Candidate]:
    """Find clips that are genuinely similar to the channel's first uploads.

    Pools, in priority order:

    1. the Shorts tabs of the five creators the channel's first uploads came from;
    2. YouTube's recommendation graph rooted at those exact clips;
    3. style searches, only as a top-up when the first two are thin.
    """
    settings = get_settings()
    reuse_only = str(getattr(settings, "viral_source_policy", "transformative")) == "reuse_licensed"
    exclude = {str(value) for value in (exclude_ids or set()) if value}
    found: dict[str, Candidate] = {}

    # 1. Seed creators' Shorts tabs - same format, proven engagement.
    channels = list(SEED_CREATOR_CHANNELS)
    with ThreadPoolExecutor(max_workers=min(5, len(channels))) as pool:
        futures = [
            pool.submit(
                _seed_channel_pool, category, channel_id, 40, reuse_only,
                found, exclude, min_seconds, max_seconds, min_views,
            )
            for _name, channel_id, category in channels
        ]
        for future in futures:
            try:
                future.result(timeout=180)
            except Exception as exc:
                log.info("Seed pool failed: %s", type(exc).__name__)

    # 2. Walk the recommendation graph from the source clips of the first uploads.
    seeds: list[str] = []
    for value in list(seed_ids or []) + list(SEED_VIDEO_IDS):
        if value and value not in seeds and value not in exclude:
            seeds.append(value)
    seeds = seeds[:5]

    related: list[str] = []
    if seeds:
        with ThreadPoolExecutor(max_workers=min(5, len(seeds))) as pool:
            for ids in pool.map(related_video_ids, seeds):
                for video_id in ids:
                    if video_id not in related and video_id not in exclude:
                        related.append(video_id)

    to_inspect = [vid for vid in related if vid not in found][:40]
    metas: list[dict[str, Any]] = []
    if to_inspect:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for info in pool.map(_video_metadata, to_inspect):
                if info:
                    metas.append(info)

    for info in metas:
        _accept(
            info, _lane_for(info), reuse_only, found, exclude,
            min_seconds, max_seconds, min_views,
        )

    # 3. Top up with style searches when the pools above are thin.
    if len(found) < max(3, limit // 2):
        tasks: list[tuple[dict[str, Any], Any]] = [
            (lane, lambda lane=lane: _search(lane["query"], 18, reuse_only))
            for lane in STYLE_LANES[:6]
        ]
        handles = [
            handle.strip().lstrip("@")
            for handle in str(getattr(settings, "viral_channel_handles", "") or "").split(",")
            if handle.strip()
        ]
        for handle in handles[:3]:
            category = next(
                (cat for name, cat in STYLE_CHANNELS if name.casefold() == handle.casefold()), "VIRAL"
            )
            lane = _lane_by_category(category)
            tasks.append((lane, lambda handle=handle: _channel_shorts(handle, 20)))

        with ThreadPoolExecutor(max_workers=4) as pool:
            futures = {pool.submit(fetch): lane for lane, fetch in tasks}
            for future, lane in futures.items():
                try:
                    results = future.result(timeout=120)
                except Exception as exc:
                    log.info("Discovery pool failed (%s): %s", lane["query"], type(exc).__name__)
                    continue
                for info in results:
                    _accept(
                        info, lane, reuse_only, found, exclude,
                        min_seconds, max_seconds, min_views,
                    )

    ranked = sorted(found.values(), key=lambda item: item.score, reverse=True)
    log.info(
        "Discovered %d %s candidates (seed channels=%d, graph seeds=%d, inspected=%d)",
        len(ranked), "reusable-licensed" if reuse_only else "style-matched",
        len(channels), len(seeds), len(metas),
    )
    return ranked[: max(1, int(limit))]


def used_source_video_ids(db: Any) -> set[str]:
    """Video ids already pulled into VyralX so nothing is republished twice."""
    from sqlalchemy import select

    from app.models import Source

    used: set[str] = set()
    for url in db.scalars(select(Source.source_url)).all():
        text = str(url or "")
        if "v=" in text:
            used.add(text.rsplit("v=", 1)[-1].split("&")[0])
        elif "youtu.be/" in text:
            used.add(text.rsplit("youtu.be/", 1)[-1].split("?")[0])
    return used


def utc_today() -> date:
    return datetime.now(timezone.utc).date()
