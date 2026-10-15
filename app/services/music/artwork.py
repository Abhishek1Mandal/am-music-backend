from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import settings


class ArtworkError(Exception):
    """Base exception for artwork operations."""


class ArtworkNotFoundError(ArtworkError):
    """Raised when artwork cannot be found."""


class ArtworkDownloadError(ArtworkError):
    """Raised when artwork cannot be downloaded."""


class ArtworkStorageError(ArtworkError):
    """Raised when artwork cannot be stored safely."""


@dataclass(slots=True)
class StoredArtwork:
    album_mbid: str
    file_path: Path
    media_type: str
    file_size: int
    source_url: str


class ArtworkService:
    """
    Handles downloading and locally caching album artwork.

    Storage:

        MUSIC_LIBRARY_PATH/
            artwork/
                {album_mbid}.jpg
    """

    MAX_ARTWORK_SIZE = 15 * 1024 * 1024

    ALLOWED_MEDIA_TYPES = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    def __init__(self) -> None:
        self.library_path = Path(settings.music_library_path).resolve()
        self.artwork_path = (self.library_path / "artwork").resolve()

        self.artwork_path.mkdir(
            parents=True,
            exist_ok=True,
        )

    # ==========================================================
    # PATH HELPERS
    # ==========================================================

    def _validate_mbid(self, album_mbid: str) -> str:
        """
        Validate the MusicBrainz ID used as a filename.

        UUID-like MBIDs are expected. We intentionally do not
        accept path separators or arbitrary filenames.
        """

        album_mbid = album_mbid.strip()

        if not album_mbid:
            raise ArtworkStorageError(
                "Album MusicBrainz ID is required."
            )

        if len(album_mbid) > 100:
            raise ArtworkStorageError(
                "Invalid album MusicBrainz ID."
            )

        if "/" in album_mbid or "\\" in album_mbid:
            raise ArtworkStorageError(
                "Invalid album MusicBrainz ID."
            )

        if ".." in album_mbid:
            raise ArtworkStorageError(
                "Invalid album MusicBrainz ID."
            )

        return album_mbid

    def _build_path(
        self,
        album_mbid: str,
        extension: str,
    ) -> Path:
        album_mbid = self._validate_mbid(album_mbid)

        filename = f"{album_mbid}{extension}"

        target = (self.artwork_path / filename).resolve()

        try:
            target.relative_to(self.artwork_path)
        except ValueError as exc:
            raise ArtworkStorageError(
                "Invalid artwork path."
            ) from exc

        return target

    # ==========================================================
    # EXISTING FILE
    # ==========================================================

    def get_existing_artwork(
        self,
        album_mbid: str,
    ) -> Path | None:
        """
        Return an existing cached artwork file.
        """

        album_mbid = self._validate_mbid(album_mbid)

        for extension in self.ALLOWED_MEDIA_TYPES.values():
            path = self._build_path(
                album_mbid,
                extension,
            )

            if path.is_file() and path.stat().st_size > 0:
                return path

        return None

    # ==========================================================
    # SOURCE URL
    # ==========================================================

    def build_cover_art_archive_url(
        self,
        album_mbid: str,
    ) -> str:
        """
        Build the default Cover Art Archive front-cover URL.
        """

        album_mbid = self._validate_mbid(album_mbid)

        base_url = settings.cover_art_base_url.rstrip("/")

        return (
            f"{base_url}/release/"
            f"{album_mbid}/front-1200"
        )

    def resolve_source_url(
        self,
        album_mbid: str,
        cover_url: str | None = None,
    ) -> str:
        """
        Prefer the existing database cover URL.

        If no URL exists, use Cover Art Archive directly.
        """

        album_mbid = self._validate_mbid(album_mbid)

        if cover_url:
            parsed = urlparse(cover_url)

            if parsed.scheme in {"http", "https"}:
                return cover_url

        return self.build_cover_art_archive_url(
            album_mbid
        )

    # ==========================================================
    # MEDIA TYPE
    # ==========================================================

    def _detect_media_type(
        self,
        content_type: str | None,
        content: bytes,
    ) -> str:
        """
        Detect supported image type.

        We use both the HTTP content type and file signature.
        """

        normalized = ""

        if content_type:
            normalized = (
                content_type
                .split(";")[0]
                .strip()
                .lower()
            )

        if normalized in self.ALLOWED_MEDIA_TYPES:
            return normalized

        # JPEG
        if content.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"

        # PNG
        if content.startswith(
            b"\x89PNG\r\n\x1a\n"
        ):
            return "image/png"

        # WEBP
        if (
            len(content) >= 12
            and content[0:4] == b"RIFF"
            and content[8:12] == b"WEBP"
        ):
            return "image/webp"

        raise ArtworkDownloadError(
            "Unsupported artwork image format."
        )

    # ==========================================================
    # DOWNLOAD
    # ==========================================================

    async def download_artwork(
        self,
        album_mbid: str,
        source_url: str | None = None,
        force: bool = False,
    ) -> StoredArtwork:
        """
        Download artwork and store it locally.

        Existing cached artwork is reused unless force=True.
        """

        album_mbid = self._validate_mbid(
            album_mbid
        )

        if not force:
            existing = self.get_existing_artwork(
                album_mbid
            )

            if existing is not None:
                media_type = self._media_type_from_path(
                    existing
                )

                return StoredArtwork(
                    album_mbid=album_mbid,
                    file_path=existing,
                    media_type=media_type,
                    file_size=existing.stat().st_size,
                    source_url=source_url
                    or self.resolve_source_url(
                        album_mbid
                    ),
                )

        url = self.resolve_source_url(
            album_mbid,
            source_url,
        )

        headers = {
            "User-Agent": settings.musicbrainz_user_agent,
            "Accept": "image/jpeg,image/png,image/webp,image/*",
        }

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=10.0,
                    read=30.0,
                    write=30.0,
                    pool=10.0,
                ),
                follow_redirects=True,
                headers=headers,
            ) as client:

                response = await client.get(url)

                response.raise_for_status()

                content = response.content

        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404:
                raise ArtworkNotFoundError(
                    "Album artwork was not found."
                ) from exc

            raise ArtworkDownloadError(
                f"Artwork server returned HTTP "
                f"{exc.response.status_code}."
            ) from exc

        except httpx.HTTPError as exc:
            raise ArtworkDownloadError(
                f"Failed to download artwork: {exc}"
            ) from exc

        if not content:
            raise ArtworkDownloadError(
                "Artwork response was empty."
            )

        if len(content) > self.MAX_ARTWORK_SIZE:
            raise ArtworkDownloadError(
                "Artwork file is too large."
            )

        media_type = self._detect_media_type(
            response.headers.get("content-type"),
            content,
        )

        extension = self.ALLOWED_MEDIA_TYPES[
            media_type
        ]

        target = self._build_path(
            album_mbid,
            extension,
        )

        temp_path = target.with_suffix(
            target.suffix + ".tmp"
        )

        try:
            temp_path.write_bytes(content)

            temp_path.replace(target)

        except OSError as exc:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

            raise ArtworkStorageError(
                f"Failed to store artwork: {exc}"
            ) from exc

        return StoredArtwork(
            album_mbid=album_mbid,
            file_path=target,
            media_type=media_type,
            file_size=len(content),
            source_url=url,
        )

    # ==========================================================
    # MEDIA TYPE FROM FILE
    # ==========================================================

    def _media_type_from_path(
        self,
        path: Path,
    ) -> str:
        suffix = path.suffix.lower()

        if suffix == ".jpg":
            return "image/jpeg"

        if suffix == ".png":
            return "image/png"

        if suffix == ".webp":
            return "image/webp"

        guessed, _ = mimetypes.guess_type(
            str(path)
        )

        if guessed in self.ALLOWED_MEDIA_TYPES:
            return guessed

        return "application/octet-stream"

    # ==========================================================
    # DELETE
    # ==========================================================

    def delete_artwork(
        self,
        album_mbid: str,
    ) -> bool:
        """
        Delete all cached artwork variants for an album.
        """

        album_mbid = self._validate_mbid(
            album_mbid
        )

        deleted = False

        for extension in self.ALLOWED_MEDIA_TYPES.values():
            path = self._build_path(
                album_mbid,
                extension,
            )

            if path.exists():
                try:
                    path.unlink()
                    deleted = True
                except OSError as exc:
                    raise ArtworkStorageError(
                        f"Failed to delete artwork: {exc}"
                    ) from exc

        return deleted


artwork_service = ArtworkService()