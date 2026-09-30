from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.metadata import MusicSearchResponse
from app.services.metadata.musicbrainz import (
    musicbrainz_service,
)
from app.services.music.download_library import (
    get_user_downloaded_track_ids,
)


router = APIRouter(
    prefix="/search",
    tags=["Search"],
)


@router.get(
    "",
    response_model=MusicSearchResponse,
)
async def search_music(
    q: str = Query(
        ...,
        min_length=1,
        max_length=200,
    ),
    limit: int | None = Query(
        default=None,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        get_current_user
    ),
):
    search_limit = (
        limit
        if limit is not None
        else settings.music_search_limit
    )

    query = q.strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Search query cannot be empty.",
        )

    try:
        response = await musicbrainz_service.search(
            query=query,
            limit=search_limit,
            offset=offset,
        )

        musicbrainz_ids = [
            track.mbid
            for track in response.tracks
            if track.mbid
        ]

        downloaded_track_ids = (
            await get_user_downloaded_track_ids(
                db,
                current_user.id,
                musicbrainz_ids,
            )
        )

        for track in response.tracks:
            track.is_downloaded = (
                track.mbid
                in downloaded_track_ids
            )

        return response

    except HTTPException:
        raise

    except Exception as exc:
        import traceback

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        ) from exc