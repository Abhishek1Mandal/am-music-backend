from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.track import Track
from app.models.user import User
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


streaming_service = StreamingService(
    settings.music_library_path
)


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


@router.get(
    "/{track_id}",
    summary="Stream Track",
)
async def stream_track(
    track_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Stream a downloaded track.

    Supports HTTP byte-range requests for seeking and
    partial playback.
    """

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