from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DownloadCreate(BaseModel):
    """
    Request body for creating a download.

    Flutter only needs to send the MusicBrainz recording MBID.
    The backend resolves the source URL automatically.
    """

    musicbrainz_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="MusicBrainz recording MBID.",
    )


class DownloadResponse(BaseModel):
    """
    Public representation of a download.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID

    track_id: UUID | None = None

    musicbrainz_id: str | None = None

    source_url: str | None = None

    status: str

    file_path: str | None = None

    error_message: str | None = None

    created_at: datetime

    completed_at: datetime | None = None

    is_downloaded: bool = False