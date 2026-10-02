from __future__ import annotations

from pydantic import BaseModel, Field


class MaintenanceCleanupRequest(BaseModel):
    dry_run: bool = True
    orphan_grace_hours: int = Field(default=24, ge=1, le=720)
    stale_download_hours: int = Field(default=6, ge=1, le=168)
    cleanup_stale_downloads: bool = True
    cleanup_missing_tracks: bool = True
    cleanup_orphans: bool = True
    cleanup_empty_dirs: bool = True


class MaintenanceFileResponse(BaseModel):
    path: str
    size_bytes: int
    age_hours: float


class MaintenanceCleanupResponse(BaseModel):
    dry_run: bool
    library_root: str
    started_at: str
    finished_at: str | None = None
    scanned_files: int
    scanned_bytes: int
    referenced_files: int
    orphan_files: int
    orphan_bytes: int
    deleted_files: int
    deleted_bytes: int
    missing_tracks: int
    repaired_tracks: int
    stale_downloads: int
    repaired_downloads: int
    empty_directories: int
    removed_directories: int
    skipped_files: int
    errors: list[str]
    orphan_candidates: list[MaintenanceFileResponse]
    stale_download_ids: list[str]
    missing_track_ids: list[str]


class MaintenanceHealthResponse(BaseModel):
    status: str
    library_root: str
    library_exists: bool
    track_count: int
    download_count: int
    active_downloads: int
    missing_track_files: int
    audio_file_count: int
    audio_bytes: int
