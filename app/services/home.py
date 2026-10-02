from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import (
    case,
    desc,
    func,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.album import Album
from app.models.artist import Artist
from app.models.download import Download
from app.models.favorite import Favorite
from app.models.language import Language
from app.models.play_history import PlayHistory
from app.models.track import Track
from app.models.user_artist_preference import (
    UserArtistPreference,
)
from app.models.user_language import UserLanguage
from app.models.user import User


class HomeService:

    def __init__(
        self,
        db: AsyncSession,
        user: User,
    ):
        self.db = db
        self.user = user

    async def get_user_language_codes(self) -> list[str]:
        result = await self.db.execute(
            select(Language.code)
            .join(
                UserLanguage,
                UserLanguage.language_id
                == Language.id,
            )
            .where(
                UserLanguage.user_id
                == self.user.id
            )
        )

        return list(result.scalars().all())

    async def get_user_artist_ids(self) -> list[UUID]:
        result = await self.db.execute(
            select(
                UserArtistPreference.artist_id
            ).where(
                UserArtistPreference.user_id
                == self.user.id
            )
        )

        return list(result.scalars().all())

    async def personalized_tracks(
        self,
        limit: int = 20,
    ):
        language_codes = (
            await self.get_user_language_codes()
        )

        artist_ids = (
            await self.get_user_artist_ids()
        )

        if not language_codes:
            return []

        language_match = case(
            (
                Track.language_code.in_(
                    language_codes
                ),
                50,
            ),
            else_=0,
        )

        artist_match = case(
            (
                Track.artist_id.in_(
                    artist_ids
                ),
                50,
            ),
            else_=0,
        )

        favorite_count = (
            select(
                func.count(Favorite.id)
            )
            .where(
                Favorite.track_id == Track.id
            )
            .correlate(Track)
            .scalar_subquery()
        )

        play_count = (
            select(
                func.count(PlayHistory.id)
            )
            .where(
                PlayHistory.track_id == Track.id
            )
            .correlate(Track)
            .scalar_subquery()
        )

        score = (
            language_match
            + artist_match
            + func.least(favorite_count, 20)
            + func.least(play_count, 20)
        )

        result = await self.db.execute(
            select(
                Track,
                Artist,
                Album,
            )
            .join(
                Artist,
                Artist.id == Track.artist_id,
            )
            .outerjoin(
                Album,
                Album.id == Track.album_id,
            )
            .where(
                Track.is_available.is_(True),
                Track.language_code.in_(
                    language_codes
                ),
            )
            .order_by(
                desc(score),
                Track.created_at.desc(),
            )
            .limit(limit)
        )

        return result.all()

    async def trending_tracks(
        self,
        limit: int = 20,
    ):
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=30)

        play_count = (
            select(
                func.count(PlayHistory.id)
            )
            .where(
                PlayHistory.track_id == Track.id,
                PlayHistory.played_at >= since,
            )
            .correlate(Track)
            .scalar_subquery()
        )

        favorite_count = (
            select(
                func.count(Favorite.id)
            )
            .where(
                Favorite.track_id == Track.id,
                Favorite.created_at >= since,
            )
            .correlate(Track)
            .scalar_subquery()
        )

        download_count = (
            select(
                func.count(Download.id)
            )
            .where(
                Download.track_id == Track.id,
                Download.created_at >= since,
                Download.status == "completed",
            )
            .correlate(Track)
            .scalar_subquery()
        )

        score = (
            (play_count * 5)
            + (favorite_count * 8)
            + (download_count * 3)
        )

        result = await self.db.execute(
            select(
                Track,
                Artist,
                Album,
            )
            .join(
                Artist,
                Artist.id == Track.artist_id,
            )
            .outerjoin(
                Album,
                Album.id == Track.album_id,
            )
            .where(
                Track.is_available.is_(True)
            )
            .order_by(
                desc(score),
                Track.created_at.desc(),
            )
            .limit(limit)
        )

        return result.all()

    async def trending_albums(
        self,
        limit: int = 20,
    ):
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=30)

        play_count = (
            select(
                func.count(PlayHistory.id)
            )
            .join(
                Track,
                Track.id == PlayHistory.track_id,
            )
            .where(
                Track.album_id == Album.id,
                PlayHistory.played_at >= since,
            )
            .correlate(Album)
            .scalar_subquery()
        )

        favorite_count = (
            select(
                func.count(Favorite.id)
            )
            .join(
                Track,
                Track.id == Favorite.track_id,
            )
            .where(
                Track.album_id == Album.id,
                Favorite.created_at >= since,
            )
            .correlate(Album)
            .scalar_subquery()
        )

        score = (
            (play_count * 5)
            + (favorite_count * 8)
        )

        result = await self.db.execute(
            select(
                Album,
                Artist,
            )
            .join(
                Artist,
                Artist.id == Album.artist_id,
            )
            .order_by(
                desc(score),
                Album.created_at.desc(),
            )
            .limit(limit)
        )

        return result.all()

    async def recommended_artists(
        self,
        limit: int = 20,
    ):
        language_codes = (
            await self.get_user_language_codes()
        )

        if not language_codes:
            return []

        result = await self.db.execute(
            select(
                Artist,
                func.count(Track.id).label(
                    "track_count"
                ),
            )
            .join(
                Track,
                Track.artist_id == Artist.id,
            )
            .where(
                Track.language_code.in_(
                    language_codes
                )
            )
            .group_by(Artist.id)
            .order_by(
                desc("track_count"),
                Artist.name.asc(),
            )
            .limit(limit)
        )

        return [
            artist
            for artist, _ in result.all()
        ]