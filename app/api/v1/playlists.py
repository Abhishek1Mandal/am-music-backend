import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.playlist import Playlist
from app.models.user import User
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistResponse,
)

router = APIRouter(
    prefix="/playlists",
    tags=["Playlists"],
)


@router.post(
    "/",
    response_model=PlaylistResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_playlist(
    payload: PlaylistCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    playlist = Playlist(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        is_public=payload.is_public,
    )

    db.add(playlist)

    await db.commit()
    await db.refresh(playlist)

    return playlist


@router.get(
    "/",
    response_model=list[PlaylistResponse],
)
async def list_playlists(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Playlist)
        .where(
            Playlist.user_id == current_user.id
        )
        .order_by(Playlist.created_at.desc())
    )

    return result.scalars().all()


@router.get(
    "/{playlist_id}",
    response_model=PlaylistResponse,
)
async def get_playlist(
    playlist_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Playlist).where(
            Playlist.id == playlist_id,
            Playlist.user_id == current_user.id,
        )
    )

    playlist = result.scalar_one_or_none()

    if playlist is None:
        raise HTTPException(
            status_code=404,
            detail="Playlist not found",
        )

    return playlist