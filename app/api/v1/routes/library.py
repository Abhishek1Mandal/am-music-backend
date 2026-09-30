import math
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.library_item import LibraryItem
from app.models.track import Track
from app.models.user import User
from app.api.v1.dependencies.auth import get_current_user

from app.schemas.library import (
    LibraryItemResponse,
    LibraryListResponse,
    LibraryMessageResponse,
    LibraryStatusResponse,
    LibraryTrackResponse,
)


router = APIRouter(
    prefix="/library",
    tags=["Library"],
)


@router.get(
    "",
    response_model=LibraryListResponse,
    status_code=status.HTTP_200_OK,
)
async def get_library(
    page: int = Query(
        default=1,
        ge=1,
        description="Page number",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=100,
        description="Number of items per page",
    ),
    sort: str = Query(
        default="added_at",
        pattern="^(added_at|title)$",
        description="Sort field",
    ),
    order: str = Query(
        default="desc",
        pattern="^(asc|desc)$",
        description="Sort direction",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get the authenticated user's music library.
    """

    base_query = (
        select(LibraryItem)
        .join(Track, Track.id == LibraryItem.track_id)
        .where(LibraryItem.user_id == current_user.id)
    )

    count_query = (
        select(func.count())
        .select_from(LibraryItem)
        .where(
            LibraryItem.user_id == current_user.id
        )
    )

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    if sort == "title":
        sort_column = Track.title
    else:
        sort_column = LibraryItem.added_at

    if order == "asc":
        base_query = base_query.order_by(sort_column.asc())
    else:
        base_query = base_query.order_by(sort_column.desc())

    offset = (page - 1) * limit

    base_query = (
        base_query
        .options(
            selectinload(LibraryItem.track)
            .selectinload(Track.artist),
            selectinload(LibraryItem.track)
            .selectinload(Track.album),
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(base_query)

    library_items = result.scalars().unique().all()

    total_pages = math.ceil(total / limit) if total else 0

    response_items = []

    for item in library_items:
        track = item.track

        track_response = LibraryTrackResponse(
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

        response_items.append(
            LibraryItemResponse(
                id=item.id,
                track_id=item.track_id,
                added_at=item.added_at,
                track=track_response,
            )
        )

    return LibraryListResponse(
        items=response_items,
        page=page,
        limit=limit,
        total=total,
        total_pages=total_pages,
    )


@router.get(
    "/{track_id}",
    response_model=LibraryStatusResponse,
    status_code=status.HTTP_200_OK,
)
async def get_library_status(
    track_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Check whether a track belongs to the authenticated user's library.
    """

    track_result = await db.execute(
        select(Track).where(
            Track.id == track_id
        )
    )

    track = track_result.scalar_one_or_none()

    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found",
        )

    library_result = await db.execute(
        select(LibraryItem.id).where(
            LibraryItem.user_id == current_user.id,
            LibraryItem.track_id == track_id,
        )
    )

    library_item_id = library_result.scalar_one_or_none()

    return LibraryStatusResponse(
        track_id=track_id,
        is_in_library=library_item_id is not None,
        is_available=bool(track.is_available),
    )


@router.post(
    "/{track_id}",
    response_model=LibraryMessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_to_library(
    track_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Add a downloaded track to the authenticated user's library.
    """

    track_result = await db.execute(
        select(Track).where(
            Track.id == track_id
        )
    )

    track = track_result.scalar_one_or_none()

    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found",
        )

    if not track.is_available:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Track is not available locally",
        )

    existing_result = await db.execute(
        select(LibraryItem).where(
            LibraryItem.user_id == current_user.id,
            LibraryItem.track_id == track_id,
        )
    )

    existing_item = existing_result.scalar_one_or_none()

    if existing_item is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Track is already in the library",
        )

    library_item = LibraryItem(
        user_id=current_user.id,
        track_id=track_id,
    )

    db.add(library_item)

    await db.commit()

    return LibraryMessageResponse(
        message="Track added to library",
        track_id=track_id,
    )


@router.delete(
    "/{track_id}",
    response_model=LibraryMessageResponse,
    status_code=status.HTTP_200_OK,
)
async def remove_from_library(
    track_id: uuid.UUID,
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
            detail="Track is not in the library",
        )

    await db.delete(library_item)

    await db.commit()

    return LibraryMessageResponse(
        message="Track removed from library",
        track_id=track_id,
    )