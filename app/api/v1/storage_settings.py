from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.config import settings
from app.dependencies.auth import get_current_user
from app.models.user import User

router = APIRouter(prefix="/settings/storage", tags=["Storage Settings"])


class StoragePathUpdate(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


def _resolved_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        # Relative paths are interpreted relative to the backend project root.
        path = Path(__file__).resolve().parents[3] / path
    return path.resolve()


@router.get("")
async def get_storage_settings(current_user: User = Depends(get_current_user)):
    path = _resolved_path(settings.music_library_path)
    return {
        "path": str(path),
        "exists": path.exists(),
        "writable": path.exists() and path.is_dir(),
        "storage_type": "backend_filesystem",
        "note": "This is a folder on the machine running the AM Music backend, not on the browser computer.",
    }


@router.put("")
async def update_storage_settings(
    payload: StoragePathUpdate,
    current_user: User = Depends(get_current_user),
):
    """Change the library directory for this running backend process."""
    raw = payload.path.strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Storage path is required.")

    try:
        target = _resolved_path(raw)
        target.mkdir(parents=True, exist_ok=True)
        if not target.is_dir():
            raise ValueError("The selected path is not a directory.")
        probe = target / ".am_music_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot use this storage path: {exc}",
        ) from exc

    # Download and stream services read this runtime setting or keep a cached root.
    settings.music_library_path = str(target)
    try:
        from app.api.v1 import streaming
        streaming.streaming_service.library_root = target
    except Exception:
        pass
    try:
        from app.services.music.artwork import artwork_service
        artwork_service.library_path = target
        artwork_service.artwork_path = target / "artwork"
        artwork_service.artwork_path.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    return {
        "path": str(target),
        "exists": True,
        "writable": True,
        "storage_type": "backend_filesystem",
        "note": "Path updated for the running backend process. Set MUSIC_LIBRARY_PATH in the backend environment for a persistent configuration across restarts/deployments.",
    }
