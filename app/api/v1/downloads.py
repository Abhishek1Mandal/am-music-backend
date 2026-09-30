from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal, get_db
from app.dependencies.auth import get_current_user
from app.models.album import Album
from app.models.artist import Artist
from app.models.download import Download
from app.models.library import LibraryItem
from app.models.track import Track
from app.models.user import User
from app.schemas.download import DownloadCreate, DownloadResponse
from app.services.metadata.recording import (
    MusicBrainzRecordingError,
    extract_recording_metadata,
    get_recording,
)
from app.services.music.downloader import download_audio
from app.services.music.source_resolver import (
    SourceResolverError,
    resolve_source,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/downloads",
    tags=["Downloads"],
)


# ============================================================
# Constants
# ============================================================

ACTIVE_DOWNLOAD_STATUSES = {
    "pending",
    "resolving",
    "downloading",
    "processing",
}


# ============================================================
# General helpers
# ============================================================


def file_exists(
    file_path: str | None,
) -> bool:
    """
    Check whether the physical music file exists.
    """

    if not file_path:
        return False

    try:
        return Path(file_path).is_file()
    except OSError:
        return False


def delete_file_safely(
    file_path: str | None,
) -> None:
    """
    Delete a physical music file safely.

    Cleanup failure should never hide the original operation.
    """

    if not file_path:
        return

    try:
        path = Path(file_path)

        if path.is_file():
            path.unlink()

            logger.info(
                "[DOWNLOAD] Deleted file: %s",
                path,
            )

    except OSError:
        logger.exception(
            "[DOWNLOAD] Failed to delete file: %s",
            file_path,
        )


def parse_release_date(
    value: str | None,
):
    """
    Convert MusicBrainz release date into a Python date.

    Supported formats:

        YYYY
        YYYY-MM
        YYYY-MM-DD
    """

    if not value:
        return None

    value = value.strip()

    try:
        if len(value) >= 10:
            return datetime.strptime(
                value[:10],
                "%Y-%m-%d",
            ).date()

        if len(value) >= 7:
            return datetime.strptime(
                value[:7],
                "%Y-%m",
            ).date().replace(
                day=1,
            )

        if len(value) >= 4:
            return datetime.strptime(
                value[:4],
                "%Y",
            ).date().replace(
                month=1,
                day=1,
            )

    except ValueError:
        logger.warning(
            "[DOWNLOAD] Invalid release date: %s",
            value,
        )

    return None


# ============================================================
# PostgreSQL advisory lock
# ============================================================


def build_download_lock_key(
    user_id: UUID,
    musicbrainz_id: str,
) -> int:
    """
    Build a deterministic PostgreSQL advisory-lock key.

    The same user + MusicBrainz recording always produces
    the same lock key.

    This protects against multiple simultaneous download
    requests for the same user + track.
    """

    value = f"{user_id}:{musicbrainz_id}"

    digest = hashlib.sha256(
        value.encode("utf-8"),
    ).digest()

    # PostgreSQL bigint is signed 64-bit.
    number = int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=False,
    )

    if number >= 2**63:
        number -= 2**64

    return number


async def acquire_download_lock(
    db: AsyncSession,
    user_id: UUID,
    musicbrainz_id: str,
) -> None:
    """
    Acquire a transaction-scoped PostgreSQL advisory lock.

    The lock is automatically released when the transaction
    commits or rolls back.
    """

    lock_key = build_download_lock_key(
        user_id,
        musicbrainz_id,
    )

    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock(:lock_key)"
        ),
        {
            "lock_key": lock_key,
        },
    )


# ============================================================
# Download queries
# ============================================================


async def get_download_by_id(
    db: AsyncSession,
    download_id: UUID,
) -> Download | None:
    result = await db.execute(
        select(Download).where(
            Download.id == download_id,
        )
    )

    return result.scalar_one_or_none()


async def get_existing_track(
    db: AsyncSession,
    musicbrainz_id: str,
) -> Track | None:
    result = await db.execute(
        select(Track).where(
            Track.musicbrainz_id == musicbrainz_id,
        )
    )

    return result.scalar_one_or_none()


async def get_user_library_item(
    db: AsyncSession,
    user_id: UUID,
    track_id: UUID,
) -> LibraryItem | None:
    result = await db.execute(
        select(LibraryItem).where(
            LibraryItem.user_id == user_id,
            LibraryItem.track_id == track_id,
        )
    )

    return result.scalar_one_or_none()


async def get_active_download(
    db: AsyncSession,
    user_id: UUID,
    musicbrainz_id: str,
) -> Download | None:
    """
    Find an active download for the same user + track.
    """

    result = await db.execute(
        select(Download)
        .where(
            Download.user_id == user_id,
            Download.musicbrainz_id == musicbrainz_id,
            Download.status.in_(
                ACTIVE_DOWNLOAD_STATUSES,
            ),
        )
        .order_by(
            Download.created_at.desc(),
        )
    )

    return result.scalars().first()


async def get_latest_completed_download(
    db: AsyncSession,
    user_id: UUID,
    musicbrainz_id: str,
    track_id: UUID | None = None,
) -> Download | None:
    """
    Get the latest completed download for a user + track.
    """

    query = (
        select(Download)
        .where(
            Download.user_id == user_id,
            Download.musicbrainz_id == musicbrainz_id,
            Download.status == "completed",
        )
        .order_by(
            Download.completed_at.desc(),
        )
    )

    if track_id is not None:
        query = query.where(
            Download.track_id == track_id,
        )

    result = await db.execute(query)

    return result.scalars().first()


async def has_other_download_reference(
    db: AsyncSession,
    track_id: UUID,
    excluding_download_id: UUID | None = None,
) -> bool:
    """
    Check whether another Download record references this Track.
    """

    query = select(Download.id).where(
        Download.track_id == track_id,
        Download.status == "completed",
    )

    if excluding_download_id is not None:
        query = query.where(
            Download.id != excluding_download_id,
        )

    result = await db.execute(
        query.limit(1),
    )

    return result.scalar_one_or_none() is not None


async def has_other_library_reference(
    db: AsyncSession,
    track_id: UUID,
    excluding_user_id: UUID | None = None,
) -> bool:
    """
    Check whether another LibraryItem references this Track.
    """

    query = select(LibraryItem.id).where(
        LibraryItem.track_id == track_id,
    )

    if excluding_user_id is not None:
        query = query.where(
            LibraryItem.user_id != excluding_user_id,
        )

    result = await db.execute(
        query.limit(1),
    )

    return result.scalar_one_or_none() is not None


# ============================================================
# Track availability
# ============================================================


async def sync_track_availability(
    db: AsyncSession,
    track: Track,
) -> bool:
    """
    Synchronize Track.is_available with the physical file.

    If the user manually deletes or moves the file, the old
    file path becomes unavailable.

    We do NOT attempt to automatically find the moved file.
    """

    available = file_exists(
        track.file_path,
    )

    if track.is_available != available:
        logger.info(
            "[DOWNLOAD] Track availability changed: "
            "track=%s available=%s path=%s",
            track.id,
            available,
            track.file_path,
        )

        track.is_available = available

        await db.flush()

    return available


async def build_download_response(
    db: AsyncSession,
    download: Download,
) -> DownloadResponse:
    """
    Build the API response with a dynamically calculated
    is_downloaded value.
    """

    is_downloaded = False

    track: Track | None = None

    if download.track_id:
        result = await db.execute(
            select(Track).where(
                Track.id == download.track_id,
            )
        )

        track = result.scalar_one_or_none()

    if track is not None:
        is_downloaded = await sync_track_availability(
            db,
            track,
        )

    # A completed Download without a Track should never
    # be reported as downloaded.
    if download.status != "completed":
        is_downloaded = False

    # Keep Download.file_path synchronized with Track.file_path.
    if track is not None:
        download.file_path = track.file_path

    return DownloadResponse(
        id=download.id,
        user_id=download.user_id,
        track_id=download.track_id,
        musicbrainz_id=download.musicbrainz_id,
        source_url=download.source_url,
        status=download.status,
        file_path=download.file_path,
        error_message=download.error_message,
        created_at=download.created_at,
        completed_at=download.completed_at,
        is_downloaded=is_downloaded,
    )


# ============================================================
# Artist
# ============================================================


async def find_or_create_artist(
    db: AsyncSession,
    *,
    name: str,
    musicbrainz_id: str | None = None,
    sort_name: str | None = None,
) -> Artist:
    """
    Find an Artist by MusicBrainz MBID first.

    Falls back to artist name.
    """

    artist: Artist | None = None

    if musicbrainz_id:
        result = await db.execute(
            select(Artist).where(
                Artist.musicbrainz_id == musicbrainz_id,
            )
        )

        artist = result.scalar_one_or_none()

    if artist is None:
        result = await db.execute(
            select(Artist).where(
                Artist.name.ilike(name),
            )
        )

        artist = result.scalars().first()

    if artist is None:
        artist = Artist(
            name=name,
            sort_name=sort_name,
            musicbrainz_id=musicbrainz_id,
        )

        db.add(artist)

        await db.flush()

        logger.info(
            "[DOWNLOAD] Created artist: %s",
            name,
        )

    else:
        if musicbrainz_id and not artist.musicbrainz_id:
            artist.musicbrainz_id = musicbrainz_id

        if sort_name and not artist.sort_name:
            artist.sort_name = sort_name

        await db.flush()

    return artist


# ============================================================
# Album
# ============================================================


async def find_or_create_album(
    db: AsyncSession,
    *,
    artist_id: UUID,
    title: str | None,
    release_mbid: str | None,
    release_group_mbid: str | None,
    release_date: str | None,
) -> Album | None:
    """
    Find or create the concrete MusicBrainz release.
    """

    if not title:
        return None

    album: Album | None = None

    lookup_mbid = (
        release_mbid
        or release_group_mbid
    )

    if lookup_mbid:
        result = await db.execute(
            select(Album).where(
                Album.musicbrainz_id == lookup_mbid,
            )
        )

        album = result.scalar_one_or_none()

    if album is None:
        result = await db.execute(
            select(Album).where(
                Album.artist_id == artist_id,
                Album.title.ilike(title),
            )
        )

        album = result.scalars().first()

    if album is None:
        album = Album(
            artist_id=artist_id,
            title=title,
            release_date=parse_release_date(
                release_date,
            ),
            musicbrainz_id=lookup_mbid,
        )

        db.add(album)

        await db.flush()

        logger.info(
            "[DOWNLOAD] Created album: %s",
            title,
        )

    else:
        if release_date and not album.release_date:
            album.release_date = parse_release_date(
                release_date,
            )

        if (
            lookup_mbid
            and not album.musicbrainz_id
        ):
            album.musicbrainz_id = lookup_mbid

        await db.flush()

    return album


# ============================================================
# Track
# ============================================================


async def find_or_create_track(
    db: AsyncSession,
    *,
    musicbrainz_id: str,
    title: str,
    artist_id: UUID,
    album_id: UUID | None,
    duration_ms: int | None,
    file_path: str,
) -> Track:
    """
    Find a Track by MusicBrainz recording MBID
    or create it.
    """

    result = await db.execute(
        select(Track).where(
            Track.musicbrainz_id == musicbrainz_id,
        )
    )

    track = result.scalar_one_or_none()

    file_size: int | None = None

    try:
        file_size = os.path.getsize(
            file_path,
        )
    except OSError:
        pass

    if track is None:
        track = Track(
            artist_id=artist_id,
            album_id=album_id,
            title=title,
            duration_ms=duration_ms,
            file_path=file_path,
            file_size=file_size,
            mime_type="audio/mpeg",
            musicbrainz_id=musicbrainz_id,
            is_available=True,
        )

        db.add(track)

        await db.flush()

        logger.info(
            "[DOWNLOAD] Created track: %s",
            title,
        )

    else:
        track.artist_id = artist_id
        track.album_id = album_id
        track.title = title

        if duration_ms is not None:
            track.duration_ms = duration_ms

        track.file_path = file_path
        track.file_size = file_size
        track.mime_type = "audio/mpeg"
        track.is_available = True

        await db.flush()

        logger.info(
            "[DOWNLOAD] Updated track: %s",
            title,
        )

    return track


# ============================================================
# Library
# ============================================================


async def add_to_library(
    db: AsyncSession,
    *,
    user_id: UUID,
    track_id: UUID,
) -> LibraryItem:
    """
    Add Track to user's library if it isn't already there.
    """

    existing = await get_user_library_item(
        db,
        user_id,
        track_id,
    )

    if existing:
        return existing

    library_item = LibraryItem(
        user_id=user_id,
        track_id=track_id,
    )

    db.add(library_item)

    await db.flush()

    logger.info(
        "[DOWNLOAD] Added track %s to user %s library",
        track_id,
        user_id,
    )

    return library_item


# ============================================================
# Failed download
# ============================================================


async def mark_download_failed(
    download_id: UUID,
    error_message: str,
) -> None:
    """
    Mark a background download as failed.
    """

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Download).where(
                    Download.id == download_id,
                )
            )

            download = result.scalar_one_or_none()

            if download is None:
                logger.error(
                    "[DOWNLOAD] Could not find failed download %s",
                    download_id,
                )
                return

            download.status = "failed"
            download.error_message = error_message
            download.completed_at = None

            await db.commit()

        except Exception:
            await db.rollback()

            logger.exception(
                "[DOWNLOAD] Failed to update download %s as failed",
                download_id,
            )


# ============================================================
# Background download worker
# ============================================================


async def process_download(
    download_id: UUID,
    user_id: UUID,
    musicbrainz_id: str,
) -> None:
    """
    Complete the entire download pipeline.

    Flutter provides ONLY the MusicBrainz recording MBID.

    Backend:

        MusicBrainz
            ↓
        Metadata
            ↓
        YouTube resolver
            ↓
        yt-dlp
            ↓
        Artist
            ↓
        Album
            ↓
        Track
            ↓
        Library
            ↓
        Completed Download
    """

    logger.info(
        "[DOWNLOAD] Started: id=%s mbid=%s user=%s",
        download_id,
        musicbrainz_id,
        user_id,
    )

    async with AsyncSessionLocal() as db:
        try:

            # ==================================================
            # Load Download
            # ==================================================

            download = await get_download_by_id(
                db,
                download_id,
            )

            if download is None:
                logger.error(
                    "[DOWNLOAD] Download %s does not exist",
                    download_id,
                )
                return

            # ==================================================
            # Check existing Track
            # ==================================================

            existing_track = await get_existing_track(
                db,
                musicbrainz_id,
            )

            if existing_track:
                available = await sync_track_availability(
                    db,
                    existing_track,
                )

                if available:
                    logger.info(
                        "[DOWNLOAD] Track already downloaded: %s",
                        musicbrainz_id,
                    )

                    await add_to_library(
                        db,
                        user_id=user_id,
                        track_id=existing_track.id,
                    )

                    download.track_id = existing_track.id
                    download.file_path = existing_track.file_path
                    download.status = "completed"
                    download.error_message = None
                    download.completed_at = datetime.now(
                        timezone.utc,
                    )

                    await db.commit()

                    logger.info(
                        "[DOWNLOAD] Reused existing track: %s",
                        existing_track.id,
                    )

                    return

            # ==================================================
            # Fetch MusicBrainz recording
            # ==================================================

            download.status = "resolving"

            await db.commit()

            logger.info(
                "[DOWNLOAD] Fetching MusicBrainz recording: %s",
                musicbrainz_id,
            )

            recording_data = await get_recording(
                musicbrainz_id,
            )

            metadata = extract_recording_metadata(
                recording_data,
            )

            logger.info(
                "[DOWNLOAD] MusicBrainz metadata: "
                "title=%s artist=%s album=%s duration=%s",
                metadata["title"],
                metadata["artist_name"],
                metadata["album_name"],
                metadata["duration_ms"],
            )

            artist_name = metadata.get(
                "artist_name",
            )

            if not artist_name:
                raise MusicBrainzRecordingError(
                    "MusicBrainz recording has no artist.",
                )

            # ==================================================
            # Resolve YouTube source
            # ==================================================

            logger.info(
                "[DOWNLOAD] Searching YouTube automatically..."
            )

            resolved_source = await resolve_source(
                title=metadata["title"],
                artist=metadata.get(
                    "artist_name",
                ),
                album=metadata.get(
                    "album_name",
                ),
                duration_ms=metadata.get(
                    "duration_ms",
                ),
            )

            logger.info(
                "[DOWNLOAD] YouTube source resolved: "
                "title=%s url=%s score=%.2f",
                resolved_source.title,
                resolved_source.url,
                resolved_source.score,
            )

            download.source_url = (
                resolved_source.url
            )

            download.status = "downloading"

            await db.commit()

            # ==================================================
            # Download audio
            # ==================================================

            logger.info(
                "[DOWNLOAD] Starting audio download..."
            )

            download_result = await asyncio.to_thread(
                download_audio,
                resolved_source.url,
            )

            if not download_result:
                raise RuntimeError(
                    "Downloader did not return a result.",
                )

            file_path = download_result.get(
                "file_path",
            )

            if not file_path:
                raise RuntimeError(
                    "Downloader did not return a file path.",
                )

            if not file_exists(file_path):
                raise RuntimeError(
                    f"Downloaded file does not exist: {file_path}",
                )

            logger.info(
                "[DOWNLOAD] Audio downloaded: %s",
                file_path,
            )

            # ==================================================
            # Processing
            # ==================================================

            download.status = "processing"
            download.file_path = str(file_path)

            await db.commit()

            # ==================================================
            # Artist
            # ==================================================

            artist = await find_or_create_artist(
                db,
                name=artist_name,
                musicbrainz_id=metadata.get(
                    "artist_mbid",
                ),
                sort_name=metadata.get(
                    "artist_sort_name",
                ),
            )

            # ==================================================
            # Album
            # ==================================================

            album = await find_or_create_album(
                db,
                artist_id=artist.id,
                title=metadata.get(
                    "album_name",
                ),
                release_mbid=metadata.get(
                    "release_mbid",
                ),
                release_group_mbid=metadata.get(
                    "release_group_mbid",
                ),
                release_date=metadata.get(
                    "release_date",
                ),
            )

            # ==================================================
            # Track
            # ==================================================

            track = await find_or_create_track(
                db,
                musicbrainz_id=musicbrainz_id,
                title=metadata["title"],
                artist_id=artist.id,
                album_id=(
                    album.id
                    if album
                    else None
                ),
                duration_ms=metadata.get(
                    "duration_ms",
                ),
                file_path=str(file_path),
            )

            # ==================================================
            # Library
            # ==================================================

            await add_to_library(
                db,
                user_id=user_id,
                track_id=track.id,
            )

            # ==================================================
            # Complete
            # ==================================================

            download.track_id = track.id
            download.file_path = str(file_path)
            download.status = "completed"
            download.error_message = None
            download.completed_at = datetime.now(
                timezone.utc,
            )

            await db.commit()

            logger.info(
                "[DOWNLOAD] Completed successfully: "
                "download=%s track=%s file=%s",
                download_id,
                track.id,
                file_path,
            )

        # ======================================================
        # Source resolution failure
        # ======================================================

        except SourceResolverError as exc:
            await db.rollback()

            logger.error(
                "[DOWNLOAD] Source resolution failed: %s",
                exc,
            )

            await mark_download_failed(
                download_id,
                str(exc),
            )

        # ======================================================
        # MusicBrainz failure
        # ======================================================

        except MusicBrainzRecordingError as exc:
            await db.rollback()

            logger.error(
                "[DOWNLOAD] MusicBrainz failed: %s",
                exc,
            )

            await mark_download_failed(
                download_id,
                str(exc),
            )

        # ======================================================
        # General failure
        # ======================================================

        except Exception as exc:
            await db.rollback()

            logger.exception(
                "[DOWNLOAD] Failed: %s",
                exc,
            )

            await mark_download_failed(
                download_id,
                str(exc),
            )


# ============================================================
# CREATE DOWNLOAD
# ============================================================


@router.post(
    "",
    response_model=DownloadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create Download",
    description=(
        "Create a download using only a MusicBrainz recording MBID. "
        "Flutter does NOT need to provide a source URL. "
        "The backend automatically resolves a YouTube source."
    ),
)
async def create_download(
    payload: DownloadCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DownloadResponse:

    musicbrainz_id = payload.musicbrainz_id.strip()

    if not musicbrainz_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "MusicBrainz recording MBID "
                "cannot be empty."
            ),
        )

    # ========================================================
    # Protect against simultaneous clicks
    # ========================================================

    await acquire_download_lock(
        db,
        current_user.id,
        musicbrainz_id,
    )

    # ========================================================
    # Existing Track
    # ========================================================

    existing_track = await get_existing_track(
        db,
        musicbrainz_id,
    )

    if existing_track:

        # Check actual physical file.
        available = await sync_track_availability(
            db,
            existing_track,
        )

        if available:

            # Add to user's library if necessary.
            await add_to_library(
                db,
                user_id=current_user.id,
                track_id=existing_track.id,
            )

            # Find existing completed download.
            existing_download = (
                await get_latest_completed_download(
                    db,
                    current_user.id,
                    musicbrainz_id,
                    existing_track.id,
                )
            )

            if existing_download:

                await db.commit()

                return await build_download_response(
                    db,
                    existing_download,
                )

            # No Download history exists for this user,
            # but the Track itself already exists.
            completed_download = Download(
                user_id=current_user.id,
                track_id=existing_track.id,
                musicbrainz_id=musicbrainz_id,
                source_url=None,
                status="completed",
                file_path=existing_track.file_path,
                error_message=None,
                completed_at=datetime.now(
                    timezone.utc,
                ),
            )

            db.add(completed_download)

            await db.commit()
            await db.refresh(
                completed_download,
            )

            return await build_download_response(
                db,
                completed_download,
            )

    # ========================================================
    # Existing active download
    # ========================================================

    active_download = await get_active_download(
        db,
        current_user.id,
        musicbrainz_id,
    )

    if active_download:

        logger.info(
            "[DOWNLOAD] Reusing active download: %s",
            active_download.id,
        )

        await db.commit()

        return await build_download_response(
            db,
            active_download,
        )

    # ========================================================
    # Create new Download
    # ========================================================

    download = Download(
        user_id=current_user.id,
        track_id=None,
        musicbrainz_id=musicbrainz_id,
        source_url=None,
        status="pending",
        file_path=None,
        error_message=None,
        completed_at=None,
    )

    db.add(download)

    await db.commit()

    await db.refresh(
        download,
    )

    logger.info(
        "[DOWNLOAD] Queued: id=%s mbid=%s user=%s",
        download.id,
        musicbrainz_id,
        current_user.id,
    )

    # ========================================================
    # Start background worker
    # ========================================================

    background_tasks.add_task(
        process_download,
        download.id,
        current_user.id,
        musicbrainz_id,
    )

    return await build_download_response(
        db,
        download,
    )


# ============================================================
# GET DOWNLOADS
# ============================================================


@router.get(
    "",
    response_model=list[DownloadResponse],
    summary="Get Downloads",
)
async def get_downloads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[DownloadResponse]:
    """
    Return downloads belonging to the authenticated user.

    is_downloaded is calculated from the actual physical file.
    """

    result = await db.execute(
        select(Download)
        .where(
            Download.user_id == current_user.id,
        )
        .order_by(
            Download.created_at.desc(),
        )
    )

    downloads = list(
        result.scalars().all()
    )

    responses: list[DownloadResponse] = []

    for download in downloads:

        response = await build_download_response(
            db,
            download,
        )

        responses.append(
            response,
        )

    # Persist availability changes caused by missing files.
    await db.commit()

    return responses


# ============================================================
# GET SINGLE DOWNLOAD
# ============================================================


@router.get(
    "/{download_id}",
    response_model=DownloadResponse,
    summary="Get Download",
)
async def get_download(
    download_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> DownloadResponse:
    """
    Return a single download belonging to the authenticated user.
    """

    result = await db.execute(
        select(Download).where(
            Download.id == download_id,
            Download.user_id == current_user.id,
        )
    )

    download = result.scalar_one_or_none()

    if download is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found.",
        )

    response = await build_download_response(
        db,
        download,
    )

    await db.commit()

    return response


# ============================================================
# DELETE DOWNLOAD
# ============================================================


@router.delete(
    "/{download_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Download",
)
async def delete_download(
    download_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Delete a user's download.

    The physical file is deleted only when:
        - no other completed Download references it
        - no other LibraryItem references the Track
    """

    result = await db.execute(
        select(Download).where(
            Download.id == download_id,
            Download.user_id == current_user.id,
        )
    )

    download = result.scalar_one_or_none()

    if download is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found.",
        )

    track_id = download.track_id
    file_path = download.file_path

    # ========================================================
    # Remove current user's library reference
    # ========================================================

    if track_id:

        library_result = await db.execute(
            select(LibraryItem).where(
                LibraryItem.user_id == current_user.id,
                LibraryItem.track_id == track_id,
            )
        )

        library_item = (
            library_result.scalar_one_or_none()
        )

        if library_item:

            # Only remove the library entry if the user
            # doesn't have another completed download for
            # the same Track.

            other_user_download_result = await db.execute(
                select(Download.id)
                .where(
                    Download.user_id == current_user.id,
                    Download.track_id == track_id,
                    Download.status == "completed",
                    Download.id != download_id,
                )
                .limit(1)
            )

            other_user_download = (
                other_user_download_result.scalar_one_or_none()
            )

            if other_user_download is None:
                await db.delete(
                    library_item,
                )

                await db.flush()

    # ========================================================
    # Check other references
    # ========================================================

    other_download_reference = False

    if track_id:
        other_download_reference = (
            await has_other_download_reference(
                db,
                track_id,
                excluding_download_id=download_id,
            )
        )

    other_library_reference = False

    if track_id:
        other_library_reference = (
            await has_other_library_reference(
                db,
                track_id,
                excluding_user_id=current_user.id,
            )
        )

    # ========================================================
    # Delete physical file only when safe
    # ========================================================

    should_delete_file = (
        not other_download_reference
        and not other_library_reference
    )

    if should_delete_file:
        delete_file_safely(
            file_path,
        )

    # ========================================================
    # Update Track
    # ========================================================

    if track_id:

        track_result = await db.execute(
            select(Track).where(
                Track.id == track_id,
            )
        )

        track = track_result.scalar_one_or_none()

        if track:

            remaining_library_result = await db.execute(
                select(LibraryItem).where(
                    LibraryItem.track_id == track.id,
                )
            )

            remaining_library_item = (
                remaining_library_result.scalars().first()
            )

            remaining_download_result = await db.execute(
                select(Download.id)
                .where(
                    Download.track_id == track.id,
                    Download.id != download_id,
                    Download.status == "completed",
                )
                .limit(1)
            )

            remaining_download = (
                remaining_download_result.scalar_one_or_none()
            )

            if (
                remaining_library_item is None
                and remaining_download is None
            ):
                track.is_available = False

                if should_delete_file:
                    track.file_path = None
                    track.file_size = None

    # ========================================================
    # Delete Download record
    # ========================================================

    await db.delete(
        download,
    )

    await db.commit()

    return None