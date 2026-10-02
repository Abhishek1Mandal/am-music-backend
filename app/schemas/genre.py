from uuid import UUID
from pydantic import BaseModel, Field

class GenreCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)

class GenreResponse(BaseModel):
    id: UUID
    name: str

class GenreTrackResponse(BaseModel):
    id: UUID
    title: str
    artist_id: UUID
    album_id: UUID | None
    duration_ms: int | None
    musicbrainz_id: str | None
    is_available: bool
