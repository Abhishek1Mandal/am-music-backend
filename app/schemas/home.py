import uuid
from datetime import date, datetime

from pydantic import BaseModel


class HomeTrack(BaseModel):
    id: uuid.UUID
    title: str
    artist_id: uuid.UUID
    artist_name: str
    album_id: uuid.UUID | None = None
    album_title: str | None = None
    duration_ms: int | None = None
    language_code: str | None = None
    musicbrainz_id: str | None = None
    is_available: bool


class HomeAlbum(BaseModel):
    id: uuid.UUID
    title: str
    artist_id: uuid.UUID
    artist_name: str
    release_date: date | None = None
    release_type: str | None = None
    musicbrainz_id: str | None = None
    cover_url: str | None = None


class HomeArtist(BaseModel):
    id: uuid.UUID
    name: str
    musicbrainz_id: str | None = None
    image_url: str | None = None


class HomeSection(BaseModel):
    type: str
    title: str
    tracks: list[HomeTrack] = []
    albums: list[HomeAlbum] = []
    artists: list[HomeArtist] = []


class HomeResponse(BaseModel):
    onboarding_completed: bool
    sections: list[HomeSection]
    generated_at: datetime

class HomeDiscoveryTrack(BaseModel):
    """MusicBrainz discovery result, independent of the local download library."""

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
    language_code: str | None = None
    is_downloaded: bool = False
    local_track_id: uuid.UUID | None = None


class HomeDiscoveryAlbum(BaseModel):
    """MusicBrainz album/release discovery result."""

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


class HomeDiscoveryResponse(BaseModel):
    kind: str
    limit: int
    offset: int
    total_count: int
    items: list[HomeDiscoveryTrack | HomeDiscoveryAlbum]
    preferred_languages: list[str]
    preferred_artists: list[str]


class HomeDiscoveryAlbumTrack(BaseModel):
    mbid: str
    title: str
    artist_name: str | None = None
    duration_ms: int | None = None
    position: int | None = None
    disc_number: int | None = None
    is_downloaded: bool = False
    local_track_id: uuid.UUID | None = None


class HomeDiscoveryAlbumDetail(BaseModel):
    mbid: str
    title: str
    artist_name: str | None = None
    artist_mbid: str | None = None
    release_date: str | None = None
    cover_art_url: str | None = None
    tracks: list[HomeDiscoveryAlbumTrack] = []


class HomeDiscoveryArtistDetail(BaseModel):
    mbid: str
    name: str
    disambiguation: str | None = None
    country: str | None = None
    area: str | None = None
    begin_date: str | None = None
    end_date: str | None = None
    artist_type: str | None = None
    albums: list[HomeDiscoveryAlbum] = []
    tracks: list[HomeDiscoveryTrack] = []
