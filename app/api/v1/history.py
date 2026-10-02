from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.play_history import PlayHistory
from app.models.track import Track
from app.models.user import User


router = APIRouter(
    prefix="/history",
    tags=["History"],
)


@router.get("", summary="Get Listening History")
async def get_history(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the authenticated user's listening history.
    """

    result = await db.execute(
        select(PlayHistory, Track)
        .join(
            Track,
            Track.id == PlayHistory.track_id,
        )
        .where(
            PlayHistory.user_id == current_user.id,
        )
        .order_by(
            PlayHistory.played_at.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    rows = result.all()

    items = []

    for history, track in rows:
        items.append(
            {
                "id": history.id,
                "track_id": track.id,
                "title": track.title,
                "artist_id": track.artist_id,
                "album_id": track.album_id,
                "duration_ms": track.duration_ms,
                "musicbrainz_id": track.musicbrainz_id,
                "is_available": track.is_available,
                "played_at": history.played_at,
            }
        )

    return {
        "items": items,
        "count": len(items),
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/{track_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Record Track Play",
)
async def record_history(
    track_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Record that the authenticated user played a track.
    """

    track_result = await db.execute(
        select(Track).where(
            Track.id == track_id,
        )
    )

    track = track_result.scalar_one_or_none()

    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found.",
        )

    history = PlayHistory(
        user_id=current_user.id,
        track_id=track_id,
    )

    db.add(history)

    await db.commit()
    await db.refresh(history)

    return {
        "message": "Track added to listening history.",
        "id": history.id,
        "track_id": history.track_id,
        "played_at": history.played_at,
    }


@router.get(
    "/{history_id}",
    summary="Get History Entry",
)
async def get_history_item(
    history_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get one listening history entry.
    """

    result = await db.execute(
        select(PlayHistory, Track)
        .join(
            Track,
            Track.id == PlayHistory.track_id,
        )
        .where(
            PlayHistory.id == history_id,
            PlayHistory.user_id == current_user.id,
        )
    )

    row = result.one_or_none()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="History entry not found.",
        )

    history, track = row

    return {
        "id": history.id,
        "track_id": track.id,
        "title": track.title,
        "artist_id": track.artist_id,
        "album_id": track.album_id,
        "duration_ms": track.duration_ms,
        "musicbrainz_id": track.musicbrainz_id,
        "is_available": track.is_available,
        "played_at": history.played_at,
    }


@router.delete(
    "/{history_id}",
    summary="Delete History Entry",
)
async def delete_history_item(
    history_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete one listening history entry.
    """

    result = await db.execute(
        select(PlayHistory).where(
            PlayHistory.id == history_id,
            PlayHistory.user_id == current_user.id,
        )
    )

    history = result.scalar_one_or_none()

    if history is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="History entry not found.",
        )

    await db.delete(history)
    await db.commit()

    return {
        "message": "History entry deleted.",
        "id": history_id,
    }


@router.delete(
    "",
    summary="Clear Listening History",
)
async def clear_history(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete all listening history for the authenticated user.
    """

    result = await db.execute(
        delete(PlayHistory).where(
            PlayHistory.user_id == current_user.id,
        )
    )

    await db.commit()

    return {
        "message": "Listening history cleared.",
        "deleted_count": result.rowcount,
    }