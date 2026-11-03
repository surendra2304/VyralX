"""YouTube Data API v3 fallback for source-video discovery.

yt-dlp is the primary discovery path in :mod:`app.services.viral_discovery`, but
it is regularly blocked on datacenter IPs with "Sign in to confirm you're not a
bot". This module re-implements the same discovery pass on the official YouTube
Data API using the channel's existing OAuth token, so a blocked extraction does
not stop the autopilot.

Quota cost of the default path (one discovery cycle):

* :func:`channel_uploads` - 1 unit per 50 uploads read;
* :func:`video_details` - 1 unit per 50 videos inspected;
* :func:`search_comedy_shorts` - 100 units per call, only used when
  ``discover_via_api(..., use_search=True)`` is explicitly requested.

Every function degrades to an empty result rather than raising when the API
rejects a request. Discovery is best-effort; the caller can try another source.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

# 100 uploads per seed channel = two 50-item pages = 2 quota units each. Bounded
# so a playlist with thousands of uploads cannot run away with the daily quota.
_UPLOADS_PER_CHANNEL = 100
_MAX_LOOKUP_IDS = 500
_MAX_SEARCH_QUERIES = 3
_SEARCH_WINDOW_DAYS = 540  # ~18 months

_THUMBNAIL_ORDER = ("maxres", "standard", "high", "medium", "default")

_ISO_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)

SeedSpec = str | tuple[str, str] | tuple[str, str, str]


def _uploads_playlist_id(channel_id: str) -> str:
    """Return the ``UU...`` uploads playlist for a ``UC...`` channel id."""
    value = str(channel_id or "").strip()
    if not value:
        return ""
    if value.startswith("UU"):
        return value
    if value.startswith("UC") and len(value) > 2:
        return "UU" + value[2:]
    log.warning("Not a YouTube channel id: %s", channel_id)
    return ""


def _parse_iso_duration(value: Any) -> int:
    """Convert an ISO-8601 duration (``PT1M2S``) into whole seconds.

    Only the fields YouTube actually emits are supported (days, hours, minutes,
    seconds). Unknown or malformed values return 0; no external dependency.
    """
    match = _ISO_DURATION.match(str(value or "").strip())
    if match is None:
        return 0
    days = int(match.group("days") or 0)
    hours = int(match.group("hours") or 0)
    minutes = int(match.group("minutes") or 0)
    seconds = float(match.group("seconds") or 0)
    return int(days * 86_400 + hours * 3_600 + minutes * 60 + seconds)


def _thumbnail_url(thumbnails: Any) -> str:
    """Pick the highest-resolution thumbnail URL that YouTube returned."""
    if not isinstance(thumbnails, dict):
        return ""
    for key in _THUMBNAIL_ORDER:
        node = thumbnails.get(key)
        if isinstance(node, dict) and node.get("url"):
            return str(node["url"])
    return ""


def _int_value(value: Any, default: int = 0) -> int:
    """Parse an API counter that arrives as a string, never raising on garbage."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact_upload_date(published_at: Any) -> str:
    """Convert ``2025-03-04T12:00:00Z`` to the ``YYYYMMDD`` shape yt-dlp uses."""
    text = str(published_at or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10].replace("-", "")
    return ""


def _normalise_seeds(seeds: Iterable[SeedSpec] | str) -> list[tuple[str, str, str]]:
    """Accept channel ids or ``(name, channel_id[, category])`` seed tuples."""
    if isinstance(seeds, str):
        seeds = [seeds]
    entries: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for item in seeds:
        name = channel_id = ""
        category = "COMEDY"
        if isinstance(item, str):
            name = channel_id = item
        elif isinstance(item, (tuple, list)):
            if len(item) >= 3:
                name, channel_id, category = item[0], item[1], item[2]
            elif len(item) == 2:
                name, channel_id = item[0], item[1]
            else:
                continue
        else:
            continue
        channel_id = str(channel_id or "").strip()
        if not channel_id or channel_id in seen:
            continue
        seen.add(channel_id)
        entries.append(
            (str(name or channel_id).strip(), channel_id, str(category or "COMEDY").upper())
        )
    return entries


def _published_video_ids() -> set[str]:
    """Best-effort ids already pulled into VyralX, from the configured database.

    Returns an empty set when the database or the helper is unavailable; discovery
    must not fail just because a developer is running without the production DB.
    """
    try:
        from app.database import SessionLocal
        from app.services.viral_discovery import used_source_video_ids
    except Exception as exc:
        log.info("Publish DB helper unavailable (%s); skipping exclusion", type(exc).__name__)
        return set()
    try:
        with SessionLocal() as db:
            return used_source_video_ids(db)
    except Exception as exc:
        log.info("Publish DB lookup failed (%s); skipping exclusion", type(exc).__name__)
        return set()


def channel_uploads(
    service: Any, channel_id: str, max_items: int = 50
) -> list[dict[str, Any]]:
    """Read a channel's uploads playlist via ``playlistItems.list``.

    Args:
        service: Authenticated ``googleapiclient`` YouTube v3 resource.
        channel_id: Channel id (``UC...``) or an uploads playlist id (``UU...``).
        max_items: Maximum videos to return; pages of 50 cost one quota unit each.

    Returns:
        ``[{"video_id": str, "snippet": dict}, ...]``. API failures are logged
        and produce an empty list so discovery can fall back again.
    """
    playlist_id = _uploads_playlist_id(channel_id)
    if service is None or not playlist_id:
        return []
    try:
        wanted = max(1, min(int(max_items), 500))
    except (TypeError, ValueError):
        wanted = 50

    items: list[dict[str, Any]] = []
    page_token = ""
    while len(items) < wanted:
        params: dict[str, Any] = {
            "part": "snippet",
            "playlistId": playlist_id,
            "maxResults": min(50, wanted - len(items)),
        }
        if page_token:
            params["pageToken"] = page_token
        try:
            response = service.playlistItems().list(**params).execute()
        except Exception as exc:
            # googleapiclient.errors.HttpError (quota, forbidden, bad playlist) is
            # expected on a blocked or exhausted project; discovery is best-effort.
            log.warning(
                "channel_uploads failed for %s (%s)", channel_id, type(exc).__name__
            )
            break

        page = response.get("items") or []
        for item in page:
            snippet = item.get("snippet") or {}
            resource = snippet.get("resourceId") or {}
            video_id = str(resource.get("videoId") or "").strip()
            if not video_id:
                continue
            items.append({"video_id": video_id, "snippet": snippet})
            if len(items) >= wanted:
                break

        page_token = str(response.get("nextPageToken") or "")
        if not page_token or not page:
            break
    return items


def video_details(service: Any, video_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Fetch public metadata for videos with ``videos.list`` (50 per request).

    Args:
        service: Authenticated ``googleapiclient`` YouTube v3 resource.
        video_ids: Any iterable of ids; duplicates are removed and the lookup is
            capped at 500 ids to bound quota.

    Returns:
        ``{video_id: {"title", "channel", "channel_id", "view_count",
        "duration_seconds", "published_at", "description", "thumbnail"}}``.
        Failed batches are skipped; missing ids are simply absent.
    """
    ids: list[str] = []
    seen: set[str] = set()
    for value in video_ids or ():
        video_id = str(value or "").strip()
        if video_id and video_id not in seen:
            seen.add(video_id)
            ids.append(video_id)
        if len(ids) >= _MAX_LOOKUP_IDS:
            break
    if service is None or not ids:
        return {}

    details: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(ids), 50):
        batch = ids[offset:offset + 50]
        try:
            response = service.videos().list(
                part="snippet,statistics,contentDetails",
                id=",".join(batch),
            ).execute()
        except Exception as exc:
            log.warning(
                "video_details batch failed at offset %d (%s)",
                offset,
                type(exc).__name__,
            )
            continue

        for item in response.get("items") or []:
            video_id = str(item.get("id") or "").strip()
            if not video_id:
                continue
            snippet = item.get("snippet") or {}
            statistics = item.get("statistics") or {}
            content_details = item.get("contentDetails") or {}
            details[video_id] = {
                "title": str(snippet.get("title") or "").strip(),
                "channel": str(snippet.get("channelTitle") or "").strip(),
                "channel_id": str(snippet.get("channelId") or "").strip(),
                "view_count": _int_value(statistics.get("viewCount")),
                "duration_seconds": _parse_iso_duration(content_details.get("duration")),
                "published_at": str(snippet.get("publishedAt") or "").strip(),
                "description": str(snippet.get("description") or ""),
                "thumbnail": _thumbnail_url(snippet.get("thumbnails")),
            }
    return details


def search_comedy_shorts(
    service: Any, query: str, max_results: int = 25
) -> list[dict[str, Any]]:
    """Search recent short comedy videos with ``search.list``.

    This call costs **100 quota units**, so :func:`discover_via_api` only uses it
    when ``use_search=True``. Results are restricted to short videos published
    in the last ~18 months and ordered by view count.

    Returns:
        ``[{"video_id": str, "snippet": dict}, ...]``; API failures return ``[]``.
    """
    text = str(query or "").strip()
    if service is None or not text:
        return []
    try:
        limit = max(1, min(int(max_results), 50))
    except (TypeError, ValueError):
        limit = 25

    published_after = (
        datetime.now(timezone.utc) - timedelta(days=_SEARCH_WINDOW_DAYS)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        response = service.search().list(
            part="snippet",
            q=text,
            type="video",
            videoDuration="short",
            order="viewCount",
            relevanceLanguage="en",
            safeSearch="none",
            publishedAfter=published_after,
            maxResults=limit,
        ).execute()
    except Exception as exc:
        log.warning(
            "search_comedy_shorts failed for %r (%s)", text, type(exc).__name__
        )
        return []

    results: list[dict[str, Any]] = []
    for item in response.get("items") or []:
        video_id = str((item.get("id") or {}).get("videoId") or "").strip()
        if not video_id:
            continue
        results.append({"video_id": video_id, "snippet": item.get("snippet") or {}})
    return results


def discover_via_api(
    seeds: Iterable[SeedSpec] | str | None = None,
    max_candidates: int = 40,
    min_views: int | None = None,
    max_duration: float = 75,
    *,
    use_search: bool = False,
    exclude_ids: Iterable[str] | None = None,
    exclude_published: bool = True,
) -> list[dict[str, Any]]:
    """Discover comedy shorts through the YouTube Data API.

    This is the drop-in replacement for
    :func:`app.services.viral_discovery.discover_candidates` when yt-dlp is
    blocked. Seed channels are read first; an optional ``search.list`` pass tops
    the pool up.

    Args:
        seeds: Channel ids or ``(name, channel_id, category)`` tuples. Defaults
            to ``viral_discovery.SEED_CREATOR_CHANNELS`` (the four comedy
            creators behind the channel's existing uploads).
        max_candidates: Maximum candidates returned.
        min_views: Minimum view count; defaults to settings
            ``viral_min_source_views`` with a 1,000,000 fallback.
        max_duration: Longest accepted source clip in seconds (shorts only).
        use_search: Run ``search.list`` top-up queries. Costs 100 quota units
            per query and is therefore off by default.
        exclude_ids: Extra video ids to reject.
        exclude_published: Exclude ids already stored in the local source DB.

    Returns:
        Candidate dicts in the same shape as
        :meth:`app.services.viral_discovery.Candidate.to_dict` -
        ``video_id, title, channel, duration, view_count, category, hook,
        score, url`` - plus ``channel_id, thumbnail, description,
        published_at``. Sorted by score, highest first.
    """
    try:
        from app.services.viral_discovery import (
            SEED_CREATOR_CHANNELS,
            STYLE_LANES,
            _accept,
            _is_comedy,
            _lane_by_category,
            _lane_for,
        )
    except Exception as exc:
        log.error(
            "viral_discovery is unavailable; cannot match its candidate format (%s)",
            type(exc).__name__,
        )
        return []

    try:
        from app.config import get_settings

        settings = get_settings()
    except Exception as exc:
        log.info("Settings unavailable (%s); using discovery defaults", type(exc).__name__)
        settings = None

    if min_views is None:
        min_views = _int_value(
            getattr(settings, "viral_min_source_views", 1_000_000), 1_000_000
        )
    try:
        minimum_views = max(0, int(min_views))
    except (TypeError, ValueError):
        minimum_views = 0
    try:
        longest = float(max_duration)
    except (TypeError, ValueError):
        longest = 75.0

    reuse_only = (
        str(getattr(settings, "viral_source_policy", "transformative"))
        == "reuse_licensed"
    )
    if reuse_only:
        # videos.list does not expose another creator's licence, so this source
        # cannot prove Creative Commons reuse. Refuse instead of guessing.
        log.warning(
            "viral_source_policy=reuse_licensed: the public Data API cannot verify "
            "a source licence, so API discovery will return no candidates"
        )

    try:
        from app.services.youtube import youtube_service

        service = youtube_service()
    except Exception as exc:
        log.warning("YouTube API service unavailable (%s)", type(exc).__name__)
        return []

    excluded = {
        str(value).strip()
        for value in (exclude_ids or ())
        if str(value).strip()
    }
    if exclude_published:
        excluded |= _published_video_ids()

    # Seeds first, so a video reachable both ways keeps its seed bonus.
    seed_entries = _normalise_seeds(
        SEED_CREATOR_CHANNELS if seeds is None else seeds
    )
    seed_order: dict[str, str] = {}
    fetched_channels = 0
    for _name, channel_id, category in seed_entries:
        lane = _lane_by_category(category)
        if not _is_comedy(lane):
            log.info("Skipping non-comedy seed channel %s (%s)", channel_id, category)
            continue
        fetched_channels += 1
        for row in channel_uploads(service, channel_id, _UPLOADS_PER_CHANNEL):
            video_id = row["video_id"]
            if video_id not in excluded:
                seed_order.setdefault(video_id, category)

    search_order: dict[str, str] = {}
    if use_search:
        queries = [
            str(lane.get("query") or "")
            for lane in STYLE_LANES
            if _is_comedy(lane) and lane.get("query")
        ][:_MAX_SEARCH_QUERIES]
        for query in queries:
            log.info("search.list top-up: %r (100 quota units)", query)
            for row in search_comedy_shorts(service, query, 25):
                video_id = row["video_id"]
                if video_id not in excluded:
                    search_order.setdefault(video_id, query)

    ordered_ids: list[str] = []
    for video_id in list(seed_order) + list(search_order):
        if video_id not in ordered_ids:
            ordered_ids.append(video_id)
    ordered_ids = ordered_ids[:_MAX_LOOKUP_IDS]
    if not ordered_ids:
        log.info("API discovery found no uploads to inspect")
        return []

    details = video_details(service, ordered_ids)
    found: dict[str, Any] = {}
    for video_id in ordered_ids:
        detail = details.get(video_id)
        if not detail:
            continue
        duration = float(detail["duration_seconds"] or 0)
        if duration <= 0:
            # Without contentDetails there is no way to confirm this is a short.
            continue
        info = {
            "id": video_id,
            "title": detail["title"],
            "channel": detail["channel"],
            "view_count": detail["view_count"],
            "duration": duration,
            "upload_date": _compact_upload_date(detail["published_at"]),
            "description": detail["description"],
            # The public API carries no reusable-licence field for other creators.
            "license": "",
        }
        if video_id in seed_order:
            lane = _lane_by_category(seed_order[video_id])
            bonus = 0.5  # Proven format: the same creators the channel copies.
        else:
            lane = _lane_for(info)
            if not _is_comedy(lane):
                # Everything this fallback discovers is intentionally comedy.
                lane = _lane_by_category("COMEDY")
            bonus = 0.0
        _accept(
            info,
            lane,
            reuse_only,
            found,
            excluded,
            0.0,
            longest,
            minimum_views,
            bonus=bonus,
        )

    ranked = sorted(found.values(), key=lambda item: item.score, reverse=True)
    try:
        limit = max(1, int(max_candidates))
    except (TypeError, ValueError):
        limit = 40

    results: list[dict[str, Any]] = []
    for candidate in ranked[:limit]:
        detail = details.get(candidate.video_id) or {}
        payload = candidate.to_dict()
        payload.update(
            {
                "channel_id": detail.get("channel_id", ""),
                "thumbnail": detail.get("thumbnail", ""),
                "description": detail.get("description", ""),
                "published_at": detail.get("published_at", ""),
            }
        )
        results.append(payload)

    log.info(
        "API discovery: channels=%d ids=%d accepted=%d returned=%d search=%s",
        fetched_channels,
        len(ordered_ids),
        len(found),
        len(results),
        "on" if use_search else "off",
    )
    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    from app.services.viral_discovery import SEED_CREATOR_CHANNELS

    discovered = discover_via_api(
        seeds=SEED_CREATOR_CHANNELS,
        exclude_published=False,
    )
    if not discovered:
        print("No API candidates discovered.")
    else:
        print(f"{'video_id':<12} {'views':>12} {'duration':>9}  title")
        print("-" * 78)
        for row in discovered:
            print(
                f"{row['video_id']:<12} "
                f"{row['view_count']:>12,} "
                f"{row['duration']:>8.1f}s  "
                f"{str(row['title'])[:70]}"
            )
