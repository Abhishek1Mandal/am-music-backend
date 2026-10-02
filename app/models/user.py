import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user_artist_preference import UserArtistPreference
    from app.models.user_language import UserLanguage


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )

    username: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
    )

    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    playlists = relationship(
        "Playlist",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    favorites = relationship(
        "Favorite",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    play_history = relationship(
        "PlayHistory",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    library_items = relationship(
        "LibraryItem",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    downloads = relationship(
        "Download",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    language_preferences: Mapped[list["UserLanguage"]] = relationship(
        "UserLanguage",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    artist_preferences: Mapped[list["UserArtistPreference"]] = relationship(
        "UserArtistPreference",
        back_populates="user",
        cascade="all, delete-orphan",
    )