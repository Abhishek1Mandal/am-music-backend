from __future__ import annotations

import asyncio
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
from app.models.library import LibraryItem
from app.models.play_history import PlayHistory
from app.models.track import Track
from app.models.user_artist_preference import (
    UserArtistPreference,
)
from app.models.user_language import UserLanguage
from app.models.user import User
from app.services.metadata.musicbrainz import musicbrainz_service


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


    async def discover_music(
        self,
        *,
        kind: str,
        limit: int = 20,
        offset: int = 0,
    ) -> dict:
        """Discover music by querying preference pools separately and interleaving them.

        A single broad OR query tends to return many results for one popular
        artist or one language. Separate pools plus round-robin merging keep
        the result set representative of the user's saved preferences.
        """
        language_codes = list(dict.fromkeys(
            code.strip().lower()
            for code in await self.get_user_language_codes()
            if code and code.strip()
        ))

        artist_result = await self.db.execute(
            select(Artist.name)
            .join(UserArtistPreference, UserArtistPreference.artist_id == Artist.id)
            .where(UserArtistPreference.user_id == self.user.id)
            .order_by(Artist.name.asc())
        )
        artist_names = list(dict.fromkeys(
            name.strip()
            for name in artist_result.scalars().all()
            if name and name.strip()
        ))

        if not language_codes and not artist_names:
            return {
                "items": [], "total_count": 0,
                "preferred_languages": [], "preferred_artists": [],
                "local_track_ids": {},
            }

        language_map = musicbrainz_service.LANGUAGE_639_1_TO_639_3
        language_terms = list(dict.fromkeys(
            language_map.get(code, code)
            for code in language_codes
        ))

        def quote_lucene(value: str) -> str:
            return value.replace("\\", "\\\\").replace('"', '\\"').strip()

        current_year = datetime.now(timezone.utc).year
        earliest_year = current_year - 5
        date_field = "firstreleasedate" if kind == "tracks" else "date"
        date_filter = f"{date_field}:[{earliest_year} TO *]"

        # Build a separate pool for every selected artist and every selected
        # language. Keeping them independent avoids the relevance bias of one
        # broad OR query and avoids requiring MusicBrainz to have language
        # metadata for every artist/language pair.
        pool_queries: list[tuple[str, str]] = []
        for name in artist_names:
            pool_queries.append((f"artist:{name}", f'artist:"{quote_lucene(name)}"'))
        for code in language_terms:
            pool_queries.append((f"language:{code}", f"lang:{code}"))

        # Use a small pool from each preference. MusicBrainz rate limiting is
        # enforced by the shared service, so keep the number of calls bounded
        # to the actual selected preferences and cache the response in memory
        # on the frontend for the rest of the app session.
        pool_limit = 100

        async def fetch_pool(label: str, query: str):
            dated_query = f"({query}) AND {date_filter}"
            try:
                if kind == "tracks":
                    items, count = await musicbrainz_service.search_tracks(
                        query=dated_query, limit=pool_limit, offset=0,
                    )
                else:
                    items, count = await musicbrainz_service.search_albums(
                        query=dated_query, limit=pool_limit, offset=0,
                    )
            except Exception:
                # Older metadata can lack date indexing; retry without date.
                if kind == "tracks":
                    items, count = await musicbrainz_service.search_tracks(
                        query=query, limit=pool_limit, offset=0,
                    )
                else:
                    items, count = await musicbrainz_service.search_albums(
                        query=query, limit=pool_limit, offset=0,
                    )
            items = sorted(
                items,
                key=lambda item: (
                    getattr(item, "release_date", None) or "",
                    getattr(item, "title", "").casefold(),
                ),
                reverse=True,
            )
            return label, items, count

        # Concurrent orchestration is safe: MusicBrainzService serializes
        # requests at its documented request interval.
        pools = await asyncio.gather(*(
            fetch_pool(label, query) for label, query in pool_queries
        ))

        # Round-robin by pool, de-duplicating MBIDs. This keeps the first 20
        # cards balanced instead of filling them with the first popular pool.
        merged = []
        seen: set[str] = set()
        max_pool_length = max((len(items) for _, items, _ in pools), default=0)
        for index in range(max_pool_length):
            for _, pool_items, _ in pools:
                if index >= len(pool_items):
                    continue
                item = pool_items[index]
                mbid = getattr(item, "mbid", None)
                if not mbid or mbid in seen:
                    continue
                seen.add(mbid)
                merged.append(item)

        local_tracks: dict[str, UUID] = {}
        if kind == "tracks":
            mbids = [item.mbid for item in merged if item.mbid]
            local_result = await self.db.execute(
                select(Track.id, Track.musicbrainz_id)
                .join(LibraryItem, LibraryItem.track_id == Track.id)
                .where(
                    LibraryItem.user_id == self.user.id,
                    Track.is_available.is_(True),
                    Track.musicbrainz_id.in_(mbids),
                )
            ) if mbids else None
            local_tracks = {
                mbid: track_id
                for track_id, mbid in (local_result.all() if local_result else [])
                if mbid
            }
            for item in merged:
                item.is_downloaded = item.mbid in local_tracks

        return {
            "items": merged[offset:offset + limit],
            "total_count": len(merged),
            "preferred_languages": language_codes,
            "preferred_artists": artist_names,
            "local_track_ids": local_tracks,
        }

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