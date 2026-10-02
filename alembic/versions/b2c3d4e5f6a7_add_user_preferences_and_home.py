"""add user preferences and home discovery support

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "languages",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(100),
            nullable=False,
        ),
        sa.Column(
            "code",
            sa.String(20),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_languages_name",
        "languages",
        ["name"],
        unique=True,
    )

    op.create_index(
        "ix_languages_code",
        "languages",
        ["code"],
        unique=True,
    )

    op.create_table(
        "user_languages",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "language_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["language_id"],
            ["languages.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "language_id",
        ),
    )

    op.create_index(
        "ix_user_languages_user_id",
        "user_languages",
        ["user_id"],
    )

    op.create_index(
        "ix_user_languages_language_id",
        "user_languages",
        ["language_id"],
    )

    op.create_table(
        "user_artist_preferences",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "artist_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["artist_id"],
            ["artists.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "user_id",
            "artist_id",
        ),
    )

    op.create_index(
        "ix_user_artist_preferences_user_id",
        "user_artist_preferences",
        ["user_id"],
    )

    op.create_index(
        "ix_user_artist_preferences_artist_id",
        "user_artist_preferences",
        ["artist_id"],
    )

    op.add_column(
        "users",
        sa.Column(
            "onboarding_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.add_column(
        "tracks",
        sa.Column(
            "language_code",
            sa.String(20),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_tracks_language_code",
        "tracks",
        ["language_code"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tracks_language_code",
        table_name="tracks",
    )

    op.drop_column(
        "tracks",
        "language_code",
    )

    op.drop_column(
        "users",
        "onboarding_completed",
    )

    op.drop_index(
        "ix_user_artist_preferences_artist_id",
        table_name="user_artist_preferences",
    )

    op.drop_index(
        "ix_user_artist_preferences_user_id",
        table_name="user_artist_preferences",
    )

    op.drop_table(
        "user_artist_preferences",
    )

    op.drop_index(
        "ix_user_languages_language_id",
        table_name="user_languages",
    )

    op.drop_index(
        "ix_user_languages_user_id",
        table_name="user_languages",
    )

    op.drop_table(
        "user_languages",
    )

    op.drop_index(
        "ix_languages_code",
        table_name="languages",
    )

    op.drop_index(
        "ix_languages_name",
        table_name="languages",
    )

    op.drop_table(
        "languages",
    )