from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.playlist import Playlist, playlist_tracks
from app.models.track import Track
from app.models.user import User
from app.schemas.playlist import PlaylistCreate, PlaylistResponse


router = APIRouter(
    prefix="/playlists",
    tags=["Playlists"],
)


@router.post(
    "",
    response_model=PlaylistResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Playlist",
)
async def create_playlist(
    payload: PlaylistCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    playlist = Playlist(
        user_id=current_user.id,
        name=payload.name,
        description=payload.description,
        is_public=payload.is_public,
    )

    db.add(playlist)

    await db.commit()
    await db.refresh(playlist)

    return playlist


@router.get(
    "",
    response_model=list[PlaylistResponse],
    summary="Get User Playlists",
)
async def list_playlists(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Playlist)
        .where(
            Playlist.user_id == current_user.id,
        )
        .order_by(
            Playlist.created_at.desc(),
        )
    )

    return result.scalars().all()


@router.get(
    "/{playlist_id}",
    response_model=PlaylistResponse,
    summary="Get Playlist",
)
async def get_playlist(
    playlist_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Playlist).where(
            Playlist.id == playlist_id,
            Playlist.user_id == current_user.id,
        )
    )

    playlist = result.scalar_one_or_none()

    if playlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found.",
        )

    return playlist


@router.put(
    "/{playlist_id}",
    response_model=PlaylistResponse,
    summary="Update Playlist",
)
async def update_playlist(
    playlist_id: UUID,
    payload: PlaylistCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Playlist).where(
            Playlist.id == playlist_id,
            Playlist.user_id == current_user.id,
        )
    )

    playlist = result.scalar_one_or_none()

    if playlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found.",
        )

    playlist.name = payload.name
    playlist.description = payload.description
    playlist.is_public = payload.is_public

    await db.commit()
    await db.refresh(playlist)

    return playlist


@router.delete(
    "/{playlist_id}",
    summary="Delete Playlist",
)
async def delete_playlist(
    playlist_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Playlist).where(
            Playlist.id == playlist_id,
            Playlist.user_id == current_user.id,
        )
    )

    playlist = result.scalar_one_or_none()

    if playlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found.",
        )

    await db.delete(playlist)
    await db.commit()

    return {
        "message": "Playlist deleted.",
        "playlist_id": playlist_id,
    }


@router.get(
    "/{playlist_id}/tracks",
    summary="Get Playlist Tracks",
)
async def get_playlist_tracks(
    playlist_id: UUID,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify playlist ownership.
    playlist_result = await db.execute(
        select(Playlist).where(
            Playlist.id == playlist_id,
            Playlist.user_id == current_user.id,
        )
    )

    playlist = playlist_result.scalar_one_or_none()

    if playlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found.",
        )

    result = await db.execute(
        select(
            playlist_tracks.c.playlist_id,
            playlist_tracks.c.track_id,
            playlist_tracks.c.position,
            Track,
        )
        .join(
            Track,
            Track.id == playlist_tracks.c.track_id,
        )
        .where(
            playlist_tracks.c.playlist_id == playlist_id,
        )
        .order_by(
            playlist_tracks.c.position.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    rows = result.all()

    items = []

    for playlist_id_value, track_id, position, track in rows:
        items.append(
            {
                "playlist_id": playlist_id_value,
                "track_id": track_id,
                "title": track.title,
                "artist_id": track.artist_id,
                "album_id": track.album_id,
                "duration_ms": track.duration_ms,
                "musicbrainz_id": track.musicbrainz_id,
                "is_available": track.is_available,
                "position": position,
            }
        )

    return {
        "playlist_id": playlist_id,
        "items": items,
        "count": len(items),
        "limit": limit,
        "offset": offset,
    }


@router.post(
    "/{playlist_id}/tracks/{track_id}",
    status_code=status.HTTP_201_CREATED,
    summary="Add Track To Playlist",
)
async def add_track_to_playlist(
    playlist_id: UUID,
    track_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify playlist ownership.
    playlist_result = await db.execute(
        select(Playlist).where(
            Playlist.id == playlist_id,
            Playlist.user_id == current_user.id,
        )
    )

    playlist = playlist_result.scalar_one_or_none()

    if playlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found.",
        )

    # Verify track exists.
    track_result = await db.execute(
        select(Track).where(
            Track.id == track_id,
        )
    )

    track = track_result.scalar_one_or_none()

    if track is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track not found.",
        )

    # Check whether the track is already in the playlist.
    existing_result = await db.execute(
        select(playlist_tracks).where(
            playlist_tracks.c.playlist_id == playlist_id,
            playlist_tracks.c.track_id == track_id,
        )
    )

    existing = existing_result.first()

    if existing is not None:
        return {
            "message": "Track is already in playlist.",
            "playlist_id": playlist_id,
            "track_id": track_id,
            "position": existing.position,
        }

    # Find the next position.
    position_result = await db.execute(
        select(playlist_tracks.c.position)
        .where(
            playlist_tracks.c.playlist_id == playlist_id,
        )
        .order_by(
            playlist_tracks.c.position.desc(),
        )
        .limit(1)
    )

    last_position = position_result.scalar_one_or_none()

    next_position = 0 if last_position is None else last_position + 1

    await db.execute(
        insert(playlist_tracks).values(
            playlist_id=playlist_id,
            track_id=track_id,
            position=next_position,
        )
    )

    await db.commit()

    return {
        "message": "Track added to playlist.",
        "playlist_id": playlist_id,
        "track_id": track_id,
        "position": next_position,
    }


@router.delete(
    "/{playlist_id}/tracks/{track_id}",
    summary="Remove Track From Playlist",
)
async def remove_track_from_playlist(
    playlist_id: UUID,
    track_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify playlist ownership.
    playlist_result = await db.execute(
        select(Playlist).where(
            Playlist.id == playlist_id,
            Playlist.user_id == current_user.id,
        )
    )

    playlist = playlist_result.scalar_one_or_none()

    if playlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found.",
        )

    result = await db.execute(
        select(playlist_tracks).where(
            playlist_tracks.c.playlist_id == playlist_id,
            playlist_tracks.c.track_id == track_id,
        )
    )

    existing = result.first()

    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Track is not in playlist.",
        )

    await db.execute(
        delete(playlist_tracks).where(
            playlist_tracks.c.playlist_id == playlist_id,
            playlist_tracks.c.track_id == track_id,
        )
    )

    await db.commit()

    return {
        "message": "Track removed from playlist.",
        "playlist_id": playlist_id,
        "track_id": track_id,
    }


@router.delete(
    "/{playlist_id}/tracks",
    summary="Clear Playlist Tracks",
)
async def clear_playlist_tracks(
    playlist_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify playlist ownership.
    playlist_result = await db.execute(
        select(Playlist).where(
            Playlist.id == playlist_id,
            Playlist.user_id == current_user.id,
        )
    )

    playlist = playlist_result.scalar_one_or_none()

    if playlist is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Playlist not found.",
        )

    result = await db.execute(
        delete(playlist_tracks).where(
            playlist_tracks.c.playlist_id == playlist_id,
        )
    )

    await db.commit()

    return {
        "message": "Playlist tracks cleared.",
        "playlist_id": playlist_id,
        "deleted_count": result.rowcount,
    }