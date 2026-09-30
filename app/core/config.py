from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # ==========================================
    # Application
    # ==========================================

    app_name: str = Field(default="AM Music API")
    app_version: str = Field(default="0.1.0")
    app_environment: str = Field(default="development")
    debug: bool = Field(default=True)

    api_prefix: str = Field(default="/api/v1")

    # ==========================================
    # Database
    # ==========================================

    database_url: str

    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)
    database_pool_timeout: int = Field(default=30, ge=1)
    database_pool_recycle: int = Field(default=1800, ge=0)
    database_echo: bool = Field(default=False)

    # ==========================================
    # CORS
    # ==========================================

    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173"
    )

    # ==========================================
    # Authentication
    # ==========================================

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # ==========================================
    # Music Library
    # ==========================================

    music_library_path: str = "./music"

    # ==========================================
    # MusicBrainz
    # ==========================================

    musicbrainz_base_url: str = Field(
        default="https://musicbrainz.org/ws/2"
    )

    musicbrainz_user_agent: str = Field(
        default="AM-Music/0.1.0"
    )

    # ==========================================
    # Cover Art Archive
    # ==========================================

    cover_art_base_url: str = Field(
        default="https://coverartarchive.org"
    )

    # ==========================================
    # Search
    # ==========================================

    music_search_limit: int = Field(
        default=20,
        ge=1,
        le=100,
    )

    music_search_cache_minutes: int = Field(
        default=60,
        ge=1,
    )

    # ==========================================
    # Pydantic Settings
    # ==========================================

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()