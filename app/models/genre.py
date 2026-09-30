import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Table, Column, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


track_genres = Table(
    "track_genres",
    Base.metadata,
    Column(
        "track_id",
        UUID(as_uuid=True),
        ForeignKey("tracks.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "genre_id",
        UUID(as_uuid=True),
        ForeignKey("genres.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Genre(Base):
    __tablename__ = "genres"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        index=True,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    tracks = relationship(
        "Track",
        secondary=track_genres,
        back_populates="genres",
    )