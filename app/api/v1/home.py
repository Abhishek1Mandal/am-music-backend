from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.home import (
    HomeAlbum,
    HomeArtist,
    HomeResponse,
    HomeSection,
    HomeTrack,
)
from app.services.home import HomeService


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

    trending = (
        await service.trending_tracks()
    )

    trending_albums = (
        await service.trending_albums()
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

    if trending:
        sections.append(
            HomeSection(
                type="trending_tracks",
                title="Trending Music",
                tracks=[
                    track_response(row)
                    for row in trending
                ],
            )
        )

    if trending_albums:
        sections.append(
            HomeSection(
                type="trending_albums",
                title="Trending Albums",
                albums=[
                    album_response(row)
                    for row in trending_albums
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