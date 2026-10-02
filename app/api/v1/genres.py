import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.genre import Genre
from app.models.track import Track
from app.models.user import User
from app.schemas.genre import GenreCreate, GenreResponse, GenreTrackResponse
from app.models.track import Track as TrackModel

from sqlalchemy import Table, Column
from app.core.database import Base

track_genres = Base.metadata.tables["track_genres"]

router = APIRouter(prefix="/genres", tags=["Genres"])

@router.get("", response_model=list[GenreResponse])
async def list_genres(limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Genre).order_by(Genre.name.asc()).limit(limit))
    return [GenreResponse(id=g.id, name=g.name) for g in result.scalars().all()]

@router.post("", response_model=GenreResponse, status_code=status.HTTP_201_CREATED)
async def create_genre(payload: GenreCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    name = payload.name.strip()
    result = await db.execute(select(Genre).where(func.lower(Genre.name) == name.lower()))
    genre = result.scalar_one_or_none()
    if genre is not None:
        return GenreResponse(id=genre.id, name=genre.name)
    genre = Genre(name=name)
    db.add(genre)
    await db.commit()
    await db.refresh(genre)
    return GenreResponse(id=genre.id, name=genre.name)

@router.get("/{genre_id}/tracks", response_model=list[GenreTrackResponse])
async def genre_tracks(genre_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Genre).where(Genre.id == genre_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Genre not found.")
    result = await db.execute(
        select(Track)
        .join(track_genres, track_genres.c.track_id == Track.id)
        .where(track_genres.c.genre_id == genre_id)
        .order_by(Track.title.asc())
        .offset(offset).limit(limit)
    )
    return [GenreTrackResponse(id=t.id, title=t.title, artist_id=t.artist_id, album_id=t.album_id, duration_ms=t.duration_ms, musicbrainz_id=t.musicbrainz_id, is_available=t.is_available) for t in result.scalars().all()]

@router.post("/{genre_id}/tracks/{track_id}")
async def add_track_to_genre(genre_id: uuid.UUID, track_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    genre_result = await db.execute(select(Genre).where(Genre.id == genre_id))
    if genre_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Genre not found.")
    track_result = await db.execute(select(Track).where(Track.id == track_id))
    if track_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Track not found.")
    existing = await db.execute(select(track_genres.c.track_id).where(track_genres.c.genre_id == genre_id, track_genres.c.track_id == track_id))
    if existing.scalar_one_or_none() is None:
        await db.execute(track_genres.insert().values(genre_id=genre_id, track_id=track_id))
        await db.commit()
    return {"message": "Track added to genre.", "genre_id": genre_id, "track_id": track_id}

@router.delete("/{genre_id}/tracks/{track_id}")
async def remove_track_from_genre(genre_id: uuid.UUID, track_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(delete(track_genres).where(track_genres.c.genre_id == genre_id, track_genres.c.track_id == track_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Track is not assigned to this genre.")
    await db.commit()
    return {"message": "Track removed from genre.", "genre_id": genre_id, "track_id": track_id}
