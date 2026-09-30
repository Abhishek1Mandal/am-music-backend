import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PlaylistCreate(BaseModel):
    name: str
    description: str | None = None
    is_public: bool = False


class PlaylistResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    description: str | None
    is_public: bool
    created_at: datetime
    updated_at: datetime