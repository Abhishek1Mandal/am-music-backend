from __future__ import annotations

import asyncio
import traceback

import httpx

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
from app.services.music.source_resolver import (
    SourceResolverError,
    resolve_source,
)


router = APIRouter(
    prefix="/search",
    tags=["Search"],
)


# Limit concurrent YouTube searches.
#
# Without this, searching for 20 MusicBrainz tracks could result
# in many simultaneous yt-dlp requests.
YOUTUBE_SEARCH_CONCURRENCY = 4


async def _check_youtube_availability(
    track,
    semaphore: asyncio.Semaphore,
) -> None:
    """
    Check whether a suitable YouTube source exists for a MusicBrainz
    recording.

    The existing source resolver performs:
        - YouTube search
        - title matching
        - artist matching
        - duration matching
        - score calculation
        - minimum score validation
    """

    if not track.mbid:
        return

    if not track.title:
        return

    async with semaphore:
        try:
            resolved_source = await resolve_source(
                title=track.title,
                artist=track.artist_name,
                album=track.album_name,
                duration_ms=track.duration_ms,
            )

        except SourceResolverError:
            track.youtube_available = False
            track.youtube_url = None
            track.youtube_score = None
            return

        except Exception:
            # A YouTube failure should not make the entire
            # MusicBrainz search request fail.
            track.youtube_available = False
            track.youtube_url = None
            track.youtube_score = None
            return

    track.youtube_available = True
    track.youtube_url = resolved_source.url
    track.youtube_score = round(
        resolved_source.score,
        4,
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
    limit: int | None = Query(
        default=None,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    check_youtube: bool = Query(
        default=True,
        description=(
            "Check YouTube availability for MusicBrainz "
            "track results."
        ),
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(
        get_current_user
    ),
):
    """
    Search MusicBrainz for artists, albums and tracks.

    For track results, the API also checks whether a sufficiently
    matching YouTube source can currently be resolved.

    Example:

        GET /api/v1/search?q=Aaya%20Sher

    With YouTube checking:

        GET /api/v1/search?q=Aaya%20Sher&check_youtube=true

    To skip YouTube checks:

        GET /api/v1/search?q=Aaya%20Sher&check_youtube=false
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

    # ==========================================================
    # 1. MusicBrainz search
    # ==========================================================

    try:
        response = await musicbrainz_service.search(
            query=query,
            limit=search_limit,
            offset=offset,
        )

    except httpx.HTTPStatusError as exc:
        # ------------------------------------------------------
        # MusicBrainz returned an HTTP error after all retries.
        # ------------------------------------------------------

        status_code = (
            exc.response.status_code
            if exc.response is not None
            else None
        )

        if status_code == 429:
            raise HTTPException(
                status_code=429,
                detail=(
                    "MusicBrainz rate limit reached. "
                    "Please try again shortly."
                ),
            ) from exc

        if status_code in {
            500,
            502,
            503,
            504,
        }:
            raise HTTPException(
                status_code=503,
                detail=(
                    "MusicBrainz is temporarily unavailable. "
                    "Please try again shortly."
                ),
            ) from exc

        # Other HTTP errors.
        raise HTTPException(
            status_code=502,
            detail=(
                "MusicBrainz search request failed."
            ),
        ) from exc

    except (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    ) as exc:
        # ------------------------------------------------------
        # MusicBrainz could not be reached even after retries.
        # ------------------------------------------------------

        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to reach MusicBrainz right now. "
                "Please try again shortly."
            ),
        ) from exc

    except Exception as exc:
        # ------------------------------------------------------
        # Unexpected MusicBrainz failure.
        #
        # Keep the actual traceback in the backend logs but do
        # not expose implementation details to the client.
        # ------------------------------------------------------

        traceback.print_exc()

        raise HTTPException(
            status_code=502,
            detail=(
                "Unable to complete MusicBrainz search."
            ),
        ) from exc

    # ==========================================================
    # 2. Local download status
    # ==========================================================

    try:
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

    except Exception as exc:
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=(
                "Music search succeeded, but local "
                "download status could not be loaded."
            ),
        ) from exc

    # ==========================================================
    # 3. YouTube availability
    # ==========================================================

    if check_youtube and response.tracks:

        semaphore = asyncio.Semaphore(
            YOUTUBE_SEARCH_CONCURRENCY
        )

        youtube_tasks = [
            _check_youtube_availability(
                track,
                semaphore,
            )
            for track in response.tracks
        ]

        # _check_youtube_availability() intentionally catches
        # resolver failures per track, so one bad YouTube lookup
        # cannot fail the entire search.
        await asyncio.gather(
            *youtube_tasks
        )

    return response