from __future__ import annotations

import asyncio
import random
from typing import Any

import httpx

from app.core.config import settings
from app.schemas.metadata import (
    MusicAlbumResult,
    MusicArtistResult,
    MusicSearchResponse,
    MusicTrackResult,
)
from app.services.metadata.cover_art import cover_art_service


class MusicBrainzService:
    """
    MusicBrainz API service.

    Responsibilities:
        - Artist search
        - Release/album search
        - Recording/track search
        - Combined search
        - Automatic retry for temporary MusicBrainz failures
    """

    # HTTP status codes that indicate a temporary failure.
    RETRYABLE_STATUS_CODES = {
        429,  # Too Many Requests
        500,  # Internal Server Error
        502,  # Bad Gateway
        503,  # Service Unavailable
        504,  # Gateway Timeout
    }

    # Number of retries AFTER the initial request.
    MAX_RETRIES = 3

    # Base delay for exponential backoff.
    RETRY_BASE_DELAY = 1.0

    # Maximum retry delay.
    RETRY_MAX_DELAY = 8.0

    def __init__(self) -> None:
        self.base_url = (
            settings.musicbrainz_base_url.rstrip("/")
        )

        self.headers = {
            "User-Agent": settings.musicbrainz_user_agent,
            "Accept": "application/json",
        }

        self.timeout = httpx.Timeout(
            connect=5.0,
            read=15.0,
            write=10.0,
            pool=5.0,
        )

    # ==========================================
    # Retry helpers
    # ==========================================

    @staticmethod
    def _retry_after_seconds(
        response: httpx.Response,
    ) -> float | None:
        """
        Read Retry-After from a MusicBrainz response.

        Supports the standard integer-seconds form.

        Example:
            Retry-After: 2
        """
        value = response.headers.get(
            "Retry-After"
        )

        if not value:
            return None

        try:
            seconds = float(value)
        except (TypeError, ValueError):
            return None

        if seconds < 0:
            return None

        return min(
            seconds,
            MusicBrainzService.RETRY_MAX_DELAY,
        )

    @classmethod
    def _backoff_seconds(
        cls,
        attempt: int,
    ) -> float:
        """
        Calculate exponential backoff with small jitter.

        attempt=0 -> around 1 second
        attempt=1 -> around 2 seconds
        attempt=2 -> around 4 seconds
        """
        delay = min(
            cls.RETRY_BASE_DELAY * (2**attempt),
            cls.RETRY_MAX_DELAY,
        )

        # Small jitter prevents synchronized retries.
        jitter = random.uniform(
            0.0,
            0.25,
        )

        return min(
            delay + jitter,
            cls.RETRY_MAX_DELAY,
        )

    @classmethod
    async def _sleep_before_retry(
        cls,
        *,
        attempt: int,
        response: httpx.Response | None = None,
    ) -> None:
        """
        Wait before retrying.

        Prefer MusicBrainz's Retry-After header when available.
        Otherwise use exponential backoff.
        """
        retry_after = None

        if response is not None:
            retry_after = cls._retry_after_seconds(
                response
            )

        delay = (
            retry_after
            if retry_after is not None
            else cls._backoff_seconds(attempt)
        )

        await asyncio.sleep(delay)

    # ==========================================
    # HTTP GET
    # ==========================================

    async def _get(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Perform a GET request against MusicBrainz.

        Temporary failures are retried automatically.

        Retryable HTTP statuses:
            429
            500
            502
            503
            504

        Connection and timeout failures are also retried.
        """

        url = (
            f"{self.base_url}/"
            f"{endpoint.lstrip('/')}"
        )

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        ) as client:

            for attempt in range(
                self.MAX_RETRIES + 1
            ):
                response: httpx.Response | None = None

                try:
                    response = await client.get(
                        url,
                        params=params,
                    )

                    # ------------------------------------------
                    # Success
                    # ------------------------------------------

                    if response.is_success:
                        return response.json()

                    # ------------------------------------------
                    # Retryable HTTP failure
                    # ------------------------------------------

                    if (
                        response.status_code
                        in self.RETRYABLE_STATUS_CODES
                    ):
                        if attempt < self.MAX_RETRIES:
                            await self._sleep_before_retry(
                                attempt=attempt,
                                response=response,
                            )
                            continue

                        # Retries exhausted.
                        response.raise_for_status()

                    # ------------------------------------------
                    # Non-retryable HTTP failure
                    # ------------------------------------------

                    response.raise_for_status()

                except (
                    httpx.ConnectError,
                    httpx.ConnectTimeout,
                    httpx.ReadTimeout,
                    httpx.WriteTimeout,
                    httpx.PoolTimeout,
                ):
                    # ------------------------------------------
                    # Temporary connection/timeout failure
                    # ------------------------------------------

                    if attempt < self.MAX_RETRIES:
                        await self._sleep_before_retry(
                            attempt=attempt,
                        )
                        continue

                    raise

        raise RuntimeError(
            "MusicBrainz request failed unexpectedly."
        )

    # ==========================================
    # Artist Search
    # ==========================================

    async def search_artists(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[
        list[MusicArtistResult],
        int,
    ]:
        data = await self._get(
            "/artist",
            {
                "query": query,
                "fmt": "json",
                "limit": limit,
                "offset": offset,
            },
        )

        artists: list[
            MusicArtistResult
        ] = []

        for item in data.get(
            "artists",
            [],
        ):
            artist_mbid = item.get("id")

            artists.append(
                MusicArtistResult(
                    mbid=artist_mbid or "",
                    name=item.get(
                        "name",
                        "",
                    ),
                    sort_name=item.get(
                        "sort-name"
                    ),
                    country=item.get(
                        "country"
                    ),
                    type=item.get(
                        "type"
                    ),
                    disambiguation=item.get(
                        "disambiguation"
                    ),
                )
            )

        return (
            artists,
            data.get(
                "count",
                0,
            ),
        )

    # ==========================================
    # Album / Release Search
    # ==========================================

    async def search_albums(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[
        list[MusicAlbumResult],
        int,
    ]:
        data = await self._get(
            "/release",
            {
                "query": query,
                "fmt": "json",
                "limit": limit,
                "offset": offset,
            },
        )

        albums: list[
            MusicAlbumResult
        ] = []

        for item in data.get(
            "releases",
            [],
        ):
            release_mbid = item.get("id")

            artist_name = None
            artist_mbid = None

            artist_credit = (
                item.get("artist-credit")
                or []
            )

            if artist_credit:
                first_artist = artist_credit[0]

                artist = (
                    first_artist.get(
                        "artist"
                    )
                    or {}
                )

                artist_name = artist.get(
                    "name"
                )

                artist_mbid = artist.get(
                    "id"
                )

            release_group = (
                item.get("release-group")
                or {}
            )

            release_group_mbid = (
                release_group.get("id")
            )

            release_group_type = (
                release_group.get(
                    "primary-type"
                )
            )

            cover_art_url = None

            if release_mbid:
                cover_art_url = (
                    cover_art_service
                    .get_front_cover_url(
                        release_mbid,
                        500,
                    )
                )

            albums.append(
                MusicAlbumResult(
                    # This is the MusicBrainz
                    # RELEASE MBID.
                    mbid=release_mbid or "",
                    title=item.get(
                        "title",
                        "",
                    ),
                    artist_name=artist_name,
                    artist_mbid=artist_mbid,
                    release_date=item.get(
                        "date"
                    ),
                    country=item.get(
                        "country"
                    ),
                    status=item.get(
                        "status"
                    ),
                    release_group_mbid=(
                        release_group_mbid
                    ),
                    release_group_type=(
                        release_group_type
                    ),
                    cover_art_url=(
                        cover_art_url
                    ),
                )
            )

        return (
            albums,
            data.get(
                "count",
                0,
            ),
        )

    # ==========================================
    # Track / Recording Search
    # ==========================================

    async def search_tracks(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[
        list[MusicTrackResult],
        int,
    ]:
        data = await self._get(
            "/recording",
            {
                "query": query,
                "fmt": "json",
                "limit": limit,
                "offset": offset,
                "inc": "artists+releases",
            },
        )

        tracks: list[
            MusicTrackResult
        ] = []

        for item in data.get(
            "recordings",
            [],
        ):
            # ==========================================
            # IMPORTANT
            # ==========================================
            #
            # item["id"] is the RECORDING MBID.
            #
            # This is the ID that must be sent to:
            #
            # POST /api/v1/downloads
            #
            # Do NOT replace this with release.id.
            # ==========================================

            recording_mbid = item.get(
                "id"
            )

            if not recording_mbid:
                continue

            # ==========================================
            # Artist
            # ==========================================

            artist_name = None
            artist_mbid = None

            artist_credit = (
                item.get("artist-credit")
                or []
            )

            if artist_credit:
                first_artist = artist_credit[0]

                artist = (
                    first_artist.get(
                        "artist"
                    )
                    or {}
                )

                artist_name = artist.get(
                    "name"
                )

                artist_mbid = artist.get(
                    "id"
                )

            # ==========================================
            # Release / Album
            # ==========================================

            release_mbid = None
            album_name = None
            album_mbid = None
            release_group_mbid = None
            release_date = None
            cover_art_url = None

            releases = (
                item.get("releases")
                or []
            )

            if releases:
                # MusicBrainz can return multiple
                # releases.

                release = releases[0]

                release_mbid = release.get(
                    "id"
                )

                album_name = release.get(
                    "title"
                )

                release_date = release.get(
                    "date"
                )

                release_group = (
                    release.get(
                        "release-group"
                    )
                    or {}
                )

                release_group_mbid = (
                    release_group.get(
                        "id"
                    )
                )

                # album_mbid represents the actual
                # RELEASE associated with this result.
                #
                # release_mbid == release.id
                album_mbid = release_mbid

                if release_mbid:
                    cover_art_url = (
                        cover_art_service
                        .get_front_cover_url(
                            release_mbid,
                            500,
                        )
                    )

            # ==========================================
            # Track Result
            # ==========================================

            tracks.append(
                MusicTrackResult(
                    # ======================================
                    # CRITICAL:
                    #
                    # This MUST be recording.id
                    #
                    # This is what the download API expects.
                    # ======================================
                    mbid=recording_mbid,

                    title=item.get(
                        "title",
                        "",
                    ),

                    artist_name=artist_name,
                    artist_mbid=artist_mbid,

                    album_name=album_name,

                    # Release MBID.
                    album_mbid=album_mbid,

                    # Same release MBID.
                    release_mbid=release_mbid,

                    # Release-group MBID.
                    release_group_mbid=(
                        release_group_mbid
                    ),

                    release_date=release_date,

                    # MusicBrainz recording
                    # length is milliseconds.
                    duration_ms=item.get(
                        "length"
                    ),

                    disambiguation=item.get(
                        "disambiguation"
                    ),

                    cover_art_url=(
                        cover_art_url
                    ),
                )
            )

        return (
            tracks,
            data.get(
                "count",
                0,
            ),
        )

    # ==========================================
    # Combined Search
    # ==========================================

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> MusicSearchResponse:
        artists, artist_count = (
            await self.search_artists(
                query=query,
                limit=limit,
                offset=offset,
            )
        )

        albums, album_count = (
            await self.search_albums(
                query=query,
                limit=limit,
                offset=offset,
            )
        )

        tracks, track_count = (
            await self.search_tracks(
                query=query,
                limit=limit,
                offset=offset,
            )
        )

        return MusicSearchResponse(
            query=query,
            offset=offset,
            limit=limit,
            total_count=max(
                artist_count,
                album_count,
                track_count,
            ),
            artists=artists,
            albums=albums,
            tracks=tracks,
        )


musicbrainz_service = MusicBrainzService()