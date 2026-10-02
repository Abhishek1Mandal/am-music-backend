import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Artist(Base):
    __tablename__ = "artists"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        index=True,
        nullable=False,
    )

    sort_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    musicbrainz_id: Mapped[str | None] = mapped_column(
        String(100),
        unique=True,
        nullable=True,
    )

    language_codes: Mapped[list[str]] = mapped_column(
        ARRAY(String(20)),
        nullable=False,
        default=list,
        server_default="{}",
    )

    image_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    biography: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    albums = relationship(
        "Album",
        back_populates="artist",
    )

    tracks = relationship(
        "Track",
        back_populates="artist",
    )

    user_preferences = relationship(
        "UserArtistPreference",
        back_populates="artist",
        cascade="all, delete-orphan",
    )