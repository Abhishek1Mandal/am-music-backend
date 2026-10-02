"""add download progress fields

Revision ID: 9c8b7a6d5e4f
Revises: 215b402c91c6
"""
from alembic import op
import sqlalchemy as sa

revision = "9c8b7a6d5e4f"
down_revision = "215b402c91c6"
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column("play_history", sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.alter_column("play_history", "completed", server_default=None)
    op.add_column("downloads", sa.Column("progress_percent", sa.Float(), nullable=False, server_default="0"))
    op.add_column("downloads", sa.Column("downloaded_bytes", sa.BigInteger(), nullable=False, server_default="0"))
    op.add_column("downloads", sa.Column("total_bytes", sa.BigInteger(), nullable=True))
    op.alter_column("downloads", "progress_percent", server_default=None)
    op.alter_column("downloads", "downloaded_bytes", server_default=None)

def downgrade() -> None:
    op.drop_column("downloads", "total_bytes")
    op.drop_column("downloads", "downloaded_bytes")
    op.drop_column("downloads", "progress_percent")
    op.drop_column("play_history", "completed")
