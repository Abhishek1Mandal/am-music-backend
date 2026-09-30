import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.artist import Artist
from app.schemas.artist import ArtistResponse

router = APIRouter(prefix="/artists", tags=["Artists"])


@router.get(
    "/",
    response_model=list[ArtistResponse],
)
async def list_artists(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Artist)
        .order_by(Artist.name)
        .limit(100)
    )

    return result.scalars().all()


@router.get(
    "/{artist_id}",
    response_model=ArtistResponse,
)
async def get_artist(
    artist_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Artist).where(
            Artist.id == artist_id
        )
    )

    artist = result.scalar_one_or_none()

    if artist is None:
        raise HTTPException(
            status_code=404,
            detail="Artist not found",
        )

    return artist