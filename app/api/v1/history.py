import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.play_history import PlayHistory
from app.models.track import Track
from app.models.user import User
from app.schemas.history import HistoryItem, PlaybackPositionResponse, PlaybackPositionUpdate, PlayCreate

router = APIRouter(prefix="/history", tags=["History"])

async def _track_or_404(db: AsyncSession, track_id: uuid.UUID) -> Track:
    result = await db.execute(select(Track).where(Track.id == track_id))
    track = result.scalar_one_or_none()
    if track is None:
        raise HTTPException(status_code=404, detail="Track not found.")
    return track

@router.get("", response_model=dict)
async def get_history(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(PlayHistory, Track).join(Track, Track.id == PlayHistory.track_id).where(PlayHistory.user_id == current_user.id).order_by(PlayHistory.played_at.desc()).offset(offset).limit(limit))
    items = [HistoryItem(id=h.id, track_id=t.id, title=t.title, artist_id=t.artist_id, album_id=t.album_id, played_at=h.played_at, position_ms=h.position_ms, completed=h.completed) for h, t in result.all()]
    return {"items": items, "count": len(items), "limit": limit, "offset": offset}

@router.post("/{track_id}", response_model=HistoryItem, status_code=status.HTTP_201_CREATED)
async def record_history(track_id: uuid.UUID, payload: PlayCreate | None = None, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    track = await _track_or_404(db, track_id)
    history = PlayHistory(user_id=current_user.id, track_id=track.id, position_ms=payload.position_ms if payload else None, completed=False)
    db.add(history)
    await db.commit()
    await db.refresh(history)
    return HistoryItem(id=history.id, track_id=track.id, title=track.title, artist_id=track.artist_id, album_id=track.album_id, played_at=history.played_at, position_ms=history.position_ms, completed=history.completed)

@router.get("/track/{track_id}/count")
async def get_play_count(track_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    await _track_or_404(db, track_id)
    result = await db.execute(select(func.count(PlayHistory.id)).where(PlayHistory.user_id == current_user.id, PlayHistory.track_id == track_id))
    return {"track_id": track_id, "play_count": int(result.scalar_one())}

@router.get("/track/{track_id}/position", response_model=PlaybackPositionResponse)
async def get_playback_position(track_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    await _track_or_404(db, track_id)
    result = await db.execute(select(PlayHistory).where(PlayHistory.user_id == current_user.id, PlayHistory.track_id == track_id).order_by(PlayHistory.played_at.desc()).limit(1))
    history = result.scalar_one_or_none()
    if history is None:
        return PlaybackPositionResponse(track_id=track_id, position_ms=0, completed=False, updated_at=None)
    return PlaybackPositionResponse(track_id=track_id, position_ms=history.position_ms or 0, completed=history.completed, updated_at=history.played_at)

@router.put("/track/{track_id}/position", response_model=PlaybackPositionResponse)
async def save_playback_position(track_id: uuid.UUID, payload: PlaybackPositionUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    track = await _track_or_404(db, track_id)
    result = await db.execute(select(PlayHistory).where(PlayHistory.user_id == current_user.id, PlayHistory.track_id == track_id).order_by(PlayHistory.played_at.desc()).limit(1))
    history = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if history is None:
        history = PlayHistory(user_id=current_user.id, track_id=track.id, position_ms=payload.position_ms)
        db.add(history)
    else:
        history.position_ms = 0 if payload.completed else payload.position_ms
        history.completed = payload.completed
        history.played_at = now
    await db.commit()
    return PlaybackPositionResponse(track_id=track_id, position_ms=0 if payload.completed else payload.position_ms, completed=payload.completed, updated_at=now)

@router.delete("/track/{track_id}/position")
async def clear_playback_position(track_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    await _track_or_404(db, track_id)
    result = await db.execute(select(PlayHistory).where(PlayHistory.user_id == current_user.id, PlayHistory.track_id == track_id).order_by(PlayHistory.played_at.desc()).limit(1))
    history = result.scalar_one_or_none()
    if history:
        history.position_ms = 0
        await db.commit()
    return {"track_id": track_id, "position_ms": 0, "completed": True}

@router.get("/{history_id}", response_model=HistoryItem)
async def get_history_item(history_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(PlayHistory, Track).join(Track, Track.id == PlayHistory.track_id).where(PlayHistory.id == history_id, PlayHistory.user_id == current_user.id))
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="History entry not found.")
    h, t = row
    return HistoryItem(id=h.id, track_id=t.id, title=t.title, artist_id=t.artist_id, album_id=t.album_id, played_at=h.played_at, position_ms=h.position_ms, completed=h.completed)

@router.delete("/{history_id}")
async def delete_history_item(history_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(PlayHistory).where(PlayHistory.id == history_id, PlayHistory.user_id == current_user.id))
    history = result.scalar_one_or_none()
    if history is None:
        raise HTTPException(status_code=404, detail="History entry not found.")
    await db.delete(history)
    await db.commit()
    return {"message": "History entry deleted.", "id": history_id}

@router.delete("")
async def clear_history(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(delete(PlayHistory).where(PlayHistory.user_id == current_user.id))
    await db.commit()
    return {"message": "Listening history cleared.", "deleted_count": result.rowcount}
