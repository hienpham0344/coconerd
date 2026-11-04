"""Persist Discord output settings and topic origin channels.

Revision ID: 20261105_0004
Revises: 20261104_0003
"""

import sqlalchemy as sa

from alembic import op

revision = "20261105_0004"
down_revision = "20261104_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("guild_settings", sa.Column("output_channel_id", sa.String(100)))
    op.add_column("topics", sa.Column("channel_id", sa.String(100)))
    op.execute(
        sa.text(
            "UPDATE topics SET channel_id = ("
            "SELECT m.channel_id FROM messages m "
            "JOIN message_topic_associations a ON a.message_record_id=m.id "
            "WHERE a.topic_id=topics.id AND a.guild_id=topics.guild_id "
            "AND m.guild_id=topics.guild_id "
            "ORDER BY m.created_at, m.id LIMIT 1)"
        )
    )
    op.create_index(
        "ix_topics_guild_channel_activity", "topics", ["guild_id", "channel_id", "last_activity_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_topics_guild_channel_activity", table_name="topics")
    op.drop_column("topics", "channel_id")
    op.drop_column("guild_settings", "output_channel_id")
