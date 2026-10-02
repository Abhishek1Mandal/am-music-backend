from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.maintenance import (
    MaintenanceCleanupRequest,
    MaintenanceCleanupResponse,
    MaintenanceHealthResponse,
)
from app.services.music.maintenance import MaintenanceService


router = APIRouter(
    prefix="/maintenance",
    tags=["Maintenance"],
)


service = MaintenanceService()


@router.get(
    "/health",
    response_model=MaintenanceHealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Maintenance Health",
)
async def maintenance_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return filesystem and database consistency statistics."""
    return await service.health(db)


@router.post(
    "/cleanup",
    response_model=MaintenanceCleanupResponse,
    status_code=status.HTTP_200_OK,
    summary="Run Music Library Cleanup",
    description=(
        "Reconcile missing track files, detect stale downloads, "
        "find orphan MP3 files, and remove empty directories. "
        "Use dry_run=true first."
    ),
)
async def cleanup_music_library(
    payload: MaintenanceCleanupRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        report = await service.cleanup(
            db,
            dry_run=payload.dry_run,
            orphan_grace_hours=payload.orphan_grace_hours,
            stale_download_hours=payload.stale_download_hours,
            cleanup_stale_downloads=payload.cleanup_stale_downloads,
            cleanup_missing_tracks=payload.cleanup_missing_tracks,
            cleanup_orphans=payload.cleanup_orphans,
            cleanup_empty_dirs=payload.cleanup_empty_dirs,
        )

        return MaintenanceCleanupResponse(
            dry_run=report.dry_run,
            library_root=report.library_root,
            started_at=report.started_at,
            finished_at=report.finished_at,
            scanned_files=report.scanned_files,
            scanned_bytes=report.scanned_bytes,
            referenced_files=report.referenced_files,
            orphan_files=report.orphan_files,
            orphan_bytes=report.orphan_bytes,
            deleted_files=report.deleted_files,
            deleted_bytes=report.deleted_bytes,
            missing_tracks=report.missing_tracks,
            repaired_tracks=report.repaired_tracks,
            stale_downloads=report.stale_downloads,
            repaired_downloads=report.repaired_downloads,
            empty_directories=report.empty_directories,
            removed_directories=report.removed_directories,
            skipped_files=report.skipped_files,
            errors=report.errors,
            orphan_candidates=report.orphan_candidates,
            stale_download_ids=report.stale_download_ids,
            missing_track_ids=report.missing_track_ids,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Maintenance operation failed.",
        ) from exc
