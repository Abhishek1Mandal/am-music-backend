from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

class PlayCreate(BaseModel):
    position_ms: int | None = Field(default=None, ge=0)

class PlaybackPositionUpdate(BaseModel):
    position_ms: int = Field(..., ge=0)
    completed: bool = False

class HistoryItem(BaseModel):
    id: UUID
    track_id: UUID
    title: str
    artist_id: UUID
    album_id: UUID | None
    played_at: datetime
    position_ms: int | None
    completed: bool

class PlaybackPositionResponse(BaseModel):
    track_id: UUID
    position_ms: int
    completed: bool
    updated_at: datetime | None
