from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db

router = APIRouter(tags=["Health"])


@router.get("/health")
async def health(
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        text(
            "SELECT current_database(), current_user"
        )
    )

    database, user = result.one()

    return {
        "status": "healthy",
        "database": database,
        "user": user,
    }