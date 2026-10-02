import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.album import Album
from app.models.artist import Artist
from app.models.track import Track
from app.models.user import User
from app.services.metadata.cover_art import cover_art_service
from app.services.music.tagging import read_audio_tags, tag_audio_file

router = APIRouter(prefix="/metadata", tags=["Metadata"])

@router.post("/tracks/{track_id}/tag")
async def tag_track(track_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None or not track.file_path:
        raise HTTPException(status_code=404, detail="Track or audio file not found.")
    artist = await db.get(Artist, track.artist_id)
    album = await db.get(Album, track.album_id) if track.album_id else None
    artwork_url = cover_art_service.get_front_cover_url(album.musicbrainz_id, 1200) if album and album.musicbrainz_id else None
    result = await tag_audio_file(track.file_path, title=track.title, artist=artist.name if artist else None, album=album.title if album else None, musicbrainz_id=track.musicbrainz_id, album_artist=artist.name if artist else None, artwork_url=artwork_url)
    return result

@router.get("/tracks/{track_id}/tags")
async def get_track_tags(track_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None or not track.file_path:
        raise HTTPException(status_code=404, detail="Track or audio file not found.")
    return read_audio_tags(track.file_path)
