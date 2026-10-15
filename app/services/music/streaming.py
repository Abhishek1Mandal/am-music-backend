from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StreamFile:
    path: Path
    media_type: str
    file_size: int


@dataclass
class ByteRange:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start + 1


class StreamingError(Exception):
    """Base exception for streaming errors."""


class StreamFileNotFoundError(StreamingError):
    """Raised when the track file does not exist."""


class StreamFileUnavailableError(StreamingError):
    """Raised when the track is not available for streaming."""


class InvalidRangeError(StreamingError):
    """Raised when an HTTP Range header is invalid."""


class StreamingService:
    """
    Resolve and validate local music files for HTTP streaming.

    This service does not modify the database.
    """

    def __init__(self, library_root: str | Path):
        self.library_root = Path(library_root).resolve()

    def resolve_file(
        self,
        file_path: str | None,
        is_available: bool,
        mime_type: str | None = None,
    ) -> StreamFile:
        if not is_available:
            raise StreamFileUnavailableError(
                "Track is not available for streaming."
            )

        if not file_path:
            raise StreamFileNotFoundError(
                "Track does not have a file path."
            )

        path = Path(file_path)

        if not path.is_absolute():
            path = self.library_root / path

        try:
            resolved_path = path.resolve()
        except OSError as exc:
            raise StreamFileNotFoundError(
                "Unable to resolve track file."
            ) from exc

        # Prevent accidental path traversal outside the music library.
        try:
            resolved_path.relative_to(self.library_root)
        except ValueError as exc:
            raise StreamFileNotFoundError(
                "Track file is outside the music library."
            ) from exc

        if not resolved_path.is_file():
            raise StreamFileNotFoundError(
                "Track audio file does not exist."
            )

        try:
            file_size = resolved_path.stat().st_size
        except OSError as exc:
            raise StreamFileNotFoundError(
                "Unable to read track file."
            ) from exc

        if file_size <= 0:
            raise StreamFileNotFoundError(
                "Track audio file is empty."
            )

        detected_mime_type = (
            mime_type
            or mimetypes.guess_type(resolved_path.name)[0]
            or "audio/mpeg"
        )

        return StreamFile(
            path=resolved_path,
            media_type=detected_mime_type,
            file_size=file_size,
        )

    @staticmethod
    def parse_range(
        range_header: str | None,
        file_size: int,
    ) -> ByteRange | None:
        """
        Parse a single HTTP byte range.

        Supported examples:

            bytes=0-1023
            bytes=1024-
            bytes=-1024
        """

        if not range_header:
            return None

        if not range_header.startswith("bytes="):
            raise InvalidRangeError("Invalid Range header.")

        range_value = range_header[len("bytes="):].strip()

        # This implementation intentionally supports one range only.
        if "," in range_value:
            raise InvalidRangeError(
                "Multiple byte ranges are not supported."
            )

        if "-" not in range_value:
            raise InvalidRangeError("Invalid Range header.")

        start_text, end_text = range_value.split("-", 1)

        try:
            if start_text == "":
                # Suffix range:
                # bytes=-1024
                suffix_length = int(end_text)

                if suffix_length <= 0:
                    raise InvalidRangeError(
                        "Invalid suffix byte range."
                    )

                start = max(file_size - suffix_length, 0)
                end = file_size - 1

            else:
                start = int(start_text)

                if start < 0:
                    raise InvalidRangeError(
                        "Invalid range start."
                    )

                if start >= file_size:
                    raise InvalidRangeError(
                        "Range start is outside the file."
                    )

                if end_text == "":
                    # bytes=1024-
                    end = file_size - 1

                else:
                    end = int(end_text)

                    if end < start:
                        raise InvalidRangeError(
                            "Range end is before range start."
                        )

                    end = min(end, file_size - 1)

        except ValueError as exc:
            raise InvalidRangeError(
                "Invalid Range header."
            ) from exc

        return ByteRange(
            start=start,
            end=end,
        )