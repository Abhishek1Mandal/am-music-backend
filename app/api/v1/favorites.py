from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.favorite import Favorite
from app.models.track import Track
from app.models.user import User

router = APIRouter(
    prefix="/favorites",
    tags=["Favorites"],
)


@router.get("")
async def get_favorites(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get all favorite tracks for the authenticated user.
    """

    result = await db.execute(
        select(Favorite, Track)
        .join(
            Track,
            Track.id == Favorite.track_id,
        )
        .where(
            Favorite.user_id == current_user.id
        )
        .order_by(
            Favorite.created_at.desc()
        )
    )

    rows = result.all()

    return {
        "items": [
            {
                "id": favorite.id,
                "track_id": track.id,
                "title": track.title,
                "artist_id": track.artist_id,
                "album_id": track.album_id,
                "created_at": favorite.created_at,
            }
            for favorite, track in rows
        ],
        "count": len(rows),
    }


@router.post(
    "/{track_id}",
    status_code=status.HTTP_201_CREATED,
)
async def add_favorite(
    track_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add a track to the authenticated user's favorites.
    """

    # Check track exists
    track_result = await db.execute(
        select(Track).where(
            Track.id == track_id
        )
    )

    track = track_result.scalar_one_or_none()

    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found.",
        )

    # Check if already favorite
    favorite_result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.track_id == track_id,
        )
    )

    existing = favorite_result.scalar_one_or_none()

    if existing is not None:
        return {
            "message": "Track is already in favorites.",
            "favorite_id": existing.id,
            "track_id": track_id,
        }

    favorite = Favorite(
        user_id=current_user.id,
        track_id=track_id,
    )

    db.add(favorite)

    await db.commit()
    await db.refresh(favorite)

    return {
        "message": "Track added to favorites.",
        "favorite_id": favorite.id,
        "track_id": track_id,
    }


@router.delete(
    "/{track_id}",
)
async def remove_favorite(
    track_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Remove a track from the authenticated user's favorites.
    """

    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.track_id == track_id,
        )
    )

    favorite = result.scalar_one_or_none()

    if favorite is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track is not in favorites.",
        )

    await db.delete(favorite)

    await db.commit()

    return {
        "message": "Track removed from favorites.",
        "track_id": track_id,
    }


@router.get(
    "/{track_id}/status",
)
async def favorite_status(
    track_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Check whether a track is favorited by the current user.
    """

    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
            Favorite.track_id == track_id,
        )
    )

    favorite = result.scalar_one_or_none()

    return {
        "track_id": track_id,
        "is_favorite": favorite is not None,
        "favorite_id": (
            favorite.id
            if favorite
            else None
        ),
    }