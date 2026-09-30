from typing import Any

from pydantic import BaseModel, Field


class MusicArtistResult(BaseModel):
    mbid: str
    name: str
    sort_name: str | None = None
    country: str | None = None
    type: str | None = None
    disambiguation: str | None = None


class MusicAlbumResult(BaseModel):
    mbid: str
    title: str
    artist_name: str | None = None
    artist_mbid: str | None = None
    release_date: str | None = None
    country: str | None = None
    status: str | None = None
    release_group_mbid: str | None = None
    release_group_type: str | None = None
    cover_art_url: str | None = None


class MusicTrackResult(BaseModel):
    mbid: str
    title: str
    artist_name: str | None = None
    artist_mbid: str | None = None
    album_name: str | None = None
    album_mbid: str | None = None
    release_mbid: str | None = None
    release_group_mbid: str | None = None
    release_date: str | None = None
    duration_ms: int | None = None
    disambiguation: str | None = None
    cover_art_url: str | None = None

    is_downloaded: bool = False


class MusicSearchResponse(BaseModel):
    query: str
    offset: int
    limit: int
    total_count: int

    artists: list[MusicArtistResult] = Field(
        default_factory=list
    )

    albums: list[MusicAlbumResult] = Field(
        default_factory=list
    )

    tracks: list[MusicTrackResult] = Field(
        default_factory=list
    )


class MusicSearchResult(BaseModel):
    type: str
    data: dict[str, Any]