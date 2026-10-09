from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pathlib import Path

import re

from uuid import UUID

import jwt


from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from pydantic import BaseModel, Field

from fastapi.security import OAuth2PasswordBearer

from fastapi.responses import StreamingResponse

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

from app.core.database import get_db

from app.core.security import decode_access_token

from app.dependencies.auth import get_current_user

from app.models.track import Track

from app.models.user import User

from app.services.music.source_resolver import SourceResolverError, resolve_source


from app.services.music.streaming import (

    InvalidRangeError,

    StreamFileNotFoundError,

    StreamFileUnavailableError,

    StreamingService,

)

router = APIRouter(

    prefix="/stream",

    tags=["Streaming"],

)

optional_bearer = OAuth2PasswordBearer(

    tokenUrl="/api/v1/auth/token",

    auto_error=False,

)

streaming_service = StreamingService(

    settings.music_library_path

)

class OnlinePlaybackRequest(BaseModel):

    title: str = Field(min_length=1, max_length=300)

    artist: str | None = Field(default=None, max_length=300)

    album: str | None = Field(default=None, max_length=300)

    duration_ms: int | None = Field(default=None, ge=0, le=3_600_000)

    youtube_video_id: str | None = Field(default=None, min_length=11, max_length=20, pattern=r"^[A-Za-z0-9_-]+$")

@router.post("/online", summary="Prepare an official YouTube embedded player")
async def resolve_online_playback(
    body: OnlinePlaybackRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Prepare a selected track for playback with YouTube's official embedded player.

    If the frontend already has a YouTube video ID (from YouTube Music search),
    use it directly. Catalog/discovery tracks usually have no video ID, so find
    a matching YouTube video from their metadata. This only resolves the video
    identity; playback itself is handled by the official YouTube IFrame Player.
    """
    video_id = body.youtube_video_id

    if not video_id:
        try:
            source = await resolve_source(
                title=body.title,
                artist=body.artist,
                album=body.album,
                duration_ms=body.duration_ms,
            )
            video_id = source.video_id

            # Defensive fallback in case the resolver returns a URL but no ID.
            if not video_id and source.url:
                match = re.search(
                    r"(?:[?&]v=|youtu\.be/|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})(?:[?&#/]|$)",
                    source.url,
                )
                if match:
                    video_id = match.group(1)
        except SourceResolverError as exc:
            raise HTTPException(
                status_code=404,
                detail=f"Could not find a playable YouTube video for '{body.title}'. Try the YouTube Music search results instead.",
            ) from exc
        except Exception as exc:
            # Keep the internal traceback in the backend terminal, not in the API response.
            import logging
            logging.getLogger(__name__).exception("Could not resolve a YouTube video ID for online playback")
            raise HTTPException(
                status_code=503,
                detail="YouTube video lookup is temporarily unavailable. Please retry or choose a result from YouTube Music.",
            ) from exc

    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11,20}", video_id):
        raise HTTPException(
            status_code=404,
            detail="No playable YouTube video ID was found for this track. Choose a song or video from YouTube Music search.",
        )

    return {
        "provider": "youtube",
        "youtube_video_id": video_id,
        "title": body.title,
        "artist": body.artist,
        "album": body.album,
        "duration_ms": body.duration_ms,
        "embed_url": f"https://www.youtube.com/embed/{video_id}",
    }


def iter_file(

    file_path: Path,

    start: int,

    end: int,

    chunk_size: int = 1024 * 1024,

):

    """

    Stream a specific byte range from a local file.

    Default chunk size: 1 MB.

    """

    remaining = end - start + 1

    with file_path.open("rb") as file:

        file.seek(start)

        while remaining > 0:

            chunk = file.read(

                min(chunk_size, remaining)

            )

            if not chunk:

                break

            remaining -= len(chunk)

            yield chunk

@router.post("/{track_id}/ticket", summary="Create a short-lived playback ticket")

async def create_playback_ticket(

    track_id: UUID,

    db: AsyncSession = Depends(get_db),

    current_user: User = Depends(get_current_user),

):

    """Create a track-scoped token so the browser can use native audio streaming."""

    result = await db.execute(select(Track).where(Track.id == track_id))

    track = result.scalar_one_or_none()

    if track is None or not track.is_available:

        raise HTTPException(status_code=404, detail="Track is not available for playback.")

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

    ticket = jwt.encode(

        {

            "sub": str(current_user.id),

            "scope": "audio_stream",

            "track_id": str(track_id),

            "exp": expires_at,

        },

        settings.jwt_secret_key,

        algorithm=settings.jwt_algorithm,

    )

    return {"ticket": ticket, "expires_in": 1800}

@router.get(

    "/{track_id}",

    summary="Stream Track",

)

async def stream_track(

    track_id: UUID,

    request: Request,

    ticket: str | None = Query(default=None),

    bearer_token: str | None = Depends(optional_bearer),

    db: AsyncSession = Depends(get_db),

):

    """

    Stream a downloaded track.

    Supports HTTP byte-range requests for seeking and

    partial playback.

    """

    credentials_exception = HTTPException(

        status_code=status.HTTP_401_UNAUTHORIZED,

        detail="A valid access token or playback ticket is required.",

        headers={"WWW-Authenticate": "Bearer"},

    )

    token_to_validate = ticket or bearer_token

    if not token_to_validate:

        raise credentials_exception

    try:

        payload = decode_access_token(token_to_validate)

        if ticket:

            if payload.get("scope") != "audio_stream" or payload.get("track_id") != str(track_id):

                raise credentials_exception

        subject = payload.get("sub")

        user_id = UUID(subject) if subject else None

        if user_id is None:

            raise credentials_exception

    except Exception as exc:

        raise credentials_exception from exc

    user_result = await db.execute(select(User).where(User.id == user_id))

    authenticated_user = user_result.scalar_one_or_none()

    if authenticated_user is None or not authenticated_user.is_active:

        raise credentials_exception

    result = await db.execute(

        select(Track).where(

            Track.id == track_id

        )

    )

    track = result.scalar_one_or_none()

    if track is None:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="Track not found.",

        )

    try:

        stream_file = streaming_service.resolve_file(

            file_path=track.file_path,

            is_available=track.is_available,

            mime_type=track.mime_type,

        )

    except StreamFileUnavailableError as exc:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail=str(exc),

        ) from exc

    except StreamFileNotFoundError as exc:

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail=str(exc),

        ) from exc

    file_size = stream_file.file_size

    range_header = request.headers.get("range")

    try:

        byte_range = streaming_service.parse_range(

            range_header=range_header,

            file_size=file_size,

        )

    except InvalidRangeError as exc:

        return StreamingResponse(

            content=iter(()),

            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,

            headers={

                "Content-Range": f"bytes */{file_size}",

                "Accept-Ranges": "bytes",

            },

        )

    # =========================================================

    # FULL FILE

    # =========================================================

    if byte_range is None:

        start = 0

        end = file_size - 1

        headers = {

            "Accept-Ranges": "bytes",

            "Content-Length": str(file_size),

            "Content-Range": f"bytes {start}-{end}/{file_size}",

            "Cache-Control": "private, max-age=3600",

        }

        return StreamingResponse(

            content=iter_file(

                stream_file.path,

                start,

                end,

            ),

            status_code=status.HTTP_200_OK,

            media_type=stream_file.media_type,

            headers=headers,

        )

    # =========================================================

    # PARTIAL FILE

    # =========================================================

    start = byte_range.start

    end = byte_range.end

    content_length = byte_range.length

    headers = {

        "Accept-Ranges": "bytes",

        "Content-Length": str(content_length),

        "Content-Range": f"bytes {start}-{end}/{file_size}",

        "Cache-Control": "private, max-age=3600",

    }

    return StreamingResponse(

        content=iter_file(

            stream_file.path,

            start,

            end,

        ),

        status_code=status.HTTP_206_PARTIAL_CONTENT,

        media_type=stream_file.media_type,

        headers=headers,

    )