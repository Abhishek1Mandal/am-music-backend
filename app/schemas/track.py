import uuid

from pydantic import BaseModel, ConfigDict


class TrackResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    artist_id: uuid.UUID
    album_id: uuid.UUID | None = None
    title: str
    track_number: int | None = None
    disc_number: int | None = None
    duration_ms: int | None = None
    musicbrainz_id: str | None = None
    is_available: bool