from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application configuration.

    Values are loaded from environment variables and/or .env.
    """

    # ---------------------------------------------------------
    # Application
    # ---------------------------------------------------------

    app_name: str = Field(
        default="OpenMusic API",
        description="Application name",
    )

    app_version: str = Field(
        default="0.1.0",
        description="Application version",
    )

    app_environment: str = Field(
        default="development",
        description="Application environment",
    )

    debug: bool = Field(
        default=True,
        description="Enable debug mode",
    )

    # ---------------------------------------------------------
    # API
    # ---------------------------------------------------------

    api_prefix: str = Field(
        default="/api/v1",
        description="Base API prefix",
    )

    # ---------------------------------------------------------
    # PostgreSQL
    # ---------------------------------------------------------

    database_url: str = Field(
        ...,
        description="Async PostgreSQL database URL",
    )

    # ---------------------------------------------------------
    # Database Pool
    # ---------------------------------------------------------

    database_pool_size: int = Field(
        default=10,
        ge=1,
        description="Number of persistent database connections",
    )

    database_max_overflow: int = Field(
        default=20,
        ge=0,
        description="Additional connections allowed above pool size",
    )

    database_pool_timeout: int = Field(
        default=30,
        ge=1,
        description="Seconds to wait for a connection from the pool",
    )

    database_pool_recycle: int = Field(
        default=1800,
        ge=0,
        description="Seconds before a connection is recycled",
    )

    database_echo: bool = Field(
        default=False,
        description="Log SQL statements",
    )

    # ---------------------------------------------------------
    # CORS
    # ---------------------------------------------------------

    cors_origins: str = Field(
        default="http://localhost:3000,http://localhost:5173",
        description="Comma-separated allowed CORS origins",
    )

    # ---------------------------------------------------------
    # Settings configuration
    # ---------------------------------------------------------

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origins_list(self) -> list[str]:
        """
        Convert comma-separated CORS origins into a list.
        """
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    """
    Return a cached Settings instance.

    Using lru_cache ensures the application doesn't recreate
    the settings object on every request.
    """
    return Settings()


settings = get_settings()