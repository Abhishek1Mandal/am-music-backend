from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.favorite import Favorite
from app.models.track import Track
from app.models.user import User


router = APIRouter(
    prefix="/favorites",
    tags=["Favorites"],
)


# ============================================================
# GET FAVORITES
# ============================================================


@router.get(
    "",
    summary="Get Favorites",
)
async def get_favorites(
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get favorite tracks for the authenticated user.
    """

    result = await db.execute(
        select(Favorite, Track)
        .join(
            Track,
            Track.id == Favorite.track_id,
        )
        .where(
            Favorite.user_id == current_user.id,
        )
        .order_by(
            Favorite.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    rows = result.all()

    items = []

    for favorite, track in rows:
        items.append(
            {
                "id": favorite.id,
                "track_id": track.id,
                "title": track.title,
                "artist_id": track.artist_id,
                "album_id": track.album_id,
                "duration_ms": track.duration_ms,
                "musicbrainz_id": track.musicbrainz_id,
                "is_available": track.is_available,
                "created_at": favorite.created_at,
            }
        )

    return {
        "items": items,
        "count": len(items),
        "limit": limit,
        "offset": offset,
    }


# ============================================================
# ADD FAVORITE
# ============================================================


@router.post(
    "/{track_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Add Favorite",
)
async def add_favorite(
    track_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add a track to the authenticated user's favorites.
    """

    # --------------------------------------------------------
    # Check track exists
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Check existing favorite
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Create favorite
    # --------------------------------------------------------

    favorite = Favorite(
        user_id=current_user.id,
        track_id=track_id,
    )

    db.add(favorite)

    try:
        await db.commit()

    except IntegrityError:
        # Protect against a race where another request creates
        # the same favorite between our SELECT and INSERT.
        await db.rollback()

        existing_result = await db.execute(
            select(Favorite).where(
                Favorite.user_id == current_user.id,
                Favorite.track_id == track_id,
            )
        )

        existing = existing_result.scalar_one_or_none()

        if existing is not None:
            return {
                "message": "Track is already in favorites.",
                "favorite_id": existing.id,
                "track_id": track_id,
            }

        raise

    await db.refresh(favorite)

    return {
        "message": "Track added to favorites.",
        "favorite_id": favorite.id,
        "track_id": favorite.track_id,
        "created_at": favorite.created_at,
    }


# ============================================================
# FAVORITE STATUS
# ============================================================


@router.get(
    "/{track_id}/status",
    summary="Favorite Status",
)
async def favorite_status(
    track_id: UUID,
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
            if favorite is not None
            else None
        ),
    }


# ============================================================
# REMOVE FAVORITE
# ============================================================


@router.delete(
    "/{track_id}",
    summary="Remove Favorite",
)
async def remove_favorite(
    track_id: UUID,
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


# ============================================================
# CLEAR FAVORITES
# ============================================================


@router.delete(
    "",
    summary="Clear Favorites",
)
async def clear_favorites(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Remove all favorites belonging to the authenticated user.
    """

    result = await db.execute(
        select(Favorite).where(
            Favorite.user_id == current_user.id,
        )
    )

    favorites = result.scalars().all()

    deleted_count = len(favorites)

    for favorite in favorites:
        await db.delete(favorite)

    await db.commit()

    return {
        "message": "Favorites cleared.",
        "deleted_count": deleted_count,
    }