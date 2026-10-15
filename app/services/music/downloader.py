from __future__ import annotations

import logging
import os
import re
import shutil
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

import yt_dlp

from app.core.config import settings


logger = logging.getLogger(__name__)


# ==========================================================
# EXCEPTIONS
# ==========================================================

class InvalidDownloadURL(Exception):
    """Raised when a source URL is invalid or unsupported."""


class DownloadServiceError(Exception):
    """Raised when a download operation fails."""


# ==========================================================
# SUPPORTED SOURCES
# ==========================================================

ALLOWED_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "music.youtube.com",
}


# ==========================================================
# URL VALIDATION
# ==========================================================

def validate_download_url(url: str) -> str:
    """
    Validate and normalize a supported download URL.
    """

    if not url:
        raise InvalidDownloadURL(
            "Download URL is required."
        )

    url = url.strip()
    parsed = urlparse(url)

    if parsed.scheme not in {"http", "https"}:
        raise InvalidDownloadURL(
            "Only HTTP and HTTPS URLs are supported."
        )

    hostname = (parsed.hostname or "").lower()

    normalized_hostname = hostname.removeprefix("www.")

    allowed_hosts = {
        host.removeprefix("www.")
        for host in ALLOWED_HOSTS
    }

    if normalized_hostname not in allowed_hosts:
        raise InvalidDownloadURL(
            "This source is not supported."
        )

    return url


# ==========================================================
# FILENAME SANITIZATION
# ==========================================================

def sanitize_filename(value: str) -> str:
    """
    Make a string safe for use as a Windows filename/folder name.
    """

    value = str(value or "").strip()

    # Replace characters that are invalid in Windows paths.
    value = re.sub(
        r'[<>:"/\\|?*\x00-\x1F]',
        "_",
        value,
    )

    value = re.sub(
        r"\s+",
        " ",
        value,
    )

    value = value.strip(". ")

    if not value:
        value = "Unknown"

    # Windows filenames should not end in a dot or space.
    return value[:180]


# ==========================================================
# LIBRARY PATHS
# ==========================================================

def _get_library_path() -> Path:
    """
    Return the configured music library path.
    """

    return Path(settings.music_library_path).expanduser()


def _get_temporary_download_path() -> Path:
    """
    Return the temporary download directory.

    yt-dlp downloads into this directory first.
    The file is moved to its final metadata-based
    location after MusicBrainz metadata is resolved.
    """

    library_path = _get_library_path()

    return library_path / ".downloads"


def _build_output_template() -> str:
    """
    Build the temporary yt-dlp output template.

    MusicBrainz metadata is resolved only after yt-dlp
    has downloaded the source. Therefore, downloads are
    initially stored as:

        music/.downloads/<youtube-id>.<extension>
    """

    temporary_path = _get_temporary_download_path()

    return str(
        temporary_path / "%(id)s.%(ext)s"
    )


# ==========================================================
# YT-DLP CONFIGURATION
# ==========================================================

def _get_backend_root() -> Path:
    """
    Return the backend project root.

    Expected structure:

        backend/
        ├── app/
        │   └── services/
        │       └── music/
        │           └── downloader.py
        └── cookies.txt
    """

    return Path(__file__).resolve().parents[3]


def _resolve_cookie_path() -> Path | None:
    """
    Resolve the YouTube cookies file.

    Resolution order:
    1. YOUTUBE_COOKIES_FILE environment variable
    2. settings.youtube_cookies_file
    3. cookies.txt in the backend root

    Relative paths are resolved from the backend root.
    """

    configured_path = (
        os.getenv("YOUTUBE_COOKIES_FILE")
        or getattr(
            settings,
            "youtube_cookies_file",
            None,
        )
    )

    backend_root = _get_backend_root()

    if configured_path:
        cookie_path = Path(
            configured_path
        ).expanduser()

        if not cookie_path.is_absolute():
            cookie_path = backend_root / cookie_path
    else:
        cookie_path = backend_root / "cookies.txt"

    try:
        cookie_path = cookie_path.resolve()
    except OSError:
        logger.warning(
            "Could not resolve the configured YouTube cookie path."
        )
        return None

    if not cookie_path.is_file():
        logger.warning(
            "YouTube cookie file was not found. "
            "Authenticated downloads may fail."
        )
        return None

    return cookie_path


def _resolve_deno_path() -> str | None:
    """
    Resolve the Deno JavaScript runtime executable.
    """

    configured_path = (
        os.getenv("YT_DLP_DENO_PATH")
        or getattr(
            settings,
            "yt_dlp_deno_path",
            None,
        )
    )

    if not configured_path:
        return None

    deno_path = Path(
        configured_path
    ).expanduser()

    try:
        deno_path = deno_path.resolve()
    except OSError:
        logger.warning(
            "Could not resolve the configured Deno executable path."
        )
        return None

    if not deno_path.is_file():
        logger.warning(
            "Configured Deno executable was not found."
        )
        return None

    return str(deno_path)


def _resolve_remote_components() -> list[str]:
    """
    Resolve yt-dlp remote component configuration.

    The default enables the EJS challenge solver component
    from GitHub when required by the installed yt-dlp version.
    """

    configured_components = (
        os.getenv("YT_DLP_REMOTE_COMPONENTS")
        or getattr(
            settings,
            "yt_dlp_remote_components",
            None,
        )
        or "ejs:github"
    )

    if isinstance(configured_components, str):
        components = [
            component.strip()
            for component in configured_components.split(",")
            if component.strip()
        ]
    else:
        components = [
            str(component).strip()
            for component in configured_components
            if str(component).strip()
        ]

    return components


def _build_ytdlp_options(
    output_template: str,
    progress_hook: Callable[
        [dict[str, Any]],
        None,
    ] | None = None,
) -> dict[str, Any]:
    """
    Build yt-dlp options consistently for AM Music downloads.

    Cookies, Deno and remote components are configured here
    so the download worker uses the same runtime settings
    as the command-line diagnostic.
    """

    options: dict[str, Any] = {
        # Prefer audio-only when available.
        # Fall back to a combined format when necessary.
        "format": "bestaudio/best",

        "outtmpl": output_template,

        "noplaylist": True,

        "quiet": True,

        "no_warnings": True,

        "progress_hooks": (
            [progress_hook]
            if progress_hook
            else []
        ),

        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "320",
            }
        ],
    }

    # ------------------------------------------------------
    # Cookies
    # ------------------------------------------------------

    cookie_path = _resolve_cookie_path()

    if cookie_path:
        options["cookiefile"] = str(cookie_path)

        logger.info(
            "yt-dlp cookie file configured."
        )

    # ------------------------------------------------------
    # JavaScript runtime: Deno
    # ------------------------------------------------------

    deno_path = _resolve_deno_path()

    if deno_path:
        options["js_runtimes"] = {
            "deno": {
                "path": deno_path,
            }
        }

        logger.info(
            "yt-dlp Deno runtime configured."
        )

    # ------------------------------------------------------
    # Remote components
    # ------------------------------------------------------

    remote_components = _resolve_remote_components()

    if remote_components:
        options["remote_components"] = remote_components

    return options


# ==========================================================
# METADATA-BASED FINAL PATH
# ==========================================================

def build_metadata_file_path(
    metadata: dict[str, Any],
) -> Path:
    """
    Build the final canonical music-library path.

    Example:

        music/
        └── Artist Name/
            └── Album Name/
                └── Track Name.mp3

    The YouTube uploader is intentionally not used
    here as the artist.
    """

    library_path = _get_library_path()

    artist = sanitize_filename(
        metadata.get("artist_name")
        or "Unknown Artist"
    )

    album = sanitize_filename(
        metadata.get("album_name")
        or "Unknown Album"
    )

    title = sanitize_filename(
        metadata.get("title")
        or "Unknown Title"
    )

    return (
        library_path
        / artist
        / album
        / f"{title}.mp3"
    )


# ==========================================================
# CLEANUP EMPTY DIRECTORIES
# ==========================================================

def _cleanup_empty_parent_directories(
    directory: Path,
    stop_at: Path,
) -> None:
    """
    Remove empty directories left behind by downloading.

    Never removes the music library root itself.
    """

    try:
        directory = directory.resolve()
        stop_at = stop_at.resolve()
    except OSError:
        return

    while (
        directory != stop_at
        and stop_at in directory.parents
    ):
        try:
            if not directory.exists():
                directory = directory.parent
                continue

            if any(directory.iterdir()):
                break

            directory.rmdir()
            directory = directory.parent

        except OSError:
            break


# ==========================================================
# RELOCATE DOWNLOADED FILE
# ==========================================================

def relocate_downloaded_file(
    file_path: str | Path,
    metadata: dict[str, Any],
) -> str:
    """
    Move the downloaded MP3 to its canonical metadata path.

    Also removes empty directories left behind by older
    source-based download layouts.
    """

    source = Path(file_path).resolve()

    if not source.is_file():
        raise DownloadServiceError(
            f"Downloaded file does not exist: {source}"
        )

    library_path = _get_library_path().resolve()

    target = build_metadata_file_path(
        metadata
    ).resolve()

    # Prevent a metadata-derived path from escaping the library.
    if (
        target != library_path
        and library_path not in target.parents
    ):
        raise DownloadServiceError(
            "The destination path is outside the music library."
        )

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if source == target:
        return str(target)

    if target.exists():
        try:
            source.unlink()
        except OSError as exc:
            raise DownloadServiceError(
                "Target file already exists and "
                "the source file could not be removed: "
                f"{target}"
            ) from exc

        _cleanup_empty_parent_directories(
            source.parent,
            library_path,
        )

        return str(target)

    try:
        shutil.move(
            str(source),
            str(target),
        )
    except OSError as exc:
        raise DownloadServiceError(
            "Could not move downloaded file to "
            f"canonical path: {target}"
        ) from exc

    _cleanup_empty_parent_directories(
        source.parent,
        library_path,
    )

    return str(target)


# ==========================================================
# DOWNLOAD AUDIO
# ==========================================================

def download_audio(
    url: str,
    progress_hook: Callable[
        [dict[str, Any]],
        None,
    ] | None = None,
) -> dict[str, Any]:
    """
    Download a supported YouTube source and convert it to MP3.

    The source is initially stored at:

        music/.downloads/<youtube-id>.mp3

    The final Artist/Album/Title path is assigned later,
    after MusicBrainz and YouTube metadata resolution.

    Returns:

        {
            "file_path": "...",
            "metadata": {...}
        }
    """

    source_url = validate_download_url(url)

    library_path = _get_library_path()

    library_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    temporary_path = _get_temporary_download_path()

    temporary_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_template = _build_output_template()

    ydl_options = _build_ytdlp_options(
        output_template=output_template,
        progress_hook=progress_hook,
    )

    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            info = ydl.extract_info(
                source_url,
                download=True,
            )

            if not info:
                raise DownloadServiceError(
                    "yt-dlp returned no metadata."
                )

            requested_downloads = (
                info.get("requested_downloads")
                or []
            )

            filepath: str | None = None

            # --------------------------------------------------
            # Locate downloaded file
            # --------------------------------------------------

            if requested_downloads:
                filepath = (
                    requested_downloads[0].get("filepath")
                )

            if not filepath:
                filepath = ydl.prepare_filename(info)

                original_path = Path(filepath)

                converted_path = original_path.with_suffix(
                    ".mp3"
                )

                if converted_path.exists():
                    filepath = str(converted_path)

            file_path = Path(filepath)

            # --------------------------------------------------
            # Additional MP3 lookup
            # --------------------------------------------------

            if not file_path.exists():
                video_id = info.get("id") or "unknown"

                candidates = list(
                    temporary_path.glob(
                        f"{video_id}*.mp3"
                    )
                )

                if candidates:
                    file_path = max(
                        candidates,
                        key=lambda path: path.stat().st_mtime,
                    )

            # --------------------------------------------------
            # Final validation
            # --------------------------------------------------

            if not file_path.is_file():
                raise DownloadServiceError(
                    "Download completed but the MP3 file "
                    "could not be located."
                )

            # --------------------------------------------------
            # YouTube source metadata
            # --------------------------------------------------

            metadata = {
                "title": info.get("title"),

                # Do not use uploader as the artist here.
                # The metadata resolver determines the final
                # artist using MusicBrainz and YouTube data.
                "artist": info.get("artist"),

                "creator": info.get("creator"),

                "album": info.get("album"),

                "album_artist": info.get("album_artist"),

                "track_number": info.get("track_number"),

                "disc_number": info.get("disc_number"),

                "release_date": info.get("release_date"),

                "duration": info.get("duration"),

                "thumbnail": info.get("thumbnail"),

                # Stored separately as source metadata.
                "uploader": info.get("uploader"),

                "webpage_url": info.get("webpage_url"),
            }

            return {
                "file_path": str(file_path.resolve()),
                "metadata": metadata,
            }

    except DownloadServiceError:
        raise

    except Exception as exc:
        message = str(exc)
        lowered = message.lower()

        # ------------------------------------------------------
        # YouTube bot verification
        # ------------------------------------------------------

        if (
            "sign in to confirm you're not a bot" in lowered
            or "confirm you're not a bot" in lowered
        ):
            raise DownloadServiceError(
                "YouTube rejected the download with bot "
                "verification. Check that the configured cookies "
                "are valid and current, then retry. YouTube may "
                "also require a supported client or proof-of-origin "
                "token."
            ) from exc

        # ------------------------------------------------------
        # Requested format unavailable
        # ------------------------------------------------------

        if (
            "requested format is not available" in lowered
            or "requested format not available" in lowered
        ):
            raise DownloadServiceError(
                "YouTube did not expose a usable format for this "
                "video. Check the available formats, client "
                "configuration, and any required YouTube tokens."
            ) from exc

        # ------------------------------------------------------
        # Cookie file errors
        # ------------------------------------------------------

        if (
            "cookie" in lowered
            and (
                "could not find" in lowered
                or "does not exist" in lowered
                or "unable to open" in lowered
            )
        ):
            raise DownloadServiceError(
                "The configured YouTube cookie file could not "
                "be read. Check YOUTUBE_COOKIES_FILE and ensure "
                "the file exists and is accessible."
            ) from exc

        # ------------------------------------------------------
        # Generic download error
        # ------------------------------------------------------

        logger.exception(
            "Audio download failed."
        )

        raise DownloadServiceError(
            f"Audio download failed: {message}"
        ) from exc