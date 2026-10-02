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
# Existing local artist endpoint
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
    query = select(Artist)

    if q:
        query = query.where(
            Artist.name.ilike(
                f"%{q.strip()}%"
            )
        )

    query = (
        query
        .order_by(
            Artist.name.asc()
        )
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)

    artists = result.scalars().all()

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


# ============================================================
# Language-based artist discovery
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
        f"Requested languages: {language_codes}"
    )

    # --------------------------------------------------------
    # Validate languages against database.
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
            status_code=status.HTTP_400_BAD_REQUEST,
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
    # Populate a larger cache than the requested page.
    #
    # Example:
    #
    # limit=20
    # offset=0
    #
    # We populate at least 100 artists.
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
            f"Cached artists: {len(cached_artists)}"
        )

    except Exception as exc:
        print(
            "[discover-artists] "
            "ERROR while querying cached artists:"
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
    # Populate cache from MusicBrainz.
    # --------------------------------------------------------

    if len(cached_artists) < required_count:

        print(
            "[discover-artists] "
            "Cache insufficient. "
            "Starting MusicBrainz discovery."
        )

        try:
            # ------------------------------------------------
            # IMPORTANT:
            #
            # MusicBrainz can return the same artist for
            # multiple languages.
            #
            # Example:
            #
            # Hindi -> Sanjay Leela Bhansali
            # Telugu -> Sanjay Leela Bhansali
            #
            # We keep all artists discovered during this
            # request in this dictionary by MBID.
            # ------------------------------------------------

            pending_artists: dict[str, Artist] = {}

            # ------------------------------------------------
            # Search each selected language.
            # ------------------------------------------------

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

                # ------------------------------------------------
                # Process each discovered artist.
                # ------------------------------------------------

                for metadata in discovered:

                    mbid = metadata.mbid

                    if not mbid:
                        continue

                    # --------------------------------------------
                    # CASE 1:
                    #
                    # Artist was already discovered during this
                    # request.
                    #
                    # This prevents duplicate INSERTs when the
                    # same artist appears in multiple languages.
                    # --------------------------------------------

                    if mbid in pending_artists:

                        artist = pending_artists[mbid]

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

                            print(
                                "[discover-artists] "
                                f"Added language "
                                f"{language_code} to "
                                f"{artist.name}"
                            )

                        continue

                    # --------------------------------------------
                    # CASE 2:
                    #
                    # Check whether the artist already exists
                    # in PostgreSQL.
                    # --------------------------------------------

                    result = await db.execute(
                        select(Artist).where(
                            Artist.musicbrainz_id
                            == mbid
                        )
                    )

                    artist = (
                        result.scalar_one_or_none()
                    )

                    # --------------------------------------------
                    # CASE 2A:
                    #
                    # Artist already exists in database.
                    # --------------------------------------------

                    if artist is not None:

                        print(
                            "[discover-artists] "
                            f"Updating existing artist: "
                            f"{metadata.name}"
                        )

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

                        # Put existing artist into the
                        # request cache as well.
                        pending_artists[mbid] = artist

                        continue

                    # --------------------------------------------
                    # CASE 2B:
                    #
                    # Artist does not exist.
                    # Create it.
                    # --------------------------------------------

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

                    # --------------------------------------------
                    # IMPORTANT:
                    #
                    # Add it immediately to pending_artists.
                    #
                    # This prevents the same MBID from being
                    # inserted twice before db.commit().
                    # --------------------------------------------

                    pending_artists[mbid] = artist

                    print(
                        "[discover-artists] "
                        f"Creating artist: "
                        f"{metadata.name} "
                        f"({mbid})"
                    )

            # ------------------------------------------------
            # Commit all artists once.
            # ------------------------------------------------

            print(
                "[discover-artists] "
                f"Prepared {len(pending_artists)} "
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
                "ERROR during MusicBrainz discovery:"
            )

            print(
                f"Error type: {type(exc).__name__}"
            )

            print(
                f"Error: {exc}"
            )

            traceback.print_exc()

            await db.rollback()

            # ------------------------------------------------
            # If there was no cache, discovery cannot continue.
            # ------------------------------------------------

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

            # ------------------------------------------------
            # Existing cached data can still be returned.
            # ------------------------------------------------

            print(
                "[discover-artists] "
                "Discovery failed, but cached artists "
                "exist. Continuing with cache."
            )

    # --------------------------------------------------------
    # Reload artists after MusicBrainz discovery.
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
            "ERROR while loading final artist list:"
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
    # Resolve artwork only for returned artists.
    #
    # Artwork failure must never fail discovery.
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
                artist.image_url = image_url

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

            # Artwork is optional.
            # Never fail artist discovery.

    await asyncio.gather(
        *(
            resolve_image(artist)
            for artist in page
        )
    )

    # --------------------------------------------------------
    # Commit artwork changes.
    # --------------------------------------------------------

    try:
        await db.commit()

    except Exception as exc:

        print(
            "[discover-artists] "
            "ERROR while committing artwork:"
        )

        print(
            f"Error type: {type(exc).__name__}"
        )

        print(
            f"Error: {exc}"
        )

        traceback.print_exc()

        await db.rollback()

        # Artwork is optional.

    # --------------------------------------------------------
    # Build response.
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

    # --------------------------------------------------------
    # Return response.
    # --------------------------------------------------------

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
# Get preferences
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
# Save onboarding
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

    await db.execute(
        delete(UserLanguage).where(
            UserLanguage.user_id
            == current_user.id
        )
    )

    await db.execute(
        delete(
            UserArtistPreference
        ).where(
            UserArtistPreference.user_id
            == current_user.id
        )
    )

    for language_id in language_ids:
        db.add(
            UserLanguage(
                user_id=current_user.id,
                language_id=language_id,
            )
        )

    for artist_id in artist_ids:
        db.add(
            UserArtistPreference(
                user_id=current_user.id,
                artist_id=artist_id,
            )
        )

    current_user.onboarding_completed = True

    await db.commit()

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