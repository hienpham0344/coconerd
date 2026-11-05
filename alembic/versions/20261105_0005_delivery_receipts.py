"""Persist bot delivery receipts in the shared backend database."""

import sqlalchemy as sa

from alembic import op

revision = "20261105_0005"
down_revision = "20261105_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "delivery_receipts",
        sa.Column("key", sa.String(500), primary_key=True),
        sa.Column("discord_id", sa.String(100), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("delivery_receipts")
