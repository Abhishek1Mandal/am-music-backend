import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.track import Track
from app.schemas.track import TrackResponse

router = APIRouter(prefix="/tracks", tags=["Tracks"])


@router.get(
    "/",
    response_model=list[TrackResponse],
)
async def list_tracks(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Track)
        .order_by(Track.title)
        .limit(100)
    )

    return result.scalars().all()


@router.get(
    "/{track_id}",
    response_model=TrackResponse,
)
async def get_track(
    track_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Track).where(
            Track.id == track_id
        )
    )

    track = result.scalar_one_or_none()

    if track is None:
        raise HTTPException(
            status_code=404,
            detail="Track not found",
        )

    return track