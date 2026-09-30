import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class IDResponse(BaseModel):
    id: uuid.UUID


class MessageResponse(BaseModel):
    message: str


class TimestampResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime