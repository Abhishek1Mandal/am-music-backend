from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class MusicBrainzRecordingError(Exception):
    """Raised when a MusicBrainz recording cannot be retrieved."""


async def get_recording(musicbrainz_id: str) -> dict[str, Any]:
    """
    Fetch a recording from MusicBrainz by recording MBID.
    """

    url = f"{settings.musicbrainz_base_url}/recording/{musicbrainz_id}"

    params = {
        "fmt": "json",
        "inc": "artists+releases+media",
    }

    headers = {
        "User-Agent": settings.musicbrainz_user_agent,
        "Accept": "application/json",
    }

    try:
        async with httpx.AsyncClient(
            timeout=20.0,
            headers=headers,
        ) as client:
            response = await client.get(
                url,
                params=params,
            )

            logger.info(
                "[MUSICBRAINZ] GET %s -> %s",
                response.url,
                response.status_code,
            )

            response.raise_for_status()

            data = response.json()

    except httpx.HTTPStatusError as exc:
        logger.error(
            "[MUSICBRAINZ] HTTP error: status=%s url=%s body=%s",
            exc.response.status_code,
            exc.request.url,
            exc.response.text[:500],
        )

        raise MusicBrainzRecordingError(
            f"MusicBrainz returned HTTP {exc.response.status_code}."
        ) from exc

    except httpx.RequestError as exc:
        logger.error(
            "[MUSICBRAINZ] Request error: %s",
            exc,
        )

        raise MusicBrainzRecordingError(
            "Unable to connect to MusicBrainz."
        ) from exc

    except ValueError as exc:
        logger.error(
            "[MUSICBRAINZ] Invalid JSON response: %s",
            exc,
        )

        raise MusicBrainzRecordingError(
            "MusicBrainz returned an invalid response."
        ) from exc

    if not data:
        raise MusicBrainzRecordingError(
            "MusicBrainz returned an empty recording."
        )

    return data


def extract_recording_metadata(
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract normalized metadata from a MusicBrainz recording response.
    """

    musicbrainz_id = data.get("id")

    if not musicbrainz_id:
        raise MusicBrainzRecordingError(
            "MusicBrainz recording does not have an MBID."
        )

    title = data.get("title")

    if not title:
        raise MusicBrainzRecordingError(
            "MusicBrainz recording does not have a title."
        )

    # ---------------------------------------------------------
    # Artists
    # ---------------------------------------------------------

    artist_credit = data.get("artist-credit") or []

    artists: list[dict[str, Any]] = []

    for credit in artist_credit:
        if not isinstance(credit, dict):
            continue

        artist = credit.get("artist")

        if not isinstance(artist, dict):
            continue

        artist_id = artist.get("id")
        artist_name = artist.get("name")
        sort_name = artist.get("sort-name")

        if not artist_name:
            continue

        artists.append(
            {
                "mbid": artist_id,
                "name": artist_name,
                "sort_name": sort_name,
            }
        )

    # Fallback
    if not artists:
        direct_artists = data.get("artists") or []

        for artist in direct_artists:
            if not isinstance(artist, dict):
                continue

            artist_id = artist.get("id")
            artist_name = artist.get("name")
            sort_name = artist.get("sort-name")

            if not artist_name:
                continue

            artists.append(
                {
                    "mbid": artist_id,
                    "name": artist_name,
                    "sort_name": sort_name,
                }
            )

    if not artists:
        raise MusicBrainzRecordingError(
            "MusicBrainz recording has no artist."
        )

    primary_artist = artists[0]

    artist_name = primary_artist.get("name")
    artist_mbid = primary_artist.get("mbid")
    artist_sort_name = primary_artist.get("sort_name")

    # ---------------------------------------------------------
    # Releases
    # ---------------------------------------------------------

    releases = data.get("releases") or []

    release: dict[str, Any] = {}

    if releases:
        first_release = releases[0]

        if isinstance(first_release, dict):
            release = first_release

    album_name = release.get("title")
    release_mbid = release.get("id")

    # ---------------------------------------------------------
    # Release group
    # ---------------------------------------------------------

    release_group = release.get("release-group") or {}

    if not isinstance(release_group, dict):
        release_group = {}

    release_group_mbid = release_group.get("id")

    track_number = None
    disc_number = None
    media = release.get("media") or []
    if media and isinstance(media[0], dict):
        disc_number = media[0].get("position")
        track_list = media[0].get("tracks") or media[0].get("track-list") or []
        for media_track in track_list:
            if not isinstance(media_track, dict):
                continue
            recording = media_track.get("recording") or {}
            if media_track.get("id") == musicbrainz_id or recording.get("id") == musicbrainz_id:
                track_number = media_track.get("position")
                break

    # ---------------------------------------------------------
    # Release date
    # ---------------------------------------------------------

    release_date = (
        release.get("date")
        or data.get("first-release-date")
    )

    # ---------------------------------------------------------
    # Duration
    # ---------------------------------------------------------

    duration_ms = data.get("length")

    if duration_ms is not None:
        try:
            duration_ms = int(duration_ms)
        except (TypeError, ValueError):
            duration_ms = None

    # ---------------------------------------------------------
    # Normalized result
    # ---------------------------------------------------------

    return {
        "musicbrainz_id": musicbrainz_id,
        "title": title,
        "artist_name": artist_name,
        "artist_mbid": artist_mbid,
        "artist_sort_name": artist_sort_name,
        "artists": artists,
        "album_name": album_name,
        "release_mbid": release_mbid,
        "release_group_mbid": release_group_mbid,
        "release_date": release_date,
        "track_number": track_number,
        "disc_number": disc_number,
        "duration_ms": duration_ms,
    }