import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.album import AlbumResponse
from app.schemas.artist import ArtistResponse


class LibraryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    track_id: uuid.UUID
    added_at: datetime

    track: "LibraryTrackResponse"


class LibraryTrackResponse(BaseModel):
    id: uuid.UUID
    artist_id: uuid.UUID
    album_id: uuid.UUID | None = None
    title: str
    track_number: int | None = None
    disc_number: int | None = None
    duration_ms: int | None = None
    musicbrainz_id: str | None = None
    is_available: bool

    artist: ArtistResponse | None = None
    album: AlbumResponse | None = None


class LibraryListResponse(BaseModel):
    items: list[LibraryItemResponse]
    page: int
    limit: int
    total: int
    total_pages: int


class LibraryStatusResponse(BaseModel):
    track_id: uuid.UUID
    is_in_library: bool
    is_available: bool


class LibraryMessageResponse(BaseModel):
    message: str
    track_id: uuid.UUID