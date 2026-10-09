from datetime import datetime, timezone

from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.home import (
    HomeAlbum,
    HomeArtist,
    HomeDiscoveryAlbum,
    HomeDiscoveryAlbumDetail,
    HomeDiscoveryArtistDetail,
    HomeDiscoveryAlbumTrack,
    HomeDiscoveryResponse,
    HomeDiscoveryTrack,
    HomeResponse,
    HomeSection,
    HomeTrack,
)
from app.services.home import HomeService
from app.services.metadata.musicbrainz import musicbrainz_service
from app.services.metadata.cover_art import cover_art_service
from app.models.track import Track
from app.models.library import LibraryItem
from sqlalchemy import select


router = APIRouter(
    prefix="/home",
    tags=["Home"],
)


def track_response(row):
    track, artist, album = row

    return HomeTrack(
        id=track.id,
        title=track.title,
        artist_id=artist.id,
        artist_name=artist.name,
        album_id=album.id if album else None,
        album_title=album.title if album else None,
        duration_ms=track.duration_ms,
        language_code=track.language_code,
        musicbrainz_id=track.musicbrainz_id,
        is_available=track.is_available,
    )


def album_response(row):
    album, artist = row

    return HomeAlbum(
        id=album.id,
        title=album.title,
        artist_id=artist.id,
        artist_name=artist.name,
        release_date=album.release_date,
        release_type=album.release_type,
        musicbrainz_id=album.musicbrainz_id,
        cover_url=album.cover_url,
    )




@router.get(
    "/discovery",
    response_model=HomeDiscoveryResponse,
)
async def discover_home_music(
    kind: Literal["tracks", "albums"] = Query(
        default="tracks",
        description="Which discovery collection to return.",
    ),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=99),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return recent external music metadata personalized by saved preferences."""
    service = HomeService(db=db, user=current_user)

    try:
        result = await service.discover_music(
            kind=kind,
            limit=limit,
            offset=offset,
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response else None
        if status_code == 429:
            raise HTTPException(
                status_code=503,
                detail="Music discovery is rate-limited. Please try again shortly.",
            ) from exc
        raise HTTPException(
            status_code=503,
            detail="The music discovery provider is temporarily unavailable.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=503,
            detail="Unable to reach the music discovery provider right now.",
        ) from exc

    response_items = []
    if kind == "tracks":
        local_track_ids = result.get("local_track_ids", {})
        for item in result["items"]:
            response_items.append(
                HomeDiscoveryTrack(
                    **{
                        **item.model_dump(),
                        "language_code": None,
                        "is_downloaded": bool(local_track_ids.get(item.mbid)),
                        "local_track_id": local_track_ids.get(item.mbid),
                    }
                )
            )
    else:
        for item in result["items"]:
            response_items.append(
                HomeDiscoveryAlbum(**item.model_dump())
            )

    return HomeDiscoveryResponse(
        kind=kind,
        limit=limit,
        offset=offset,
        total_count=result["total_count"],
        items=response_items,
        preferred_languages=result["preferred_languages"],
        preferred_artists=result["preferred_artists"],
    )


@router.get(
    "/discovery/artists/{artist_mbid}",
    response_model=HomeDiscoveryArtistDetail,
)
async def get_discovery_artist_detail(
    artist_mbid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return artist metadata and recordings that are already playable locally."""
    try:
        artist = await musicbrainz_service._get(
            f"/artist/{artist_mbid}",
            {"fmt": "json"},
        )
        recordings, _ = await musicbrainz_service.search_tracks(
            query=f"arid:{artist_mbid}",
            limit=100,
            offset=0,
        )
        albums, _ = await musicbrainz_service.search_albums(
            query=f"arid:{artist_mbid}",
            limit=100,
            offset=0,
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else 502
        raise HTTPException(
            status_code=404 if status == 404 else 503,
            detail="Artist details could not be found." if status == 404 else
            "The music metadata provider is temporarily unavailable.",
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Unable to reach the music metadata provider.") from exc

    recording_mbids = [item.mbid for item in recordings]
    local_rows = await db.execute(
        select(Track.musicbrainz_id, Track.id)
        .join(LibraryItem, LibraryItem.track_id == Track.id)
        .where(
            LibraryItem.user_id == current_user.id,
            Track.is_available.is_(True),
            Track.musicbrainz_id.in_(recording_mbids),
        )
    ) if recording_mbids else None
    local_ids = {mbid: track_id for mbid, track_id in (local_rows.all() if local_rows else []) if mbid}

    tracks = [
        HomeDiscoveryTrack(
            **{
                **item.model_dump(),
                "language_code": None,
                "is_downloaded": item.mbid in local_ids,
                "local_track_id": local_ids.get(item.mbid),
            }
        )
        for item in recordings
    ]
    area = artist.get("area") or {}
    return HomeDiscoveryArtistDetail(
        mbid=artist_mbid,
        name=artist.get("name") or "Unknown artist",
        disambiguation=artist.get("disambiguation"),
        country=artist.get("country"),
        area=area.get("name"),
        begin_date=(artist.get("life-span") or {}).get("begin"),
        end_date=(artist.get("life-span") or {}).get("end"),
        artist_type=artist.get("type"),
        albums=[HomeDiscoveryAlbum(**item.model_dump()) for item in albums],
        tracks=tracks,
    )


@router.get(
    "/discovery/albums/{release_mbid}",
    response_model=HomeDiscoveryAlbumDetail,
)
async def get_discovery_album_detail(
    release_mbid: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a MusicBrainz release with its ordered recordings and local playability."""
    try:
        release = await musicbrainz_service._get(
            f"/release/{release_mbid}",
            {"inc": "recordings+artists+artist-credits", "fmt": "json"},
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else 502
        raise HTTPException(status_code=404 if status == 404 else 503,
                            detail="Album details could not be found." if status == 404 else
                            "The music metadata provider is temporarily unavailable.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=503, detail="Unable to reach the music metadata provider.") from exc

    artist_credit = release.get("artist-credit") or []
    artist_names = []
    artist_mbid = None
    for credit in artist_credit:
        if isinstance(credit, dict):
            artist = credit.get("artist") or {}
            if artist.get("name"):
                artist_names.append(artist["name"])
            if artist.get("id") and not artist_mbid:
                artist_mbid = artist["id"]
        elif isinstance(credit, str):
            artist_names.append(credit)
    artist_name = " ".join(artist_names) or None

    raw_tracks = []
    for medium in release.get("media") or []:
        disc_number = medium.get("position")
        for item in medium.get("tracks") or []:
            recording = item.get("recording") or {}
            mbid = recording.get("id")
            if not mbid:
                continue
            length = item.get("length") or recording.get("length")
            try:
                length = int(length) if length is not None else None
            except (TypeError, ValueError):
                length = None
            raw_tracks.append({
                "mbid": mbid,
                "title": item.get("title") or recording.get("title") or "Unknown track",
                "artist_name": artist_name,
                "duration_ms": length,
                "position": item.get("position"),
                "disc_number": disc_number,
            })

    recording_mbids = [track["mbid"] for track in raw_tracks]
    local_rows = await db.execute(
        select(Track.musicbrainz_id, Track.id)
        .join(LibraryItem, LibraryItem.track_id == Track.id)
        .where(
            LibraryItem.user_id == current_user.id,
            Track.is_available.is_(True),
            Track.musicbrainz_id.in_(recording_mbids),
        )
    ) if recording_mbids else None
    local_ids = {mbid: track_id for mbid, track_id in (local_rows.all() if local_rows else []) if mbid}

    tracks = [
        HomeDiscoveryAlbumTrack(
            **item,
            is_downloaded=item["mbid"] in local_ids,
            local_track_id=local_ids.get(item["mbid"]),
        )
        for item in raw_tracks
    ]
    return HomeDiscoveryAlbumDetail(
        mbid=release_mbid,
        title=release.get("title") or "Unknown album",
        artist_name=artist_name,
        artist_mbid=artist_mbid,
        release_date=release.get("date"),
        cover_art_url=cover_art_service.get_front_cover_url(release_mbid, 700),
        tracks=tracks,
    )


@router.get(
    "",
    response_model=HomeResponse,
)
async def get_home(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    service = HomeService(
        db=db,
        user=current_user,
    )

    personalized = (
        await service.personalized_tracks()
    )

    recommended_artists = (
        await service.recommended_artists()
    )

    sections = []

    if personalized:
        sections.append(
            HomeSection(
                type="personalized",
                title="Made For You",
                tracks=[
                    track_response(row)
                    for row in personalized
                ],
            )
        )

    if recommended_artists:
        sections.append(
            HomeSection(
                type="recommended_artists",
                title="Artists You May Like",
                artists=[
                    HomeArtist(
                        id=artist.id,
                        name=artist.name,
                        musicbrainz_id=artist.musicbrainz_id,
                        image_url=artist.image_url,
                    )
                    for artist in recommended_artists
                ],
            )
        )

    return HomeResponse(
        onboarding_completed=(
            current_user.onboarding_completed
        ),
        sections=sections,
        generated_at=datetime.now(
            timezone.utc
        ),
    )