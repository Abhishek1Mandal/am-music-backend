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
    def __init__(self) -> None:
        self.base_url = settings.musicbrainz_base_url.rstrip("/")

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

    async def _get(
        self,
        endpoint: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:

        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=True,
        ) as client:

            response = await client.get(
                url,
                params=params,
            )

            response.raise_for_status()

            return response.json()

    # ==========================================
    # Artist Search
    # ==========================================

    async def search_artists(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MusicArtistResult], int]:

        data = await self._get(
            "/artist",
            {
                "query": query,
                "fmt": "json",
                "limit": limit,
                "offset": offset,
            },
        )

        artists: list[MusicArtistResult] = []

        for item in data.get("artists", []):
            artists.append(
                MusicArtistResult(
                    mbid=item.get("id", ""),
                    name=item.get("name", ""),
                    sort_name=item.get("sort-name"),
                    country=item.get("country"),
                    type=item.get("type"),
                    disambiguation=item.get("disambiguation"),
                )
            )

        return artists, data.get("count", 0)

    # ==========================================
    # Album / Release Search
    # ==========================================

    async def search_albums(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MusicAlbumResult], int]:

        data = await self._get(
            "/release",
            {
                "query": query,
                "fmt": "json",
                "limit": limit,
                "offset": offset,
            },
        )

        albums: list[MusicAlbumResult] = []

        for item in data.get("releases", []):

            artist_name = None
            artist_mbid = None

            artist_credit = item.get("artist-credit") or []

            if artist_credit:
                first_artist = artist_credit[0]

                artist = first_artist.get("artist", {})

                artist_name = artist.get("name")
                artist_mbid = artist.get("id")

            release_group = item.get("release-group") or {}

            release_group_mbid = release_group.get("id")

            release_group_type = release_group.get(
                "primary-type"
            )

            cover_art_url = None

            if item.get("id"):
                cover_art_url = (
                    cover_art_service.get_front_cover_url(
                        item["id"],
                        500,
                    )
                )

            albums.append(
                MusicAlbumResult(
                    mbid=item.get("id", ""),
                    title=item.get("title", ""),
                    artist_name=artist_name,
                    artist_mbid=artist_mbid,
                    release_date=item.get("date"),
                    country=item.get("country"),
                    status=item.get("status"),
                    release_group_mbid=release_group_mbid,
                    release_group_type=release_group_type,
                    cover_art_url=cover_art_url,
                )
            )

        return albums, data.get("count", 0)

    # ==========================================
    # Track / Recording Search
    # ==========================================

    async def search_tracks(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[MusicTrackResult], int]:

        data = await self._get(
            "/recording",
            {
                "query": query,
                "fmt": "json",
                "limit": limit,
                "offset": offset,
            },
        )

        tracks: list[MusicTrackResult] = []

        for item in data.get("recordings", []):

            artist_name = None
            artist_mbid = None

            artist_credit = item.get("artist-credit") or []

            if artist_credit:
                first_artist = artist_credit[0]

                artist = first_artist.get("artist", {})

                artist_name = artist.get("name")
                artist_mbid = artist.get("id")

            release_mbid = None
            album_name = None
            album_mbid = None
            release_group_mbid = None
            release_date = None
            cover_art_url = None

            releases = item.get("releases") or []

            if releases:

                release = releases[0]

                release_mbid = release.get("id")
                album_name = release.get("title")
                release_date = release.get("date")

                release_group = (
                    release.get("release-group")
                    or {}
                )

                album_mbid = release_mbid
                release_group_mbid = release_group.get("id")

                if release_mbid:
                    cover_art_url = (
                        cover_art_service.get_front_cover_url(
                            release_mbid,
                            500,
                        )
                    )

            tracks.append(
                MusicTrackResult(
                    mbid=item.get("id", ""),
                    title=item.get("title", ""),
                    artist_name=artist_name,
                    artist_mbid=artist_mbid,
                    album_name=album_name,
                    album_mbid=album_mbid,
                    release_mbid=release_mbid,
                    release_group_mbid=release_group_mbid,
                    release_date=release_date,
                    duration_ms=item.get("length"),
                    disambiguation=item.get(
                        "disambiguation"
                    ),
                    cover_art_url=cover_art_url,
                )
            )

        return tracks, data.get("count", 0)

    # ==========================================
    # Combined Search
    # ==========================================

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
    ) -> MusicSearchResponse:

        artists, artist_count = await self.search_artists(
            query=query,
            limit=limit,
            offset=offset,
        )

        albums, album_count = await self.search_albums(
            query=query,
            limit=limit,
            offset=offset,
        )

        tracks, track_count = await self.search_tracks(
            query=query,
            limit=limit,
            offset=offset,
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