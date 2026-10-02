"""add created_at to genres

Revision ID: a1b2c3d4e5f6
Revises: 9c8b7a6d5e4f
Create Date: 2026-10-02
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "9c8b7a6d5e4f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "genres",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "genres",
        "created_at",
    )