"""Add durable agent budgets, deferred evidence and a lexical topic index.

Revision ID: 20261104_0002
Revises: 20261103_0001
"""

import json
import re
import unicodedata

import sqlalchemy as sa

from alembic import op

revision = "20261104_0002"
down_revision = "20261103_0001"
branch_labels = None
depends_on = None


def _terms(value):
    # Frozen v1 tokenizer: migrations must not depend on future application code.
    value = unicodedata.normalize("NFKD", value[:10000].casefold().replace("đ", "d"))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = " ".join(re.findall(r"[^\W_]+", value))
    value = value.replace("co so du lieu", "database").replace("dang nhap", "login")
    stop = set(
        [
            "a",
            "an",
            "and",
            "are",
            "for",
            "in",
            "is",
            "of",
            "on",
            "or",
            "the",
            "to",
            "with",
            "we",
            "our",
            "la",
            "va",
            "cua",
            "cho",
            "minh",
            "toi",
            "ban",
            "mot",
            "nhung",
            "cac",
        ]
    )
    aliases = {"db": "database", "csdl": "database", "auth": "authentication"}
    return list(
        dict.fromkeys(
            aliases.get(term, term)
            for term in value.split()
            if term not in stop and len(term) <= 300
        )
    )[:300]


def upgrade():
    op.add_column(
        "processing_jobs",
        sa.Column("model_call_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("reassessment_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("processing_jobs", sa.Column("followup_message_id", sa.String(36), nullable=True))
    op.add_column(
        "processing_jobs", sa.Column("deferred_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE processing_jobs SET model_call_count = "
        "CASE WHEN attempt_count < 2 THEN attempt_count ELSE 2 END"
    )
    op.create_table(
        "topic_search_terms",
        sa.Column(
            "topic_id",
            sa.String(36),
            sa.ForeignKey("topics.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("term", sa.String(300), primary_key=True),
        sa.Column("guild_id", sa.String(100), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
    )
    op.create_index("ix_topic_terms_guild_term", "topic_search_terms", ["guild_id", "term"])
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT t.id, t.guild_id, t.title, t.description, "
            "(SELECT s.data FROM topic_summaries s "
            "WHERE s.topic_id=t.id AND s.guild_id=t.guild_id "
            "ORDER BY s.version DESC LIMIT 1) AS summary FROM topics t"
        )
    ).mappings()
    for row in rows:
        summary = row["summary"] or {}
        if isinstance(summary, str):
            summary = json.loads(summary)
        texts = [
            (row["title"], 3.0),
            (row["description"], 1.5),
            (str(summary.get("overview", "")), 0.75),
        ]
        for field in ("proposals", "decisions", "open_questions", "action_items"):
            values = summary.get(field, [])
            if isinstance(values, list):
                texts.append(
                    (" ".join(item for item in values[:20] if isinstance(item, str)), 0.75)
                )
        weights = {}
        for value, weight in texts:
            for term in _terms(value):
                weights[term] = max(weights.get(term, 0), weight)
        if weights:
            connection.execute(
                sa.text(
                    "INSERT INTO topic_search_terms(topic_id,guild_id,term,weight) "
                    "VALUES (:topic_id,:guild_id,:term,:weight)"
                ),
                [
                    {
                        "topic_id": row["id"],
                        "guild_id": row["guild_id"],
                        "term": term,
                        "weight": weight,
                    }
                    for term, weight in weights.items()
                ],
            )


def downgrade():
    op.drop_table("topic_search_terms")
    for column in (
        "deferred_until",
        "followup_message_id",
        "reassessment_count",
        "model_call_count",
    ):
        op.drop_column("processing_jobs", column)
