"""Keep Discord attachment metadata alongside messages for durable delivery."""

import sqlalchemy as sa

from alembic import op

revision = "20261105_0006"
down_revision = "20261105_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("attachments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("messages", "attachments")
