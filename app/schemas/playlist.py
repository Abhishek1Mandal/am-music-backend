from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class PlaylistCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_public: bool = False

class PlaylistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    is_public: bool | None = None

class PlaylistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    name: str
    description: str | None
    is_public: bool
    created_at: datetime
    updated_at: datetime

class PlaylistTrackAdd(BaseModel):
    track_ids: list[UUID] = Field(..., min_length=1, max_length=500)

class PlaylistTrackReorder(BaseModel):
    track_ids: list[UUID] = Field(..., min_length=1, max_length=500)

class PlaylistTrackResponse(BaseModel):
    position: int
    track_id: UUID
    title: str
    artist_id: UUID
    album_id: UUID | None
    duration_ms: int | None
    musicbrainz_id: str | None
    is_available: bool

class PlaylistDetailResponse(PlaylistResponse):
    tracks: list[PlaylistTrackResponse] = Field(default_factory=list)
