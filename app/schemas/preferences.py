import uuid

from pydantic import BaseModel, Field


class LanguageResponse(BaseModel):
    id: uuid.UUID
    name: str
    code: str


class PreferredArtistResponse(BaseModel):
    id: uuid.UUID
    name: str
    musicbrainz_id: str | None = None
    image_url: str | None = None


class PreferenceStatusResponse(BaseModel):
    onboarding_completed: bool
    language_count: int
    artist_count: int


class DiscoverArtistsRequest(BaseModel):
    language_codes: list[str] = Field(
        min_length=1,
        max_length=20,
    )


class DiscoveredArtistResponse(BaseModel):
    id: uuid.UUID
    musicbrainz_id: str
    name: str
    sort_name: str | None = None
    country: str | None = None
    type: str | None = None
    disambiguation: str | None = None
    image_url: str | None = None


class DiscoverArtistsResponse(BaseModel):
    languages: list[str]
    artists: list[DiscoveredArtistResponse]
    total: int
    limit: int
    offset: int
    has_more: bool


class OnboardingRequest(BaseModel):
    language_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=20,
    )

    artist_ids: list[uuid.UUID] = Field(
        default_factory=list,
        max_length=50,
    )


class PreferencesResponse(BaseModel):
    onboarding_completed: bool
    languages: list[LanguageResponse]
    artists: list[PreferredArtistResponse]