from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.album import Album
from app.models.artist import Artist
from app.models.library import LibraryItem
from app.models.track import Track


def parse_date(value: str | None) -> date | None:
    if not value:
        return None

    try:
        if len(value) == 4:
            return date(int(value), 1, 1)

        if len(value) == 7:
            year, month = value.split("-")
            return date(int(year), int(month), 1)

        return date.fromisoformat(value)

    except (TypeError, ValueError):
        return None


async def get_track_by_musicbrainz_id(
    db: AsyncSession,
    musicbrainz_id: str,
) -> Track | None:
    result = await db.execute(
        select(Track).where(
            Track.musicbrainz_id == musicbrainz_id
        )
    )

    return result.scalar_one_or_none()


async def get_user_library_track(
    db: AsyncSession,
    user_id: UUID,
    musicbrainz_id: str,
) -> Track | None:
    result = await db.execute(
        select(Track)
        .join(
            LibraryItem,
            LibraryItem.track_id == Track.id,
        )
        .where(
            LibraryItem.user_id == user_id,
            Track.musicbrainz_id == musicbrainz_id,
            Track.is_available.is_(True),
        )
    )

    return result.scalar_one_or_none()


async def get_user_downloaded_track_ids(
    db: AsyncSession,
    user_id: UUID,
    musicbrainz_ids: list[str],
) -> set[str]:
    if not musicbrainz_ids:
        return set()

    result = await db.execute(
        select(Track.musicbrainz_id)
        .join(
            LibraryItem,
            LibraryItem.track_id == Track.id,
        )
        .where(
            LibraryItem.user_id == user_id,
            Track.musicbrainz_id.in_(musicbrainz_ids),
            Track.is_available.is_(True),
        )
    )

    return {
        value
        for value in result.scalars().all()
        if value
    }


async def find_or_create_artist(
    db: AsyncSession,
    *,
    name: str,
    musicbrainz_id: str | None = None,
) -> Artist:
    artist = None

    if musicbrainz_id:
        result = await db.execute(
            select(Artist).where(
                Artist.musicbrainz_id == musicbrainz_id
            )
        )
        artist = result.scalar_one_or_none()

    if artist is None:
        result = await db.execute(
            select(Artist).where(
                Artist.name == name
            )
        )
        artist = result.scalar_one_or_none()

    if artist is None:
        artist = Artist(
            name=name,
            sort_name=name,
            musicbrainz_id=musicbrainz_id,
        )
        db.add(artist)
        await db.flush()

    else:
        if musicbrainz_id and not artist.musicbrainz_id:
            artist.musicbrainz_id = musicbrainz_id

    return artist


async def find_or_create_album(
    db: AsyncSession,
    *,
    artist_id: UUID,
    title: str,
    musicbrainz_id: str | None = None,
    release_date: str | None = None,
) -> Album:
    album = None

    if musicbrainz_id:
        result = await db.execute(
            select(Album).where(
                Album.musicbrainz_id == musicbrainz_id
            )
        )
        album = result.scalar_one_or_none()

    if album is None:
        result = await db.execute(
            select(Album).where(
                Album.artist_id == artist_id,
                Album.title == title,
            )
        )
        album = result.scalar_one_or_none()

    if album is None:
        album = Album(
            artist_id=artist_id,
            title=title,
            release_date=parse_date(release_date),
            release_type="album",
            musicbrainz_id=musicbrainz_id,
        )
        db.add(album)
        await db.flush()

    else:
        if musicbrainz_id and not album.musicbrainz_id:
            album.musicbrainz_id = musicbrainz_id

        if release_date and not album.release_date:
            album.release_date = parse_date(release_date)

    return album


async def create_or_update_track(
    db: AsyncSession,
    *,
    musicbrainz_id: str,
    title: str,
    artist_id: UUID,
    album_id: UUID | None,
    duration_ms: int | None,
    file_path: str,
    file_size: int | None,
    mime_type: str = "audio/mpeg",
) -> Track:
    track = await get_track_by_musicbrainz_id(
        db,
        musicbrainz_id,
    )

    if track is None:
        track = Track(
            artist_id=artist_id,
            album_id=album_id,
            title=title,
            duration_ms=duration_ms,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
            musicbrainz_id=musicbrainz_id,
            is_available=True,
        )
        db.add(track)

    else:
        track.artist_id = artist_id
        track.album_id = album_id
        track.title = title
        track.duration_ms = duration_ms
        track.file_path = file_path
        track.file_size = file_size
        track.mime_type = mime_type
        track.is_available = True

    await db.flush()
    return track


async def add_track_to_library(
    db: AsyncSession,
    *,
    user_id: UUID,
    track_id: UUID,
) -> LibraryItem:
    result = await db.execute(
        select(LibraryItem).where(
            LibraryItem.user_id == user_id,
            LibraryItem.track_id == track_id,
        )
    )

    existing = result.scalar_one_or_none()

    if existing:
        return existing

    library_item = LibraryItem(
        user_id=user_id,
        track_id=track_id,
    )

    db.add(library_item)
    await db.flush()

    return library_item
