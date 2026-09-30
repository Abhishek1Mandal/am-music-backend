from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.download import Download
from app.models.user import User
from app.schemas.download import (
    DownloadCreate,
    DownloadResponse,
)
from app.services.music.downloader import (
    InvalidDownloadURL,
    process_download,
    validate_download_url,
)


router = APIRouter(
    prefix="/downloads",
    tags=["Downloads"],
)


# ============================================================
# POST /downloads
# ============================================================


@router.post(
    "",
    response_model=DownloadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_download(
    payload: DownloadCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Create a new music download.

    The actual yt-dlp/FFmpeg operation runs in the background.
    """

    # --------------------------------------------------------
    # Validate URL before creating the DB record.
    # --------------------------------------------------------

    try:
        source_url = validate_download_url(
            payload.url
        )
    except InvalidDownloadURL as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    # --------------------------------------------------------
    # Create download record.
    # --------------------------------------------------------

    download = Download(
        user_id=current_user.id,
        source_url=source_url,
        status="pending",
    )

    db.add(download)

    await db.commit()
    await db.refresh(download)

    # --------------------------------------------------------
    # Schedule background processing.
    # --------------------------------------------------------

    background_tasks.add_task(
        process_download,
        download.id,
    )

    return download


# ============================================================
# GET /downloads
# ============================================================


@router.get(
    "",
    response_model=list[DownloadResponse],
)
async def get_downloads(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get downloads belonging to the current user.
    """

    result = await db.execute(
        select(Download)
        .where(
            Download.user_id == current_user.id
        )
        .order_by(
            Download.created_at.desc()
        )
    )

    return list(result.scalars().all())


# ============================================================
# GET /downloads/{download_id}
# ============================================================


@router.get(
    "/{download_id}",
    response_model=DownloadResponse,
)
async def get_download(
    download_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Get one download belonging to the current user.
    """

    result = await db.execute(
        select(Download)
        .where(
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

    return download


# ============================================================
# DELETE /downloads/{download_id}
# ============================================================


@router.delete(
    "/{download_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_download(
    download_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Delete a download record and its downloaded file.

    The database record is only deleted if it belongs to the
    authenticated user.
    """

    result = await db.execute(
        select(Download)
        .where(
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

    # --------------------------------------------------------
    # Delete the physical file if it exists.
    # --------------------------------------------------------

    if download.file_path:
        try:
            from pathlib import Path

            file_path = Path(
                download.file_path
            )

            if file_path.exists() and file_path.is_file():
                file_path.unlink()

        except OSError:
            # Do not fail the DB deletion because a physical
            # file could not be removed.
            pass

    # --------------------------------------------------------
    # Delete database record.
    # --------------------------------------------------------

    await db.execute(
        delete(Download).where(
            Download.id == download.id
        )
    )

    await db.commit()

    return None