from __future__ import annotations

from pathlib import Path

from mutagen.id3 import (
    APIC,
    TALB,
    TCOM,
    TDRC,
    TIT2,
    TPE1,
    TPE2,
    TRCK,
    TPOS,
    TXXX,
    ID3,
    ID3NoHeaderError,
)

from app.services.music.metadata_resolver import (
    ResolvedMetadata,
)


def write_mp3_metadata(
    file_path: str | Path,
    metadata: ResolvedMetadata,
    artwork_bytes: bytes | None = None,
    artwork_mime: str = "image/jpeg",
) -> None:
    """
    Write final resolved metadata to an MP3 file.

    MusicBrainz-derived metadata has already been selected by
    resolve_metadata().
    """

    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(
            f"MP3 file not found: {path}"
        )

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    # ---------------------------------------------------------
    # Standard ID3 fields
    # ---------------------------------------------------------

    tags.delall("TIT2")
    tags.add(
        TIT2(
            encoding=3,
            text=[metadata.title],
        )
    )

    tags.delall("TPE1")
    tags.add(
        TPE1(
            encoding=3,
            text=[metadata.artist],
        )
    )

    tags.delall("TALB")
    tags.add(
        TALB(
            encoding=3,
            text=[metadata.album],
        )
    )

    tags.delall("TPE2")
    tags.add(
        TPE2(
            encoding=3,
            text=[metadata.album_artist],
        )
    )

    # ---------------------------------------------------------
    # Track number
    # ---------------------------------------------------------

    if metadata.track_number is not None:
        tags.delall("TRCK")

        tags.add(
            TRCK(
                encoding=3,
                text=[
                    str(
                        metadata.track_number
                    )
                ],
            )
        )

    # ---------------------------------------------------------
    # Disc number
    # ---------------------------------------------------------

    if metadata.disc_number is not None:
        tags.delall("TPOS")

        tags.add(
            TPOS(
                encoding=3,
                text=[
                    str(
                        metadata.disc_number
                    )
                ],
            )
        )

    # ---------------------------------------------------------
    # Release date
    # ---------------------------------------------------------

    if metadata.release_date:
        tags.delall("TDRC")

        tags.add(
            TDRC(
                encoding=3,
                text=[
                    metadata.release_date
                ],
            )
        )

    # ---------------------------------------------------------
    # MusicBrainz Recording ID
    # ---------------------------------------------------------

    if metadata.musicbrainz_recording_id:
        tags.delall(
            "MusicBrainz Track Id"
        )

        tags.add(
            TXXX(
                encoding=3,
                desc="MusicBrainz Track Id",
                text=[
                    metadata.musicbrainz_recording_id
                ],
            )
        )

    # ---------------------------------------------------------
    # MusicBrainz Release ID
    # ---------------------------------------------------------

    if metadata.musicbrainz_release_id:
        tags.delall(
            "MusicBrainz Album Id"
        )

        tags.add(
            TXXX(
                encoding=3,
                desc="MusicBrainz Album Id",
                text=[
                    metadata.musicbrainz_release_id
                ],
            )
        )

    # ---------------------------------------------------------
    # MusicBrainz Artist ID
    # ---------------------------------------------------------

    if metadata.musicbrainz_artist_id:
        tags.delall(
            "MusicBrainz Artist Id"
        )

        tags.add(
            TXXX(
                encoding=3,
                desc="MusicBrainz Artist Id",
                text=[
                    metadata.musicbrainz_artist_id
                ],
            )
        )

    # ---------------------------------------------------------
    # MusicBrainz Release Group ID
    # ---------------------------------------------------------

    if metadata.musicbrainz_release_group_id:
        tags.delall(
            "MusicBrainz Release Group Id"
        )

        tags.add(
            TXXX(
                encoding=3,
                desc="MusicBrainz Release Group Id",
                text=[
                    metadata.musicbrainz_release_group_id
                ],
            )
        )

    # ---------------------------------------------------------
    # YouTube uploader
    # ---------------------------------------------------------
    #
    # Important:
    #
    # We DO NOT write this into Artist.
    #
    # It is stored separately as informational source metadata.
    # ---------------------------------------------------------

    if metadata.youtube_uploader:
        tags.delall(
            "YouTube Uploader"
        )

        tags.add(
            TXXX(
                encoding=3,
                desc="YouTube Uploader",
                text=[
                    metadata.youtube_uploader
                ],
            )
        )

    # ---------------------------------------------------------
    # Artwork
    # ---------------------------------------------------------

    if artwork_bytes:
        tags.delall("APIC")

        tags.add(
            APIC(
                encoding=3,
                mime=artwork_mime,
                type=3,  # Front cover
                desc="Cover",
                data=artwork_bytes,
            )
        )

    tags.save(
        path,
        v2_version=3,
    )