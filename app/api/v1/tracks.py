import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.track import Track
from app.schemas.track import (
    TrackAvailabilityResponse,
    TrackDetailResponse,
)


router = APIRouter(
    prefix="/tracks",
    tags=["Tracks"],
)


# ============================================================
# TRACK AVAILABILITY
# ============================================================

@router.get(
    "/{track_id}/availability",
    response_model=TrackAvailabilityResponse,
    status_code=status.HTTP_200_OK,
)
async def get_track_availability(
    track_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Check whether a track is currently available locally.
    """

    result = await db.execute(
        select(Track.is_available).where(
            Track.id == track_id,
        )
    )

    is_available = result.scalar_one_or_none()

    if is_available is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found",
        )

    return TrackAvailabilityResponse(
        track_id=track_id,
        is_available=bool(is_available),
    )


# ============================================================
# GET TRACK
# ============================================================

@router.get(
    "/{track_id}",
    response_model=TrackDetailResponse,
    status_code=status.HTTP_200_OK,
)
async def get_track(
    track_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Get a single track with artist and album information.
    """

    result = await db.execute(
        select(Track)
        .options(
            selectinload(Track.artist),
            selectinload(Track.album),
        )
        .where(
            Track.id == track_id,
        )
    )

    track = result.scalar_one_or_none()

    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found",
        )

    return TrackDetailResponse(
        id=track.id,
        artist_id=track.artist_id,
        album_id=track.album_id,
        title=track.title,
        track_number=track.track_number,
        disc_number=track.disc_number,
        duration_ms=track.duration_ms,
        musicbrainz_id=track.musicbrainz_id,
        is_available=track.is_available,
        artist=track.artist,
        album=track.album,
    )