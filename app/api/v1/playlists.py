import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.playlist import Playlist, playlist_tracks
from app.models.track import Track
from app.models.user import User
from app.schemas.playlist import (
    PlaylistCreate,
    PlaylistDetailResponse,
    PlaylistResponse,
    PlaylistTrackAdd,
    PlaylistTrackReorder,
    PlaylistTrackResponse,
    PlaylistUpdate,
)

router = APIRouter(prefix="/playlists", tags=["Playlists"])

async def _get_owned_playlist(db: AsyncSession, user_id: uuid.UUID, playlist_id: uuid.UUID) -> Playlist:
    result = await db.execute(select(Playlist).where(Playlist.id == playlist_id, Playlist.user_id == user_id))
    playlist = result.scalar_one_or_none()
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist not found.")
    return playlist

async def _get_playlist_tracks(db: AsyncSession, playlist_id: uuid.UUID) -> list[PlaylistTrackResponse]:
    result = await db.execute(
        select(playlist_tracks.c.position, Track)
        .join(Track, Track.id == playlist_tracks.c.track_id)
        .where(playlist_tracks.c.playlist_id == playlist_id)
        .order_by(playlist_tracks.c.position.asc(), Track.title.asc())
    )
    return [
        PlaylistTrackResponse(
            position=position,
            track_id=track.id,
            title=track.title,
            artist_id=track.artist_id,
            album_id=track.album_id,
            duration_ms=track.duration_ms,
            musicbrainz_id=track.musicbrainz_id,
            is_available=track.is_available,
        )
        for position, track in result.all()
    ]

@router.post("", response_model=PlaylistResponse, status_code=status.HTTP_201_CREATED)
async def create_playlist(payload: PlaylistCreate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    playlist = Playlist(user_id=current_user.id, name=payload.name.strip(), description=payload.description, is_public=payload.is_public)
    db.add(playlist)
    await db.commit()
    await db.refresh(playlist)
    return playlist

@router.get("", response_model=list[PlaylistResponse])
async def list_playlists(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Playlist).where(Playlist.user_id == current_user.id).order_by(Playlist.created_at.desc()))
    return list(result.scalars().all())

@router.get("/{playlist_id}", response_model=PlaylistDetailResponse)
async def get_playlist(playlist_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    playlist = await _get_owned_playlist(db, current_user.id, playlist_id)
    tracks = await _get_playlist_tracks(db, playlist.id)
    return PlaylistDetailResponse.model_validate(playlist, from_attributes=True).model_copy(update={"tracks": tracks})

@router.patch("/{playlist_id}", response_model=PlaylistResponse)
async def update_playlist(playlist_id: uuid.UUID, payload: PlaylistUpdate, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    playlist = await _get_owned_playlist(db, current_user.id, playlist_id)
    values = payload.model_dump(exclude_unset=True)
    if "name" in values and values["name"] is not None:
        values["name"] = values["name"].strip()
        if not values["name"]:
            raise HTTPException(status_code=400, detail="Playlist name cannot be empty.")
    for key, value in values.items():
        setattr(playlist, key, value)
    playlist.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(playlist)
    return playlist

@router.delete("/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(playlist_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    playlist = await _get_owned_playlist(db, current_user.id, playlist_id)
    await db.delete(playlist)
    await db.commit()

@router.get("/{playlist_id}/tracks", response_model=list[PlaylistTrackResponse])
async def list_playlist_tracks(playlist_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_owned_playlist(db, current_user.id, playlist_id)
    return await _get_playlist_tracks(db, playlist_id)

@router.post("/{playlist_id}/tracks", response_model=list[PlaylistTrackResponse])
async def add_playlist_tracks(playlist_id: uuid.UUID, payload: PlaylistTrackAdd, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_owned_playlist(db, current_user.id, playlist_id)
    unique_ids = list(dict.fromkeys(payload.track_ids))
    result = await db.execute(select(Track.id).where(Track.id.in_(unique_ids)))
    existing_ids = set(result.scalars().all())
    missing = [str(track_id) for track_id in unique_ids if track_id not in existing_ids]
    if missing:
        raise HTTPException(status_code=404, detail={"message": "One or more tracks not found.", "track_ids": missing})
    result = await db.execute(select(playlist_tracks.c.track_id).where(playlist_tracks.c.playlist_id == playlist_id))
    current_ids = set(result.scalars().all())
    result = await db.execute(select(func.coalesce(func.max(playlist_tracks.c.position), -1)).where(playlist_tracks.c.playlist_id == playlist_id))
    next_position = int(result.scalar_one()) + 1
    for track_id in unique_ids:
        if track_id in current_ids:
            continue
        await db.execute(playlist_tracks.insert().values(playlist_id=playlist_id, track_id=track_id, position=next_position))
        next_position += 1
    await db.commit()
    return await _get_playlist_tracks(db, playlist_id)

@router.delete("/{playlist_id}/tracks/{track_id}", response_model=list[PlaylistTrackResponse])
async def remove_playlist_track(playlist_id: uuid.UUID, track_id: uuid.UUID, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_owned_playlist(db, current_user.id, playlist_id)
    result = await db.execute(delete(playlist_tracks).where(playlist_tracks.c.playlist_id == playlist_id, playlist_tracks.c.track_id == track_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Track is not in this playlist.")
    rows = await _get_playlist_tracks(db, playlist_id)
    for position, item in enumerate(rows):
        await db.execute(update(playlist_tracks).where(playlist_tracks.c.playlist_id == playlist_id, playlist_tracks.c.track_id == item.track_id).values(position=position))
    await db.commit()
    return await _get_playlist_tracks(db, playlist_id)

@router.put("/{playlist_id}/tracks/reorder", response_model=list[PlaylistTrackResponse])
async def reorder_playlist_tracks(playlist_id: uuid.UUID, payload: PlaylistTrackReorder, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    await _get_owned_playlist(db, current_user.id, playlist_id)
    requested = list(dict.fromkeys(payload.track_ids))
    result = await db.execute(select(playlist_tracks.c.track_id).where(playlist_tracks.c.playlist_id == playlist_id))
    existing = list(result.scalars().all())
    if set(requested) != set(existing) or len(requested) != len(existing):
        raise HTTPException(status_code=400, detail="track_ids must contain exactly the tracks currently in the playlist.")
    for position, track_id in enumerate(requested):
        await db.execute(update(playlist_tracks).where(playlist_tracks.c.playlist_id == playlist_id, playlist_tracks.c.track_id == track_id).values(position=position))
    await db.commit()
    return await _get_playlist_tracks(db, playlist_id)
