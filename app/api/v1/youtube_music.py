from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.services.providers.youtube_music import search_youtube_music

router = APIRouter(prefix="/youtube-music", tags=["YouTube Music Provider"])


@router.get("/search", summary="Search YouTube Music metadata")
async def search_provider(
    q: str = Query(..., min_length=1, max_length=200),
    filter: str = Query(default="songs", pattern="^(songs|videos|albums|artists|playlists)$"),
    limit: int = Query(default=20, ge=1, le=50),
    _current_user: User = Depends(get_current_user),
):
    """Search public YouTube Music metadata; this endpoint does not require cookies."""
    try:
        items = await search_youtube_music(q, filter, limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        message = str(exc).lower()
        if "429" in message or "too many requests" in message:
            raise HTTPException(status_code=503, detail="YouTube Music is rate-limiting requests. Retry shortly.") from exc
        raise HTTPException(status_code=502, detail="YouTube Music search is temporarily unavailable.") from exc
    return {"query": q.strip(), "filter": filter, "count": len(items), "items": items}
