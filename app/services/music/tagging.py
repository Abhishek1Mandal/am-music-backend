from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
from mutagen.id3 import APIC, COMM, ID3, ID3NoHeaderError, TALB, TDRC, TIT2, TPE1, TPOS, TRCK, TXXX
from mutagen.mp3 import MP3

from app.core.config import settings

class TaggingError(RuntimeError):
    pass

async def _download_artwork(url: str) -> tuple[bytes, str] | None:
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "image/jpeg").lower()
            mime = "image/png" if "png" in content_type else "image/webp" if "webp" in content_type else "image/jpeg"
            if len(response.content) > 15 * 1024 * 1024:
                raise TaggingError("Album artwork exceeds the 15 MB limit.")
            return response.content, mime
    except httpx.HTTPError:
        return None

def _set_text(tag: ID3, frame_type: Any, value: str | None) -> None:
    if value:
        tag.delall(frame_type.__name__)
        tag.add(frame_type(encoding=3, text=[str(value)]))

def _tag_sync(file_path: str, metadata: dict[str, Any], artwork: tuple[bytes, str] | None) -> dict[str, Any]:
    path = Path(file_path)
    if not path.is_file():
        raise TaggingError(f"Audio file does not exist: {path}")
    try:
        audio = MP3(str(path))
    except Exception as exc:
        raise TaggingError(f"Unable to open MP3 file: {exc}") from exc
    try:
        tag = ID3(str(path))
    except ID3NoHeaderError:
        tag = ID3()

    _set_text(tag, TIT2, metadata.get("title"))
    _set_text(tag, TPE1, metadata.get("artist"))
    _set_text(tag, TALB, metadata.get("album"))
    _set_text(tag, TRCK, metadata.get("track_number"))
    _set_text(tag, TPOS, metadata.get("disc_number"))
    _set_text(tag, TDRC, metadata.get("release_date"))

    mbid = metadata.get("musicbrainz_id")
    if mbid:
        tag.delall("TXXX:MusicBrainz Recording Id")
        tag.add(TXXX(encoding=3, desc="MusicBrainz Recording Id", text=[str(mbid)]))

    if metadata.get("album_artist"):
        tag.delall("TPE2")
        from mutagen.id3 import TPE2
        tag.add(TPE2(encoding=3, text=[str(metadata["album_artist"])]))

    if metadata.get("comment"):
        tag.delall("COMM")
        tag.add(COMM(encoding=3, lang="eng", desc="", text=[str(metadata["comment"])]))

    if artwork:
        image_bytes, mime = artwork
        tag.delall("APIC")
        tag.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=image_bytes))

    tag.save(str(path), v2_version=3)
    return {"file_path": str(path), "tagged": True, "artwork_embedded": artwork is not None}

async def tag_audio_file(file_path: str, *, title: str, artist: str | None = None, album: str | None = None, track_number: int | str | None = None, disc_number: int | str | None = None, release_date: str | None = None, musicbrainz_id: str | None = None, album_artist: str | None = None, artwork_url: str | None = None) -> dict[str, Any]:
    artwork = await _download_artwork(artwork_url) if artwork_url else None
    metadata = {"title": title, "artist": artist, "album": album, "track_number": track_number, "disc_number": disc_number, "release_date": release_date, "musicbrainz_id": musicbrainz_id, "album_artist": album_artist}
    return await asyncio.to_thread(_tag_sync, file_path, metadata, artwork)

def read_audio_tags(file_path: str) -> dict[str, Any]:
    audio = MP3(file_path, ID3=ID3)
    tag = audio.tags
    if tag is None:
        return {}
    def first(key: str):
        value = tag.get(key)
        if value is None:
            return None
        return value.text[0] if hasattr(value, "text") and value.text else str(value)
    return {"title": first("TIT2"), "artist": first("TPE1"), "album": first("TALB"), "track_number": first("TRCK"), "disc_number": first("TPOS"), "release_date": first("TDRC"), "musicbrainz_id": first("TXXX:MusicBrainz Recording Id"), "has_artwork": bool(tag.getall("APIC"))}
