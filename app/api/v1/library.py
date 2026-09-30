from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.library import LibraryItem
from app.models.track import Track
from app.models.user import User


router = APIRouter(
    prefix="/library",
    tags=["Library"],
)


# ============================================================
# GET USER LIBRARY
# ============================================================

@router.get("")
async def get_library(
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
    query = (
        select(LibraryItem, Track)
        .join(
            Track,
            LibraryItem.track_id == Track.id,
        )
        .where(
            LibraryItem.user_id == current_user.id,
        )
        .order_by(
            LibraryItem.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)

    rows = result.all()

    items = []

    for library_item, track in rows:
        items.append(
            {
                "id": library_item.id,
                "track_id": track.id,
                "title": track.title,
                "artist_id": track.artist_id,
                "album_id": track.album_id,
                "duration_ms": track.duration_ms,
                "musicbrainz_id": track.musicbrainz_id,
                "is_available": track.is_available,
            }
        )

    return {
        "items": items,
        "limit": limit,
        "offset": offset,
    }


# ============================================================
# ADD TRACK TO LIBRARY
# ============================================================

@router.post(
    "/{track_id}",
    status_code=status.HTTP_201_CREATED,
)
async def add_to_library(
    track_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # --------------------------------------------------------
    # Check track
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
            detail="Track not found",
        )

    # --------------------------------------------------------
    # Check duplicate
    # --------------------------------------------------------

    existing_result = await db.execute(
        select(LibraryItem).where(
            LibraryItem.user_id == current_user.id,
            LibraryItem.track_id == track_id,
        )
    )

    existing_item = existing_result.scalar_one_or_none()

    if existing_item is not None:
        return {
            "id": existing_item.id,
            "track_id": existing_item.track_id,
            "message": "Track already exists in library",
        }

    # --------------------------------------------------------
    # Create library item
    # --------------------------------------------------------

    library_item = LibraryItem(
        user_id=current_user.id,
        track_id=track_id,
    )

    db.add(library_item)

    await db.commit()

    await db.refresh(library_item)

    return {
        "id": library_item.id,
        "track_id": library_item.track_id,
        "message": "Track added to library",
    }


# ============================================================
# GET LIBRARY STATUS
# ============================================================

@router.get(
    "/{track_id}/status",
)
async def get_library_status(
    track_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LibraryItem).where(
            LibraryItem.user_id == current_user.id,
            LibraryItem.track_id == track_id,
        )
    )

    library_item = result.scalar_one_or_none()

    if library_item is None:
        return {
            "track_id": track_id,
            "in_library": False,
            "library_id": None,
        }

    return {
        "track_id": track_id,
        "in_library": True,
        "library_id": library_item.id,
    }


# ============================================================
# REMOVE TRACK FROM LIBRARY
# ============================================================

@router.delete(
    "/{track_id}",
)
async def remove_from_library(
    track_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LibraryItem).where(
            LibraryItem.user_id == current_user.id,
            LibraryItem.track_id == track_id,
        )
    )

    library_item = result.scalar_one_or_none()

    if library_item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track is not in your library",
        )

    await db.delete(library_item)

    await db.commit()

    return {
        "track_id": track_id,
        "message": "Track removed from library",
    }


# ============================================================
# CLEAR USER LIBRARY
# ============================================================

@router.delete("")
async def clear_library(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(LibraryItem).where(
            LibraryItem.user_id == current_user.id,
        )
    )

    library_items = result.scalars().all()

    deleted_count = len(library_items)

    for library_item in library_items:
        await db.delete(library_item)

    await db.commit()

    return {
        "message": "Library cleared",
        "deleted_count": deleted_count,
    }