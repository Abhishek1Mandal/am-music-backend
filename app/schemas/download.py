from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class DownloadCreate(BaseModel):
    musicbrainz_id: str = Field(..., min_length=1, max_length=100)

class DownloadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    track_id: UUID | None = None
    musicbrainz_id: str | None = None
    source_url: str | None = None
    status: str
    progress_percent: float = 0.0
    downloaded_bytes: int = 0
    total_bytes: int | None = None
    file_path: str | None = None
    error_message: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    is_downloaded: bool = False
