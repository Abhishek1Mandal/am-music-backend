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
from app.services.metadata.cover_art import (
    cover_art_service,
)


class MusicBrainzService:
    """
    MusicBrainz API client.

    Responsibilities:
    - Artist search
    - Artist lookup
    - Album/release search
    - Recording/track search
    - Language-based artist discovery
    - Retry handling
    - Rate-limit protection
    - HTTP error handling
    """

    # ======================================================
    # MusicBrainz language mapping
    # ======================================================

    LANGUAGE_639_1_TO_639_3 = {
        "en": "eng",
        "hi": "hin",
        "te": "tel",
        "ta": "tam",
        "ml": "mal",
        "kn": "kan",
        "bn": "ben",
        "pa": "pan",
        "mr": "mar",
        "gu": "guj",
        "bho": "bho",
        "or": "ori",
        "as": "asm",
        "ur": "urd",
        "kok": "kok",
        "raj": "raj",
    }

    # ======================================================
    # HTTP / retry configuration
    # ======================================================

    RETRYABLE_STATUS_CODES = {
        429,
        500,
        502,
        503,
        504,
    }

    MAX_RETRIES = 3

    BASE_RETRY_DELAY = 1.0

    MAX_RETRY_DELAY = 10.0

    # MusicBrainz requests should be approximately
    # one request per second.
    REQUEST_INTERVAL = 1.05

    # ======================================================
    # Initialization
    # ======================================================

    def __init__(self) -> None:
        self.base_url = (
            settings.musicbrainz_base_url.rstrip("/")
        )

        self.headers = {
            "User-Agent": (
                settings.musicbrainz_user_agent
            ),
            "Accept": "application/json",
        }

        self.timeout = httpx.Timeout(
            connect=5.0,
            read=15.0,
            write=10.0,
            pool=5.0,
        )

        # --------------------------------------------------
        # Rate-limit lock
        #
        # Prevents concurrent requests from this service
        # from hitting MusicBrainz simultaneously.
        # --------------------------------------------------

        self._request_lock = asyncio.Lock()

        self._last_request_at = 0.0

    # ======================================================
    # Rate-limit handling
    # ======================================================

    async def _wait_for_rate_limit(self) -> None:
        """
        Ensure requests are separated by approximately
        one second.

        The lock is important because asyncio.gather()
        could otherwise allow multiple requests to pass
        the time check simultaneously.
        """

        loop = asyncio.get_running_loop()

        async with self._request_lock:
            now = loop.time()

            elapsed = (
                now - self._last_request_at
            )

            if elapsed < self.REQUEST_INTERVAL:
                await asyncio.sleep(
                    self.REQUEST_INTERVAL
                    - elapsed
                )

            self._last_request_at = (
                loop.time()
            )

    # ======================================================
    # Retry delay
    # ======================================================

    def _retry_delay(
        self,
        attempt: int,
    ) -> float:
        """
        Exponential backoff with small random jitter.
        """

        exponential_delay = min(
            self.BASE_RETRY_DELAY
            * (2**attempt),
            self.MAX_RETRY_DELAY,
        )

        jitter = random.uniform(
            0.0,
            0.5,
        )

        return (
            exponential_delay
            + jitter
        )

    # ======================================================
    # HTTP GET
    # ======================================================

    async def _get(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Execute a GET request against MusicBrainz.

        Retryable:
        - 429
        - 500
        - 502
        - 503
        - 504

        Non-retryable HTTP errors are propagated.

        Connection and timeout failures are also retried.
        """

        url = (
            f"{self.base_url}/"
            f"{endpoint.lstrip('/')}"
        )

        request_params = params or {}

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        ) as client:

            for attempt in range(
                self.MAX_RETRIES + 1
            ):
                try:
                    await self._wait_for_rate_limit()

                    response = (
                        await client.get(
                            url,
                            params=request_params,
                        )
                    )

                    # --------------------------------------
                    # Success
                    # --------------------------------------

                    if response.is_success:
                        return response.json()

                    # --------------------------------------
                    # Retryable HTTP error
                    # --------------------------------------

                    if (
                        response.status_code
                        in self.RETRYABLE_STATUS_CODES
                    ):
                        if (
                            attempt
                            >= self.MAX_RETRIES
                        ):
                            response.raise_for_status()

                        retry_after = (
                            response.headers.get(
                                "Retry-After"
                            )
                        )

                        if retry_after:
                            try:
                                delay = float(
                                    retry_after
                                )
                            except (
                                ValueError,
                                TypeError,
                            ):
                                delay = (
                                    self._retry_delay(
                                        attempt
                                    )
                                )
                        else:
                            delay = (
                                self._retry_delay(
                                    attempt
                                )
                            )

                        await asyncio.sleep(
                            delay
                        )

                        continue

                    # --------------------------------------
                    # Non-retryable HTTP error
                    # --------------------------------------

                    response.raise_for_status()

                except (
                    httpx.ConnectError,
                    httpx.ConnectTimeout,
                    httpx.ReadTimeout,
                    httpx.WriteTimeout,
                    httpx.PoolTimeout,
                ):
                    if (
                        attempt
                        >= self.MAX_RETRIES
                    ):
                        raise

                    delay = (
                        self._retry_delay(
                            attempt
                        )
                    )

                    await asyncio.sleep(
                        delay
                    )

                except httpx.HTTPStatusError:
                    # Non-retryable HTTP errors should
                    # propagate immediately.
                    raise

        raise RuntimeError(
            "MusicBrainz request failed unexpectedly."
        )

    # ======================================================
    # Artist Search
    # ======================================================

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
            artist_mbid = item.get(
                "id"
            )

            if not artist_mbid:
                continue

            artists.append(
                MusicArtistResult(
                    mbid=artist_mbid,
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

    # ======================================================
    # Artist Lookup
    # ======================================================

    async def get_artist(
        self,
        musicbrainz_id: str,
    ) -> MusicArtistResult:
        """
        Get a single artist by MusicBrainz MBID.
        """

        musicbrainz_id = (
            musicbrainz_id.strip()
        )

        if not musicbrainz_id:
            raise ValueError(
                "MusicBrainz artist MBID "
                "is required."
            )

        data = await self._get(
            f"/artist/{musicbrainz_id}",
            {
                "fmt": "json",
            },
        )

        artist_mbid = data.get(
            "id"
        )

        if not artist_mbid:
            raise ValueError(
                "MusicBrainz artist does "
                "not have an MBID."
            )

        name = data.get(
            "name"
        )

        if not name:
            raise ValueError(
                "MusicBrainz artist does "
                "not have a name."
            )

        return MusicArtistResult(
            mbid=artist_mbid,
            name=name,
            sort_name=data.get(
                "sort-name"
            ),
            country=data.get(
                "country"
            ),
            type=data.get(
                "type"
            ),
            disambiguation=data.get(
                "disambiguation"
            ),
        )

    # ======================================================
    # Language-based Artist Discovery
    # ======================================================

    async def search_artists_by_language(
        self,
        language_code: str,
        max_artists: int = 100,
    ) -> list[MusicArtistResult]:
        """
        Discover artists from MusicBrainz releases
        matching a specific language.

        Input:
            hi
            te
            ta

        MusicBrainz query:
            lang:hin
            lang:tel
            lang:tam

        Artists are deduplicated using their
        MusicBrainz artist MBID.
        """

        language_code = (
            language_code.strip().lower()
        )

        if not language_code:
            return []

        language_639_3 = (
            self.LANGUAGE_639_1_TO_639_3.get(
                language_code,
                language_code,
            )
        )

        if not language_639_3:
            return []

        max_artists = max(
            1,
            min(
                max_artists,
                100,
            ),
        )

        artists_by_mbid: dict[
            str,
            MusicArtistResult,
        ] = {}

        release_offset = 0

        release_page_size = 100

        # --------------------------------------------------
        # Do not scan MusicBrainz indefinitely.
        # --------------------------------------------------

        max_release_offset = 500

        query = (
            f"lang:{language_639_3}"
        )

        while (
            len(artists_by_mbid)
            < max_artists
            and release_offset
            < max_release_offset
        ):
            data = await self._get(
                "/release",
                {
                    "query": query,
                    "fmt": "json",
                    "limit": release_page_size,
                    "offset": release_offset,
                },
            )

            releases = data.get(
                "releases",
                [],
            )

            if not releases:
                break

            for release in releases:
                artist_credit = (
                    release.get(
                        "artist-credit"
                    )
                    or []
                )

                for credit in artist_credit:
                    artist = (
                        credit.get(
                            "artist"
                        )
                        or {}
                    )

                    artist_mbid = (
                        artist.get(
                            "id"
                        )
                    )

                    if not artist_mbid:
                        continue

                    # ----------------------------------
                    # Duplicate prevention
                    # ----------------------------------

                    if (
                        artist_mbid
                        in artists_by_mbid
                    ):
                        continue

                    name = artist.get(
                        "name"
                    )

                    if not name:
                        continue

                    artists_by_mbid[
                        artist_mbid
                    ] = MusicArtistResult(
                        mbid=artist_mbid,
                        name=name,
                        sort_name=artist.get(
                            "sort-name"
                        ),
                        country=artist.get(
                            "country"
                        ),
                        type=artist.get(
                            "type"
                        ),
                        disambiguation=(
                            artist.get(
                                "disambiguation"
                            )
                        ),
                    )

                    if (
                        len(
                            artists_by_mbid
                        )
                        >= max_artists
                    ):
                        break

                if (
                    len(
                        artists_by_mbid
                    )
                    >= max_artists
                ):
                    break

            # ------------------------------------------
            # Advance by actual number of results.
            # ------------------------------------------

            release_offset += len(
                releases
            )

            total = data.get(
                "count",
                0,
            )

            if release_offset >= total:
                break

        artists = list(
            artists_by_mbid.values()
        )

        # Stable ordering is important because
        # these results are cached in PostgreSQL.
        artists.sort(
            key=lambda artist: (
                (
                    artist.sort_name
                    or artist.name
                ).lower(),
                artist.mbid,
            )
        )

        return artists

    # ======================================================
    # Album / Release Search
    # ======================================================

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
            release_mbid = item.get(
                "id"
            )

            artist_name = None
            artist_mbid = None

            artist_credit = (
                item.get(
                    "artist-credit"
                )
                or []
            )

            if artist_credit:
                first_artist = (
                    artist_credit[0]
                )

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
                item.get(
                    "release-group"
                )
                or {}
            )

            release_group_mbid = (
                release_group.get(
                    "id"
                )
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
                    mbid=(
                        release_mbid
                        or ""
                    ),
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

    # ======================================================
    # Track / Recording Search
    # ======================================================

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
                "inc": (
                    "artists+releases"
                ),
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
            # IMPORTANT:
            #
            # item["id"] is the RECORDING MBID.
            #
            # This is the ID sent to:
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
                item.get(
                    "artist-credit"
                )
                or []
            )

            if artist_credit:
                first_artist = (
                    artist_credit[0]
                )

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
                item.get(
                    "releases"
                )
                or []
            )

            if releases:
                # MusicBrainz can return multiple
                # releases.
                #
                # We currently use the first release
                # returned by MusicBrainz.
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

                # IMPORTANT:
                #
                # album_mbid represents the actual
                # RELEASE associated with this result.
                #
                # album_mbid == release_mbid
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
                    # It is the MusicBrainz RECORDING MBID.
                    # ======================================
                    mbid=recording_mbid,

                    title=item.get(
                        "title",
                        "",
                    ),

                    artist_name=artist_name,
                    artist_mbid=artist_mbid,

                    album_name=album_name,

                    # Release MBID
                    album_mbid=album_mbid,

                    # Same release MBID
                    release_mbid=release_mbid,

                    # Release-group MBID
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

    # ======================================================
    # Combined Search
    # ======================================================

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> MusicSearchResponse:
        """
        Search artists, albums and tracks.

        Requests are intentionally sequential.

        Do NOT change this to asyncio.gather()
        because MusicBrainz rate limiting is handled
        centrally by _wait_for_rate_limit().
        """

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


# ==========================================================
# Singleton
# ==========================================================

musicbrainz_service = MusicBrainzService()