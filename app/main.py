from fastapi import FastAPI
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
)


@app.get("/")
async def root():
    return {
        "message": "OpenMusic API is running",
        "version": settings.app_version,
    }


@app.get("/health")
async def health():
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT current_database(), current_user")
        )

        database, user = result.one()

        return {
            "status": "healthy",
            "database": database,
            "user": user,
        }