import uuid

from pydantic import BaseModel, ConfigDict


class ArtistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    sort_name: str | None = None
    musicbrainz_id: str | None = None
    image_url: str | None = None
    biography: str | None = None