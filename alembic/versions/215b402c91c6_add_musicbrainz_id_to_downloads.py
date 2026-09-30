from alembic import op
import sqlalchemy as sa


revision = "add_download_musicbrainz_id"
down_revision = "4fa11d2db0da"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "downloads",
        sa.Column(
            "musicbrainz_id",
            sa.String(length=100),
            nullable=True,
        ),
    )

    op.alter_column(
        "downloads",
        "source_url",
        existing_type=sa.Text(),
        nullable=True,
    )

    op.create_index(
        "ix_downloads_musicbrainz_id",
        "downloads",
        ["musicbrainz_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_downloads_musicbrainz_id",
        table_name="downloads",
    )

    op.alter_column(
        "downloads",
        "source_url",
        existing_type=sa.Text(),
        nullable=False,
    )

    op.drop_column(
        "downloads",
        "musicbrainz_id",
    )