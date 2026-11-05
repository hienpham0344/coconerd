"""Add audited review state and backfill bounded retrieval aliases.

Revision ID: 20261104_0003
Revises: 20261104_0002
"""

import json
import re
import unicodedata

import sqlalchemy as sa

from alembic import op

revision = "20261104_0003"
down_revision = "20261104_0002"
branch_labels = None
depends_on = None

# Frozen alias expansion: preserve existing terms, add missing canonical spellings.
_ALIASES = {
    "co so du lieu": "database",
    "persistent storage engine": "database",
    "storage engine": "database",
    "data store": "database",
    "datastore": "database",
    "dang nhap": "login",
    "sign in": "login",
    "log in": "login",
    "thanh toan": "payment",
    "han chot": "deadline",
}


def _backfill_aliases():
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT t.id,t.guild_id,t.title,t.description, "
            "(SELECT s.data FROM topic_summaries s WHERE s.topic_id=t.id AND s.guild_id=t.guild_id "
            "ORDER BY s.version DESC LIMIT 1) AS summary FROM topics t"
        )
    ).mappings()
    for row in rows:
        memory = row["summary"] or {}
        if isinstance(memory, str):
            memory = json.loads(memory)
        texts = [
            (row["title"], 3.0),
            (row["description"], 1.5),
            (str(memory.get("overview", "")), 0.75),
        ]
        for field in ("proposals", "decisions", "open_questions", "action_items"):
            values = memory.get(field, [])
            if isinstance(values, list):
                texts.append((" ".join(v for v in values[-20:] if isinstance(v, str)), 0.75))
        weights = {}
        for value, weight in texts:
            value = unicodedata.normalize("NFKD", value[:8000].casefold().replace("đ", "d"))
            value = "".join(c for c in value if not unicodedata.combining(c))
            value = " ".join(re.findall(r"[^\W_]+", value))
            for phrase, term in _ALIASES.items():
                if re.search(r"\b" + re.escape(phrase) + r"\b", value):
                    weights[term] = max(weights.get(term, 0), weight)
        if weights:
            connection.execute(
                sa.text(
                    "INSERT INTO topic_search_terms(topic_id,guild_id,term,weight) "
                    "VALUES (:topic_id,:guild_id,:term,:weight) "
                    "ON CONFLICT(topic_id,term) DO UPDATE SET weight=CASE "
                    "WHEN topic_search_terms.weight > excluded.weight "
                    "THEN topic_search_terms.weight "
                    "ELSE excluded.weight END"
                ),
                [
                    dict(topic_id=row["id"], guild_id=row["guild_id"], term=term, weight=weight)
                    for term, weight in weights.items()
                ],
            )


def upgrade():
    op.add_column("discord_actions", sa.Column("lease_token", sa.String(36), nullable=True))
    op.add_column(
        "topics", sa.Column("sync_paused", sa.Boolean(), nullable=False, server_default="0")
    )
    op.add_column(
        "message_topic_associations",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "discord_actions", sa.Column("superseded", sa.Boolean(), nullable=False, server_default="0")
    )
    op.create_table(
        "review_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("guild_id", sa.String(100), nullable=False),
        sa.Column("request_id", sa.String(100), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("resource_id", sa.String(100), nullable=False),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column(
            "message_record_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="CASCADE")
        ),
        sa.Column("topic_id", sa.String(36), sa.ForeignKey("topics.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("guild_id", "request_id", name="uq_review_guild_request"),
    )
    op.create_index("ix_review_events_guild_id", "review_events", ["guild_id"])
    _backfill_aliases()


def downgrade():
    op.drop_column("discord_actions", "lease_token")
    op.drop_table("review_events")
    op.drop_column("discord_actions", "superseded")
    op.drop_column("message_topic_associations", "revision")
    op.drop_column("topics", "sync_paused")
    # Alias terms are derived, backwards-compatible data; do not delete original index entries.
