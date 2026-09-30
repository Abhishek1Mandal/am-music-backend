import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict


class AlbumResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    artist_id: uuid.UUID
    title: str
    release_date: date | None = None
    release_type: str | None = None
    musicbrainz_id: str | None = None
    cover_url: str | None = None