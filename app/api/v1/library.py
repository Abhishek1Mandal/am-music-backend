from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
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


@router.get("")
async def get_library(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get tracks saved in the authenticated user's library.
    """

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Limit must be between 1 and 100.",
        )

    if offset < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Offset cannot be negative.",
        )

    result = await db.execute(
        select(LibraryItem, Track)
        .join(
            Track,
            Track.id == LibraryItem.track_id,
        )
        .where(
            LibraryItem.user_id == current_user.id,
        )
        .order_by(
            LibraryItem.created_at.desc(),
        )
        .offset(offset)
        .limit(limit)
    )

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
                "created_at": library_item.created_at,
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
)
async def add_to_library(
    track_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add a track to the authenticated user's library.
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

    existing_result = await db.execute(
        select(LibraryItem).where(
            LibraryItem.user_id == current_user.id,
            LibraryItem.track_id == track_id,
        )
    )

    existing = existing_result.scalar_one_or_none()

    if existing is not None:
        return {
            "message": "Track is already in the library.",
            "library_id": existing.id,
            "track_id": track_id,
        }

    library_item = LibraryItem(
        user_id=current_user.id,
        track_id=track_id,
    )

    db.add(library_item)

    await db.commit()
    await db.refresh(library_item)

    return {
        "message": "Track added to library.",
        "library_id": library_item.id,
        "track_id": library_item.track_id,
        "created_at": library_item.created_at,
    }


@router.get("/{track_id}/status")
async def library_status(
    track_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Check whether a track exists in the user's library.
    """

    result = await db.execute(
        select(LibraryItem).where(
            LibraryItem.user_id == current_user.id,
            LibraryItem.track_id == track_id,
        )
    )

    library_item = result.scalar_one_or_none()

    return {
        "track_id": track_id,
        "in_library": library_item is not None,
        "library_id": (
            library_item.id
            if library_item
            else None
        ),
    }


@router.delete("/{track_id}")
async def remove_from_library(
    track_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Remove a track from the authenticated user's library.
    """

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
            detail="Track is not in the library.",
        )

    await db.delete(library_item)

    await db.commit()

    return {
        "message": "Track removed from library.",
        "track_id": track_id,
    }


@router.delete("")
async def clear_library(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Remove all tracks from the authenticated user's library.
    """

    result = await db.execute(
        delete(LibraryItem).where(
            LibraryItem.user_id == current_user.id,
        )
    )

    await db.commit()

    return {
        "message": "Library cleared.",
        "deleted_count": result.rowcount,
    }