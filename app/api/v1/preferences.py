from __future__ import annotations

import asyncio
import traceback

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
)
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.dependencies.auth import get_current_user
from app.models.artist import Artist
from app.models.language import Language
from app.models.user import User
from app.models.user_artist_preference import (
    UserArtistPreference,
)
from app.models.user_language import UserLanguage
from app.schemas.preferences import (
    DiscoverArtistsRequest,
    DiscoverArtistsResponse,
    DiscoveredArtistResponse,
    LanguageResponse,
    OnboardingRequest,
    PreferredArtistResponse,
    PreferenceStatusResponse,
    PreferencesResponse,
)
from app.services.metadata.deezer import (
    deezer_service,
)
from app.services.metadata.musicbrainz import (
    musicbrainz_service,
)


router = APIRouter(
    prefix="/preferences",
    tags=["Preferences"],
)


# ============================================================
# Languages
# ============================================================


@router.get(
    "/languages",
    response_model=list[LanguageResponse],
)
async def get_languages(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(Language)
        .where(
            Language.is_active.is_(True)
        )
        .order_by(
            Language.name.asc()
        )
    )

    languages = result.scalars().all()

    return [
        LanguageResponse(
            id=language.id,
            name=language.name,
            code=language.code,
        )
        for language in languages
    ]


# ============================================================
# Artist Search
# ============================================================
#
# Flow:
#
# 1. Search local PostgreSQL.
# 2. If results exist -> return them.
# 3. If no results -> search MusicBrainz.
# 4. Cache MusicBrainz results.
# 5. Resolve artwork using Deezer.
# 6. Return results.
#
# Supports:
#
# GET /preferences/artists?q=Eminem
#
# GET /preferences/artists?q=Eminem&language_codes=en
#
# GET /preferences/artists?q=Eminem&language_codes=en&limit=20
#
# ============================================================


@router.get(
    "/artists",
    response_model=list[PreferredArtistResponse],
)
async def get_artists(
    q: str | None = Query(
        default=None,
        min_length=1,
        max_length=100,
    ),
    language_codes: list[str] | None = Query(
        default=None,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # ========================================================
    # Normalize search query
    # ========================================================

    search_query = (
        q.strip()
        if q
        else None
    )

    # ========================================================
    # Normalize language codes
    # ========================================================

    normalized_language_codes: list[str] = []

    if language_codes:
        normalized_language_codes = list(
            dict.fromkeys(
                code.strip().lower()
                for code in language_codes
                if code and code.strip()
            )
        )

    print(
        "[preferences/artists] "
        f"Search query: {search_query}"
    )

    print(
        "[preferences/artists] "
        f"Language codes: "
        f"{normalized_language_codes}"
    )

    print(
        "[preferences/artists] "
        f"Limit: {limit}, Offset: {offset}"
    )

    # ========================================================
    # No search query
    #
    # Return cached/local artists.
    # ========================================================

    if not search_query:

        query = select(Artist)

        # ----------------------------------------------------
        # Optional language filtering.
        # ----------------------------------------------------

        if normalized_language_codes:
            query = query.where(
                Artist.language_codes.overlap(
                    normalized_language_codes
                )
            )

        query = (
            query
            .order_by(
                Artist.name.asc(),
                Artist.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )

        result = await db.execute(query)

        artists = result.scalars().all()

        print(
            "[preferences/artists] "
            f"Returning {len(artists)} "
            "local artists."
        )

        return [
            PreferredArtistResponse(
                id=artist.id,
                name=artist.name,
                musicbrainz_id=(
                    artist.musicbrainz_id
                ),
                image_url=artist.image_url,
            )
            for artist in artists
        ]

    # ========================================================
    # Search PostgreSQL first
    # ========================================================

    local_query = (
        select(Artist)
        .where(
            Artist.name.ilike(
                f"%{search_query}%"
            )
        )
    )

    # --------------------------------------------------------
    # Apply language filtering when provided.
    # --------------------------------------------------------

    if normalized_language_codes:
        local_query = local_query.where(
            Artist.language_codes.overlap(
                normalized_language_codes
            )
        )

    local_query = (
        local_query
        .order_by(
            Artist.name.asc(),
            Artist.id.asc(),
        )
        .offset(offset)
        .limit(limit)
    )

    local_result = await db.execute(
        local_query
    )

    local_artists = list(
        local_result.scalars().all()
    )

    print(
        "[preferences/artists] "
        f"Local search returned "
        f"{len(local_artists)} results."
    )

    # ========================================================
    # Local results found
    #
    # Do NOT call MusicBrainz.
    # ========================================================

    if local_artists:

        print(
            "[preferences/artists] "
            "Using local PostgreSQL results."
        )

        return [
            PreferredArtistResponse(
                id=artist.id,
                name=artist.name,
                musicbrainz_id=(
                    artist.musicbrainz_id
                ),
                image_url=artist.image_url,
            )
            for artist in local_artists
        ]

    # ========================================================
    # No local results.
    #
    # Search MusicBrainz.
    # ========================================================

    print(
        "[preferences/artists] "
        f"No local results for "
        f"'{search_query}'."
    )

    print(
        "[preferences/artists] "
        "Searching MusicBrainz..."
    )

    try:
        discovered_artists, total = (
            await musicbrainz_service.search_artists(
                query=search_query,
                limit=limit,
                offset=offset,
            )
        )

        print(
            "[preferences/artists] "
            f"MusicBrainz returned "
            f"{len(discovered_artists)} "
            f"artists."
        )

        print(
            "[preferences/artists] "
            f"MusicBrainz total: {total}"
        )

    except Exception as exc:

        print(
            "[preferences/artists] "
            "MusicBrainz search failed."
        )

        print(
            f"Error type: {type(exc).__name__}"
        )

        print(
            f"Error: {exc}"
        )

        traceback.print_exc()

        raise HTTPException(
            status_code=(
                status.HTTP_503_SERVICE_UNAVAILABLE
            ),
            detail=(
                "Artist search failed: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    # ========================================================
    # No MusicBrainz results
    # ========================================================

    if not discovered_artists:

        print(
            "[preferences/artists] "
            f"No MusicBrainz results for "
            f"'{search_query}'."
        )

        return []

    # ========================================================
    # Cache MusicBrainz results
    # ========================================================

    pending_artists: dict[str, Artist] = {}

    response_artists: list[Artist] = []

    try:

        for metadata in discovered_artists:

            mbid = metadata.mbid

            if not mbid:
                continue

            # ------------------------------------------------
            # Prevent duplicate MBIDs during this request.
            # ------------------------------------------------

            if mbid in pending_artists:

                artist = pending_artists[mbid]

                response_artists.append(
                    artist
                )

                continue

            # ------------------------------------------------
            # Check database by MusicBrainz MBID.
            # ------------------------------------------------

            result = await db.execute(
                select(Artist).where(
                    Artist.musicbrainz_id
                    == mbid
                )
            )

            artist = (
                result.scalar_one_or_none()
            )

            # ------------------------------------------------
            # Existing artist.
            # ------------------------------------------------

            if artist is not None:

                print(
                    "[preferences/artists] "
                    f"Existing artist: "
                    f"{artist.name}"
                )

                # ------------------------------------------------
                # If a language was provided, add it to the
                # cached artist.
                # ------------------------------------------------

                if normalized_language_codes:

                    current_languages = (
                        artist.language_codes
                        or []
                    )

                    changed = False

                    for language_code in (
                        normalized_language_codes
                    ):

                        if (
                            language_code
                            not in current_languages
                        ):
                            current_languages.append(
                                language_code
                            )

                            changed = True

                    if changed:
                        artist.language_codes = (
                            current_languages
                        )

                pending_artists[mbid] = artist

                response_artists.append(
                    artist
                )

                continue

            # ------------------------------------------------
            # Create new artist.
            # ------------------------------------------------

            artist_languages = (
                normalized_language_codes.copy()
            )

            artist = Artist(
                name=metadata.name,
                sort_name=metadata.sort_name,
                musicbrainz_id=mbid,
                image_url=None,
                biography=None,
                language_codes=artist_languages,
            )

            db.add(artist)

            pending_artists[mbid] = artist

            response_artists.append(
                artist
            )

            print(
                "[preferences/artists] "
                f"Creating artist: "
                f"{metadata.name} "
                f"({mbid})"
            )

        # ----------------------------------------------------
        # Flush first.
        #
        # This assigns UUIDs to newly created Artist objects.
        # ----------------------------------------------------

        await db.flush()

        print(
            "[preferences/artists] "
            f"Prepared "
            f"{len(pending_artists)} "
            "unique artists."
        )

        # ----------------------------------------------------
        # Commit artists.
        # ----------------------------------------------------

        await db.commit()

        print(
            "[preferences/artists] "
            "Artists committed successfully."
        )

    except Exception as exc:

        print(
            "[preferences/artists] "
            "ERROR while caching MusicBrainz artists."
        )

        print(
            f"Error type: {type(exc).__name__}"
        )

        print(
            f"Error: {exc}"
        )

        traceback.print_exc()

        await db.rollback()

        # ----------------------------------------------------
        # Important:
        #
        # MusicBrainz already gave us valid results.
        # If database caching fails, we still return the
        # MusicBrainz data without failing the search.
        # ----------------------------------------------------

        response_artists = []

        for metadata in discovered_artists:

            if not metadata.mbid:
                continue

            response_artists.append(
                Artist(
                    name=metadata.name,
                    sort_name=metadata.sort_name,
                    musicbrainz_id=metadata.mbid,
                    image_url=None,
                    biography=None,
                    language_codes=(
                        normalized_language_codes.copy()
                    ),
                )
            )

    # ========================================================
    # Resolve artwork
    #
    # Only resolve artwork for the returned page.
    # ========================================================

    async def resolve_image(
        artist: Artist,
    ) -> None:

        if artist.image_url:
            return

        try:

            image_url = (
                await deezer_service
                .get_artist_image(
                    artist.name
                )
            )

            if image_url:

                artist.image_url = (
                    image_url
                )

                print(
                    "[preferences/artists] "
                    f"Artwork found for "
                    f"{artist.name}"
                )

        except Exception as exc:

            print(
                "[preferences/artists] "
                f"Artwork lookup failed "
                f"for {artist.name}: "
                f"{type(exc).__name__}: {exc}"
            )

            # Artwork is optional.
            # Never fail artist search.

    await asyncio.gather(
        *(
            resolve_image(artist)
            for artist in response_artists
        )
    )

    # ========================================================
    # Save artwork changes
    # ========================================================

    try:

        await db.commit()

        print(
            "[preferences/artists] "
            "Artwork changes committed."
        )

    except Exception as exc:

        print(
            "[preferences/artists] "
            "Artwork commit failed."
        )

        print(
            f"Error type: {type(exc).__name__}"
        )

        print(
            f"Error: {exc}"
        )

        traceback.print_exc()

        await db.rollback()

    # ========================================================
    # Response
    # ========================================================

    return [
        PreferredArtistResponse(
            id=artist.id,
            name=artist.name,
            musicbrainz_id=(
                artist.musicbrainz_id
            ),
            image_url=artist.image_url,
        )
        for artist in response_artists
        if artist.musicbrainz_id
    ]


# ============================================================
# Language-based Artist Discovery
# ============================================================


@router.post(
    "/discover-artists",
    response_model=DiscoverArtistsResponse,
)
async def discover_artists(
    payload: DiscoverArtistsRequest,
    limit: int = Query(
        default=20,
        ge=1,
        le=50,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # --------------------------------------------------------
    # Normalize requested languages.
    # --------------------------------------------------------

    language_codes = list(
        dict.fromkeys(
            code.strip().lower()
            for code in payload.language_codes
            if code and code.strip()
        )
    )

    if not language_codes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "At least one language code "
                "is required."
            ),
        )

    print(
        "[discover-artists] "
        f"Requested languages: "
        f"{language_codes}"
    )

    # --------------------------------------------------------
    # Validate languages.
    # --------------------------------------------------------

    language_result = await db.execute(
        select(Language).where(
            Language.code.in_(language_codes),
            Language.is_active.is_(True),
        )
    )

    languages = language_result.scalars().all()

    valid_codes = {
        language.code.lower()
        for language in languages
    }

    invalid_codes = [
        code
        for code in language_codes
        if code not in valid_codes
    ]

    if invalid_codes:
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "Unsupported language codes: "
                + ", ".join(invalid_codes)
            ),
        )

    print(
        "[discover-artists] "
        f"Valid languages: {valid_codes}"
    )

    # --------------------------------------------------------
    # We always populate at least 100 artists.
    # --------------------------------------------------------

    required_count = max(
        offset + limit,
        100,
    )

    print(
        "[discover-artists] "
        f"Required count: {required_count}"
    )

    # --------------------------------------------------------
    # Check cached artists.
    # --------------------------------------------------------

    try:

        cached_result = await db.execute(
            select(Artist)
            .where(
                Artist.language_codes.overlap(
                    language_codes
                )
            )
            .order_by(
                Artist.name.asc(),
                Artist.id.asc(),
            )
        )

        cached_artists = list(
            cached_result.scalars().all()
        )

        print(
            "[discover-artists] "
            f"Cached artists: "
            f"{len(cached_artists)}"
        )

    except Exception as exc:

        print(
            "[discover-artists] "
            "ERROR while querying cached artists."
        )

        print(
            f"Error type: {type(exc).__name__}"
        )

        print(
            f"Error: {exc}"
        )

        traceback.print_exc()

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Failed to query cached artists: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    # --------------------------------------------------------
    # Discover from MusicBrainz when cache is insufficient.
    # --------------------------------------------------------

    if len(cached_artists) < required_count:

        print(
            "[discover-artists] "
            "Cache insufficient. "
            "Starting MusicBrainz discovery."
        )

        try:

            # ------------------------------------------------
            # Prevent duplicate MBIDs across languages.
            # ------------------------------------------------

            pending_artists: dict[str, Artist] = {}

            for language_code in language_codes:

                print(
                    "[discover-artists] "
                    f"Searching MusicBrainz for "
                    f"language={language_code}"
                )

                discovered = (
                    await musicbrainz_service
                    .search_artists_by_language(
                        language_code=language_code,
                        max_artists=100,
                    )
                )

                print(
                    "[discover-artists] "
                    f"MusicBrainz returned "
                    f"{len(discovered)} artists "
                    f"for {language_code}"
                )

                for metadata in discovered:

                    mbid = metadata.mbid

                    if not mbid:
                        continue

                    # ----------------------------------------
                    # Already discovered during this request.
                    # ----------------------------------------

                    if mbid in pending_artists:

                        artist = (
                            pending_artists[mbid]
                        )

                        current_languages = (
                            artist.language_codes
                            or []
                        )

                        if (
                            language_code
                            not in current_languages
                        ):

                            artist.language_codes = (
                                current_languages
                                + [language_code]
                            )

                        continue

                    # ----------------------------------------
                    # Check DB.
                    # ----------------------------------------

                    result = await db.execute(
                        select(Artist).where(
                            Artist.musicbrainz_id
                            == mbid
                        )
                    )

                    artist = (
                        result.scalar_one_or_none()
                    )

                    # ----------------------------------------
                    # Existing artist.
                    # ----------------------------------------

                    if artist is not None:

                        artist.name = (
                            metadata.name
                        )

                        artist.sort_name = (
                            metadata.sort_name
                        )

                        current_languages = (
                            artist.language_codes
                            or []
                        )

                        if (
                            language_code
                            not in current_languages
                        ):

                            artist.language_codes = (
                                current_languages
                                + [language_code]
                            )

                        pending_artists[mbid] = (
                            artist
                        )

                        continue

                    # ----------------------------------------
                    # New artist.
                    # ----------------------------------------

                    artist = Artist(
                        name=metadata.name,
                        sort_name=metadata.sort_name,
                        musicbrainz_id=mbid,
                        image_url=None,
                        biography=None,
                        language_codes=[
                            language_code
                        ],
                    )

                    db.add(artist)

                    pending_artists[mbid] = (
                        artist
                    )

            print(
                "[discover-artists] "
                f"Prepared "
                f"{len(pending_artists)} "
                "unique artists."
            )

            await db.commit()

            print(
                "[discover-artists] "
                "MusicBrainz artists committed "
                "successfully."
            )

        except Exception as exc:

            print(
                "[discover-artists] "
                "ERROR during MusicBrainz discovery."
            )

            print(
                f"Error type: {type(exc).__name__}"
            )

            print(
                f"Error: {exc}"
            )

            traceback.print_exc()

            await db.rollback()

            if not cached_artists:

                raise HTTPException(
                    status_code=(
                        status.HTTP_503_SERVICE_UNAVAILABLE
                    ),
                    detail=(
                        "Artist discovery failed: "
                        f"{type(exc).__name__}: {exc}"
                    ),
                ) from exc

            print(
                "[discover-artists] "
                "Discovery failed, but cached "
                "artists exist."
            )

    # --------------------------------------------------------
    # Reload cached artists.
    # --------------------------------------------------------

    try:

        cached_result = await db.execute(
            select(Artist)
            .where(
                Artist.language_codes.overlap(
                    language_codes
                )
            )
            .order_by(
                Artist.name.asc(),
                Artist.id.asc(),
            )
        )

        cached_artists = list(
            cached_result.scalars().all()
        )

        print(
            "[discover-artists] "
            f"Final cached artists: "
            f"{len(cached_artists)}"
        )

    except Exception as exc:

        print(
            "[discover-artists] "
            "ERROR while loading final artist list."
        )

        print(
            f"Error type: {type(exc).__name__}"
        )

        print(
            f"Error: {exc}"
        )

        traceback.print_exc()

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),
            detail=(
                "Failed to load discovered artists: "
                f"{type(exc).__name__}: {exc}"
            ),
        ) from exc

    # --------------------------------------------------------
    # Pagination.
    # --------------------------------------------------------

    total = len(cached_artists)

    page = cached_artists[
        offset:offset + limit
    ]

    print(
        "[discover-artists] "
        f"Returning {len(page)} artists "
        f"(offset={offset}, "
        f"limit={limit}, "
        f"total={total})"
    )

    # --------------------------------------------------------
    # Artwork
    # --------------------------------------------------------

    async def resolve_image(
        artist: Artist,
    ) -> None:

        if artist.image_url:
            return

        try:

            image_url = (
                await deezer_service
                .get_artist_image(
                    artist.name
                )
            )

            if image_url:

                artist.image_url = (
                    image_url
                )

                print(
                    "[discover-artists] "
                    f"Artwork found for "
                    f"{artist.name}"
                )

        except Exception as exc:

            print(
                "[discover-artists] "
                f"Artwork lookup failed for "
                f"{artist.name}: "
                f"{type(exc).__name__}: {exc}"
            )

    await asyncio.gather(
        *(
            resolve_image(artist)
            for artist in page
        )
    )

    # --------------------------------------------------------
    # Commit artwork.
    # --------------------------------------------------------

    try:

        await db.commit()

    except Exception as exc:

        print(
            "[discover-artists] "
            "ERROR while committing artwork."
        )

        print(
            f"Error type: {type(exc).__name__}"
        )

        print(
            f"Error: {exc}"
        )

        traceback.print_exc()

        await db.rollback()

    # --------------------------------------------------------
    # Response.
    # --------------------------------------------------------

    response_artists = [
        DiscoveredArtistResponse(
            id=artist.id,
            musicbrainz_id=(
                artist.musicbrainz_id
                or ""
            ),
            name=artist.name,
            sort_name=artist.sort_name,
            country=None,
            type=None,
            disambiguation=None,
            image_url=artist.image_url,
        )
        for artist in page
        if artist.musicbrainz_id
    ]

    return DiscoverArtistsResponse(
        languages=language_codes,
        artists=response_artists,
        total=total,
        limit=limit,
        offset=offset,
        has_more=(
            offset + limit < total
        ),
    )


# ============================================================
# Status
# ============================================================


@router.get(
    "/status",
    response_model=PreferenceStatusResponse,
)
async def get_preference_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    language_result = await db.execute(
        select(
            func.count(
                UserLanguage.language_id
            )
        ).where(
            UserLanguage.user_id
            == current_user.id
        )
    )

    artist_result = await db.execute(
        select(
            func.count(
                UserArtistPreference.artist_id
            )
        ).where(
            UserArtistPreference.user_id
            == current_user.id
        )
    )

    return PreferenceStatusResponse(
        onboarding_completed=(
            current_user.onboarding_completed
        ),
        language_count=(
            language_result.scalar() or 0
        ),
        artist_count=(
            artist_result.scalar() or 0
        ),
    )


# ============================================================
# Get Preferences
# ============================================================


@router.get(
    "",
    response_model=PreferencesResponse,
)
async def get_preferences(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    language_result = await db.execute(
        select(Language)
        .join(
            UserLanguage,
            UserLanguage.language_id
            == Language.id,
        )
        .where(
            UserLanguage.user_id
            == current_user.id
        )
        .order_by(
            Language.name.asc()
        )
    )

    artist_result = await db.execute(
        select(Artist)
        .join(
            UserArtistPreference,
            UserArtistPreference.artist_id
            == Artist.id,
        )
        .where(
            UserArtistPreference.user_id
            == current_user.id
        )
        .order_by(
            Artist.name.asc()
        )
    )

    languages = (
        language_result.scalars().all()
    )

    artists = (
        artist_result.scalars().all()
    )

    return PreferencesResponse(
        onboarding_completed=(
            current_user.onboarding_completed
        ),
        languages=[
            LanguageResponse(
                id=language.id,
                name=language.name,
                code=language.code,
            )
            for language in languages
        ],
        artists=[
            PreferredArtistResponse(
                id=artist.id,
                name=artist.name,
                musicbrainz_id=(
                    artist.musicbrainz_id
                ),
                image_url=artist.image_url,
            )
            for artist in artists
        ],
    )


# ============================================================
# Save Onboarding Preferences
# ============================================================


@router.post(
    "/onboarding",
    response_model=PreferencesResponse,
    status_code=status.HTTP_200_OK,
)
async def save_onboarding_preferences(
    payload: OnboardingRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    language_ids = list(
        dict.fromkeys(
            payload.language_ids
        )
    )

    artist_ids = list(
        dict.fromkeys(
            payload.artist_ids
        )
    )

    # --------------------------------------------------------
    # Languages are required.
    # --------------------------------------------------------

    if not language_ids:

        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "At least one language "
                "must be selected."
            ),
        )

    # --------------------------------------------------------
    # Validate languages.
    # --------------------------------------------------------

    language_result = await db.execute(
        select(Language).where(
            Language.id.in_(
                language_ids
            ),
            Language.is_active.is_(True),
        )
    )

    languages = (
        language_result.scalars().all()
    )

    if len(languages) != len(
        language_ids
    ):

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "One or more selected "
                "languages are invalid."
            ),
        )

    # --------------------------------------------------------
    # Validate artists.
    # --------------------------------------------------------

    if artist_ids:

        artist_result = await db.execute(
            select(Artist).where(
                Artist.id.in_(
                    artist_ids
                )
            )
        )

        artists = (
            artist_result.scalars().all()
        )

        if len(artists) != len(
            artist_ids
        ):

            raise HTTPException(
                status_code=(
                    status.HTTP_400_BAD_REQUEST
                ),
                detail=(
                    "One or more selected "
                    "artists are invalid."
                ),
            )

    else:

        artists = []

    # --------------------------------------------------------
    # Remove old language preferences.
    # --------------------------------------------------------

    await db.execute(
        delete(UserLanguage).where(
            UserLanguage.user_id
            == current_user.id
        )
    )

    # --------------------------------------------------------
    # Remove old artist preferences.
    # --------------------------------------------------------

    await db.execute(
        delete(
            UserArtistPreference
        ).where(
            UserArtistPreference.user_id
            == current_user.id
        )
    )

    # --------------------------------------------------------
    # Save languages.
    # --------------------------------------------------------

    for language_id in language_ids:

        db.add(
            UserLanguage(
                user_id=current_user.id,
                language_id=language_id,
            )
        )

    # --------------------------------------------------------
    # Save artists.
    # --------------------------------------------------------

    for artist_id in artist_ids:

        db.add(
            UserArtistPreference(
                user_id=current_user.id,
                artist_id=artist_id,
            )
        )

    # --------------------------------------------------------
    # Mark onboarding complete.
    # --------------------------------------------------------

    current_user.onboarding_completed = True

    await db.commit()

    # --------------------------------------------------------
    # Return saved preferences.
    # --------------------------------------------------------

    return PreferencesResponse(
        onboarding_completed=True,
        languages=[
            LanguageResponse(
                id=language.id,
                name=language.name,
                code=language.code,
            )
            for language in languages
        ],
        artists=[
            PreferredArtistResponse(
                id=artist.id,
                name=artist.name,
                musicbrainz_id=(
                    artist.musicbrainz_id
                ),
                image_url=artist.image_url,
            )
            for artist in artists
        ],
    )