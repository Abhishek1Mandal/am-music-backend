import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.download import Download
from app.models.user import User
from app.schemas.download import DownloadResponse

router = APIRouter(prefix="/downloads", tags=["Downloads"])

@router.get("/{download_id}/progress", response_model=DownloadResponse)
async def get_download_progress(download_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    result = await db.execute(select(Download).where(Download.id == download_id, Download.user_id == current_user.id))
    download = result.scalar_one_or_none()
    if download is None:
        raise HTTPException(status_code=404, detail="Download not found.")
    return download
