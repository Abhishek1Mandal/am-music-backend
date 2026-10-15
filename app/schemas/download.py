from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class DownloadCreate(BaseModel):
    # Existing catalog downloads use a MusicBrainz recording ID.
    # Direct YouTube Music downloads can instead provide a video ID
    # and the selected result's metadata.
    musicbrainz_id: str | None = Field(default=None, min_length=1, max_length=100)
    video_id: str | None = Field(default=None, min_length=11, max_length=11)
    title: str | None = Field(default=None, min_length=1, max_length=300)
    artist_name: str | None = Field(default=None, max_length=300)
    album_name: str | None = Field(default=None, max_length=300)
    duration_ms: int | None = Field(default=None, ge=0)
    cover_art_url: str | None = Field(default=None, max_length=2000)

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
    title: str | None = None
    artist_name: str | None = None
    album_name: str | None = None
    cover_art_url: str | None = None
