from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DownloadCreate(BaseModel):
    """
    Request body for creating a new music download.
    """

    url: str = Field(
        ...,
        min_length=1,
        max_length=2048,
        description="Authorized URL of the audio/video content to download.",
    )


class DownloadResponse(BaseModel):
    """
    Public representation of a download record.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    track_id: UUID | None = None

    source_url: str

    status: str

    file_path: str | None = None

    error_message: str | None = None

    created_at: datetime
    completed_at: datetime | None = None