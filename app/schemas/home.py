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