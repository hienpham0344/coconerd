"""Persist encrypted dashboard sessions and one-use OAuth state."""

import sqlalchemy as sa

from alembic import op

revision = "20261105_0007"
down_revision = "20261105_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_credentials",
        sa.Column("kind", sa.String(10), primary_key=True),
        sa.Column("key_hash", sa.String(64), primary_key=True),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_dashboard_credentials_expires_at", "dashboard_credentials", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_dashboard_credentials_expires_at", table_name="dashboard_credentials")
    op.drop_table("dashboard_credentials")
