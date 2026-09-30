from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.schemas.metadata import MusicSearchResponse
from app.services.metadata.musicbrainz import (
    musicbrainz_service,
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
        description="Music search query",
    ),
    limit: int = Query(
        default=None,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
):
    """
    Search artists, albums and tracks using MusicBrainz.
    """

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
        return await musicbrainz_service.search(
            query=query,
            limit=search_limit,
            offset=offset,
        )

    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to fetch music metadata "
                "from MusicBrainz."
            ),
        ) from exc