from __future__ import annotations

from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.album import Album
from app.models.user import User
from app.services.music.artwork import (
    ArtworkDownloadError,
    ArtworkNotFoundError,
    ArtworkStorageError,
    artwork_service,
)


router = APIRouter(
    prefix="/artwork",
    tags=["Artwork"],
)


# ==========================================================
# GET ARTWORK INFORMATION
# ==========================================================


@router.get(
    "/album/{album_id}",
    summary="Get Album Artwork",
)
async def get_album_artwork(
    album_id: UUID,
    force: bool = Query(
        default=False,
        description="Force re-download of cached artwork.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get album artwork information.

    The artwork is downloaded from Cover Art Archive
    when it is not already cached locally.
    """

    album_result = await db.execute(
        select(Album).where(
            Album.id == album_id
        )
    )

    album = album_result.scalar_one_or_none()

    if album is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found.",
        )

    if not album.musicbrainz_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Album does not have a "
                "MusicBrainz release ID."
            ),
        )

    try:
        artwork = (
            await artwork_service.download_artwork(
                album_mbid=album.musicbrainz_id,
                source_url=album.cover_url,
                force=force,
            )
        )

    except ArtworkNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except ArtworkDownloadError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    except ArtworkStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    # Store the resolved Cover Art Archive URL
    # if the album doesn't already have one.
    if not album.cover_url:
        album.cover_url = artwork.source_url

        await db.commit()

    return {
        "album_id": album.id,
        "album_mbid": album.musicbrainz_id,
        "title": album.title,
        "source_url": artwork.source_url,
        "file_name": artwork.file_path.name,
        "media_type": artwork.media_type,
        "file_size": artwork.file_size,
        "cached": True,
        "url": (
            f"/api/v1/artwork/"
            f"album/{album.id}/file"
        ),
    }


# ==========================================================
# SERVE LOCAL ARTWORK
# ==========================================================


@router.get(
    "/album/{album_id}/file",
    summary="Serve Album Artwork",
)
async def serve_album_artwork(
    album_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Serve locally cached album artwork.

    If artwork isn't cached yet, it will be downloaded first.
    """

    album_result = await db.execute(
        select(Album).where(
            Album.id == album_id
        )
    )

    album = album_result.scalar_one_or_none()

    if album is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found.",
        )

    if not album.musicbrainz_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "Album does not have a "
                "MusicBrainz release ID."
            ),
        )

    existing = artwork_service.get_existing_artwork(
        album.musicbrainz_id
    )

    if existing is None:
        try:
            artwork = (
                await artwork_service.download_artwork(
                    album_mbid=album.musicbrainz_id,
                    source_url=album.cover_url,
                )
            )

            if not album.cover_url:
                album.cover_url = artwork.source_url
                await db.commit()

            existing = artwork.file_path

        except ArtworkNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

        except ArtworkDownloadError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc

        except ArtworkStorageError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc

    media_type = artwork_service._media_type_from_path(
        existing
    )

    return FileResponse(
        path=existing,
        media_type=media_type,
        filename=existing.name,
        headers={
            "Cache-Control": "public, max-age=86400",
        },
    )


# ==========================================================
# ARTWORK STATUS
# ==========================================================


@router.get(
    "/album/{album_id}/status",
    summary="Get Album Artwork Status",
)
async def get_album_artwork_status(
    album_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Check whether album artwork exists locally.
    """

    album_result = await db.execute(
        select(Album).where(
            Album.id == album_id
        )
    )

    album = album_result.scalar_one_or_none()

    if album is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found.",
        )

    if not album.musicbrainz_id:
        return {
            "album_id": album.id,
            "album_mbid": None,
            "has_artwork": False,
            "source_url": album.cover_url,
            "file_url": None,
        }

    existing = artwork_service.get_existing_artwork(
        album.musicbrainz_id
    )

    return {
        "album_id": album.id,
        "album_mbid": album.musicbrainz_id,
        "has_artwork": existing is not None,
        "source_url": album.cover_url,
        "file_url": (
            f"/api/v1/artwork/"
            f"album/{album.id}/file"
            if existing
            else None
        ),
        "file_name": (
            existing.name
            if existing
            else None
        ),
        "file_size": (
            existing.stat().st_size
            if existing
            else None
        ),
    }


# ==========================================================
# DELETE CACHED ARTWORK
# ==========================================================


@router.delete(
    "/album/{album_id}",
    summary="Delete Cached Album Artwork",
)
async def delete_album_artwork(
    album_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete locally cached artwork.

    This does not delete the Cover Art Archive artwork
    or the album's cover_url from PostgreSQL.
    """

    album_result = await db.execute(
        select(Album).where(
            Album.id == album_id
        )
    )

    album = album_result.scalar_one_or_none()

    if album is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Album not found.",
        )

    if not album.musicbrainz_id:
        return {
            "message": "Album has no MusicBrainz ID.",
            "deleted": False,
        }

    try:
        deleted = artwork_service.delete_artwork(
            album.musicbrainz_id
        )

    except ArtworkStorageError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    return {
        "message": (
            "Cached artwork deleted."
            if deleted
            else "No cached artwork found."
        ),
        "album_id": album.id,
        "deleted": deleted,
    }