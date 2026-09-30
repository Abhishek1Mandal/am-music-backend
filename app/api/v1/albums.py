import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.album import Album
from app.schemas.album import AlbumResponse

router = APIRouter(prefix="/albums", tags=["Albums"])


@router.get(
    "/",
    response_model=list[AlbumResponse],
)
async def list_albums(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Album)
        .order_by(Album.title)
        .limit(100)
    )

    return result.scalars().all()


@router.get(
    "/{album_id}",
    response_model=AlbumResponse,
)
async def get_album(
    album_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Album).where(
            Album.id == album_id
        )
    )

    album = result.scalar_one_or_none()

    if album is None:
        raise HTTPException(
            status_code=404,
            detail="Album not found",
        )

    return album