from __future__ import annotations

import asyncio
import re
import time
from typing import Any


_ALLOWED_FILTERS = {"songs", "videos", "albums", "artists", "playlists", "channels"}
_CACHE_TTL_SECONDS = 90
_CACHE: dict[tuple[str, str, int], tuple[float, list[dict[str, Any]]]] = {}
_CACHE_LOCK = asyncio.Lock()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (str, int, float)):
        value = str(value).strip()
        return value or None
    return None


def _duration_ms(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value * 1000)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parts = [int(part) for part in value.strip().split(":")]
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + part
        return seconds * 1000
    except (TypeError, ValueError):
        return None


def _artists(value: Any) -> tuple[str | None, str | None]:
    if not isinstance(value, list):
        return None, None
    names: list[str] = []
    first_id: str | None = None
    for item in value:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"))
        if name:
            names.append(name)
        if first_id is None:
            first_id = _text(item.get("id") or item.get("browseId"))
    return (", ".join(names) or None), first_id


def _thumbnail(value: Any) -> str | None:
    if not isinstance(value, list):
        return None
    for item in reversed(value):
        if isinstance(item, dict):
            url = _text(item.get("url"))
            if url and url.startswith(("https://", "http://")):
                return url
    return None


def _normalize(item: dict[str, Any], filter_name: str) -> dict[str, Any] | None:
    title = _text(item.get("title"))
    if not title:
        return None
    artist, artist_id = _artists(item.get("artists"))
    album_data = item.get("album") if isinstance(item.get("album"), dict) else {}
    video_id = _text(item.get("videoId"))
    browse_id = _text(item.get("browseId"))
    result_type = _text(item.get("resultType")) or filter_name.rstrip("s")
    return {
        "id": video_id or browse_id or f"{result_type}:{title}",
        "video_id": video_id,
        "browse_id": browse_id,
        "result_type": result_type,
        "title": title,
        "artist_name": artist,
        "artist_id": artist_id,
        "album_name": _text(album_data.get("name")),
        "album_id": _text(album_data.get("id")),
        "duration_ms": _duration_ms(item.get("duration_seconds") or item.get("duration")),
        "thumbnail_url": _thumbnail(item.get("thumbnails")),
        "year": _text(item.get("year")),
        "is_explicit": bool(item.get("isExplicit", False)),
        "source": "youtube_music",
    }


def _search_sync(query: str, filter_name: str, limit: int) -> list[dict[str, Any]]:
    # Lazy import means AM Music's normal startup still works when the optional
    # provider package has not been installed yet.
    try:
        from ytmusicapi import YTMusic
    except ImportError as exc:
        raise RuntimeError("YouTube Music metadata support is not installed. Install requirements.txt.") from exc

    client = YTMusic()
    # ytmusicapi does not expose a stable dedicated channel filter in every
    # version. Search broadly for channels and keep channel-like results only.
    provider_filter = None if filter_name == "channels" else filter_name
    raw_items = client.search(query, filter=provider_filter, limit=min(50, limit * 3) if filter_name == "channels" else limit)
    if filter_name == "channels":
        raw_items = [
            item for item in (raw_items or [])
            if isinstance(item, dict)
            and str(item.get("resultType") or item.get("category") or "").casefold() in {"channel", "artist"}
        ]
    normalized: list[dict[str, Any]] = []
    for item in raw_items or []:
        if isinstance(item, dict):
            row = _normalize(item, filter_name)
            if row:
                normalized.append(row)
    return normalized[:limit]


async def search_youtube_music(query: str, filter_name: str = "songs", limit: int = 20) -> list[dict[str, Any]]:
    query = re.sub(r"\s+", " ", query).strip()
    if not query:
        return []
    if filter_name not in _ALLOWED_FILTERS:
        raise ValueError("Unsupported YouTube Music search filter.")
    limit = max(1, min(int(limit), 50))
    key = (query.casefold(), filter_name, limit)
    now = time.monotonic()
    async with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached and now - cached[0] < _CACHE_TTL_SECONDS:
            return cached[1]
    items = await asyncio.to_thread(_search_sync, query, filter_name, limit)
    async with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), items)
        # Keep the in-memory cache bounded.
        if len(_CACHE) > 256:
            oldest = sorted(_CACHE, key=lambda item: _CACHE[item][0])[:64]
            for old_key in oldest:
                _CACHE.pop(old_key, None)
    return items
