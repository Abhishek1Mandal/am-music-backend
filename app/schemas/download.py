from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DownloadCreate(BaseModel):
    """
    Request body for creating a download.

    Flutter only sends the MusicBrainz recording MBID.
    """

    musicbrainz_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )


class DownloadResponse(BaseModel):
    """
    API response for a download.

    is_downloaded is calculated by the backend from the
    actual Track + physical file state.
    """

    model_config = ConfigDict(
        from_attributes=True,
    )

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