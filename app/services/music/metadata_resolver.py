from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ResolvedMetadata:
    title: str
    artist_name: str
    album_name: str | None = None
    album_artist_name: str | None = None
    track_number: int | None = None
    disc_number: int | None = None
    release_date: str | None = None
    duration_ms: int | None = None

    artist_mbid: str | None = None
    artist_sort_name: str | None = None

    album_mbid: str | None = None
    release_mbid: str | None = None
    release_group_mbid: str | None = None
    recording_mbid: str | None = None

    cover_art_url: str | None = None

    youtube_uploader: str | None = None
    youtube_url: str | None = None

    language_code: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist_name": self.artist_name,
            "album_name": self.album_name,
            "album_artist_name": self.album_artist_name,
            "artist_mbid": self.artist_mbid,
            "artist_sort_name": self.artist_sort_name,
            "album_mbid": self.album_mbid,
            "release_mbid": self.release_mbid,
            "release_group_mbid": self.release_group_mbid,
            "recording_mbid": self.recording_mbid,
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "release_date": self.release_date,
            "duration_ms": self.duration_ms,
            "cover_art_url": self.cover_art_url,
            "youtube_uploader": self.youtube_uploader,
            "youtube_url": self.youtube_url,
            "language_code": self.language_code,
        }


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    return re.sub(r"\s+", " ", value)


def _first(*values: Any) -> str | None:
    for value in values:
        cleaned = _clean(value)
        if cleaned:
            return cleaned
    return None


def _positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        value = int(value)
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def _duration_ms(value: Any) -> int | None:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    if value < 10000:
        return int(round(value * 1000))
    return int(round(value))


def _extract_youtube_title(title: str | None) -> dict[str, str | None]:
    title = _clean(title)
    if not title:
        return {"title": None, "artist": None, "album": None}

    parts = [_clean(part) for part in re.split(r"\s*\|\s*", title)]
    parts = [part for part in parts if part]

    if len(parts) >= 3:
        return {"title": parts[0], "artist": parts[1], "album": parts[2]}
    if len(parts) == 2:
        return {"title": parts[0], "artist": parts[1], "album": None}

    dash_match = re.match(r"^\s*(.+?)\s+[–—-]\s+(.+?)\s*$", title)
    if dash_match:
        return {
            "title": _clean(dash_match.group(1)),
            "artist": _clean(dash_match.group(2)),
            "album": None,
        }

    return {"title": title, "artist": None, "album": None}


def resolve_metadata(
    musicbrainz: dict[str, Any],
    youtube: dict[str, Any],
) -> ResolvedMetadata:
    musicbrainz = musicbrainz or {}
    youtube = youtube or {}

    parsed_title = _extract_youtube_title(youtube.get("title"))

    title = _first(
        musicbrainz.get("title"),
        youtube.get("title"),
        parsed_title.get("title"),
    ) or "Unknown Title"

    artist = _first(
        musicbrainz.get("artist_name"),
        youtube.get("artist"),
        youtube.get("creator"),
        parsed_title.get("artist"),
        youtube.get("uploader"),
    ) or "Unknown Artist"

    album = _first(
        musicbrainz.get("album_name"),
        youtube.get("album"),
        parsed_title.get("album"),
    )

    album_artist = _first(
        musicbrainz.get("album_artist_name"),
        musicbrainz.get("artist_name"),
        youtube.get("album_artist"),
        artist,
    ) or artist

    return ResolvedMetadata(
        title=title,
        artist_name=artist,
        album_name=album,
        album_artist_name=album_artist,
        track_number=(
            _positive_int(musicbrainz.get("track_number"))
            or _positive_int(youtube.get("track_number"))
        ),
        disc_number=(
            _positive_int(musicbrainz.get("disc_number"))
            or _positive_int(youtube.get("disc_number"))
        ),
        release_date=_first(
            musicbrainz.get("release_date"),
            youtube.get("release_date"),
        ),
        duration_ms=(
            _duration_ms(musicbrainz.get("duration_ms"))
            or _duration_ms(youtube.get("duration"))
        ),
        artist_mbid=_clean(musicbrainz.get("artist_mbid")),
        artist_sort_name=_first(
            musicbrainz.get("artist_sort_name"),
            artist,
        ),
        album_mbid=_clean(musicbrainz.get("album_mbid")),
        release_mbid=_clean(musicbrainz.get("release_mbid")),
        release_group_mbid=_clean(musicbrainz.get("release_group_mbid")),
        recording_mbid=_clean(
            musicbrainz.get("mbid")
            or musicbrainz.get("recording_mbid")
        ),
        cover_art_url=_first(
            musicbrainz.get("cover_art_url"),
            youtube.get("thumbnail"),
        ),
        youtube_uploader=_clean(youtube.get("uploader")),
        youtube_url=_first(
            youtube.get("webpage_url"),
            youtube.get("url"),
        ),
        language_code=_clean(musicbrainz.get("language_code")),
    )