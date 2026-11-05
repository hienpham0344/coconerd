"""Create initial conversation organizer schema."""

# ruff: noqa: E501

from alembic import op

revision = "20261103_0001"
down_revision = None
branch_labels = None
depends_on = None


def _execute(statement: str) -> None:
    # Keep the frozen SQLite DDL; translate its timestamp type for PostgreSQL.
    if op.get_context().dialect.name == "postgresql":
        statement = statement.replace("DATETIME", "TIMESTAMP WITH TIME ZONE")
    op.execute(statement)


def upgrade() -> None:
    _execute(
        "\nCREATE TABLE api_rate_limits (\n\tclient_fingerprint VARCHAR(64) NOT NULL, \n\twindow_start DATETIME NOT NULL, \n\trequest_count INTEGER NOT NULL, \n\tPRIMARY KEY (client_fingerprint, window_start)\n)\n\n"
    )
    _execute(
        "\nCREATE TABLE guild_settings (\n\tguild_id VARCHAR(100) NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tallowed_channel_ids JSON NOT NULL, \n\tretention_days INTEGER NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (guild_id)\n)\n\n"
    )
    _execute(
        "\nCREATE TABLE messages (\n\tid VARCHAR(36) NOT NULL, \n\tguild_id VARCHAR(100) NOT NULL, \n\tchannel_id VARCHAR(100) NOT NULL, \n\tdiscord_message_id VARCHAR(100) NOT NULL, \n\tauthor_id VARCHAR(100) NOT NULL, \n\tauthor_name VARCHAR(200) NOT NULL, \n\tcontent TEXT NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\treply_to_message_id VARCHAR(100), \n\tingested_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_message_guild_discord_id UNIQUE (guild_id, discord_message_id)\n)\n\n"
    )
    _execute(
        "CREATE INDEX ix_messages_guild_author_created ON messages (guild_id, author_id, created_at)"
    )
    _execute(
        "CREATE INDEX ix_messages_guild_channel_created ON messages (guild_id, channel_id, created_at)"
    )
    _execute("CREATE INDEX ix_messages_guild_id ON messages (guild_id)")
    _execute(
        "\nCREATE TABLE model_configs (\n\tid VARCHAR(36) NOT NULL, \n\tscope VARCHAR(20) NOT NULL, \n\tguild_id VARCHAR(100), \n\tprovider VARCHAR(100) NOT NULL, \n\tmodel_id VARCHAR(200) NOT NULL, \n\ttemperature FLOAT NOT NULL, \n\tmax_tokens INTEGER NOT NULL, \n\tenabled BOOLEAN NOT NULL, \n\tupdated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id)\n)\n\n"
    )
    _execute("CREATE INDEX ix_model_configs_guild_id ON model_configs (guild_id)")
    _execute(
        "CREATE UNIQUE INDEX uq_model_configs_global ON model_configs (scope) WHERE guild_id IS NULL"
    )
    _execute(
        "CREATE UNIQUE INDEX uq_model_configs_guild ON model_configs (scope, guild_id) WHERE guild_id IS NOT NULL"
    )
    _execute(
        "\nCREATE TABLE topics (\n\tid VARCHAR(36) NOT NULL, \n\tguild_id VARCHAR(100) NOT NULL, \n\ttitle VARCHAR(300) NOT NULL, \n\tdescription TEXT NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tdiscord_thread_id VARCHAR(100), \n\tcreated_at DATETIME NOT NULL, \n\tlast_activity_at DATETIME NOT NULL, \n\tversion INTEGER NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (discord_thread_id)\n)\n\n"
    )
    _execute("CREATE INDEX ix_topics_guild_id ON topics (guild_id)")
    _execute(
        "CREATE INDEX ix_topics_guild_status_activity ON topics (guild_id, status, last_activity_at)"
    )
    _execute(
        "\nCREATE TABLE worker_heartbeats (\n\tworker_id VARCHAR(100) NOT NULL, \n\tstatus VARCHAR(30) NOT NULL, \n\tlast_seen_at DATETIME NOT NULL, \n\tPRIMARY KEY (worker_id)\n)\n\n"
    )
    _execute(
        "\nCREATE TABLE ai_decisions (\n\tid VARCHAR(36) NOT NULL, \n\tguild_id VARCHAR(100) NOT NULL, \n\tmessage_record_id VARCHAR(36) NOT NULL, \n\tdecision_type VARCHAR(40) NOT NULL, \n\tmodel_id VARCHAR(200) NOT NULL, \n\tpayload JSON NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(message_record_id) REFERENCES messages (id) ON DELETE CASCADE\n)\n\n"
    )
    _execute("CREATE INDEX ix_ai_decisions_guild_id ON ai_decisions (guild_id)")
    _execute(
        "\nCREATE TABLE conversation_episodes (\n\tid VARCHAR(36) NOT NULL, \n\tguild_id VARCHAR(100) NOT NULL, \n\ttopic_id VARCHAR(36) NOT NULL, \n\tstarted_at DATETIME NOT NULL, \n\tended_at DATETIME, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(topic_id) REFERENCES topics (id) ON DELETE CASCADE\n)\n\n"
    )
    _execute("CREATE INDEX ix_conversation_episodes_guild_id ON conversation_episodes (guild_id)")
    _execute(
        "CREATE INDEX ix_episodes_guild_topic_started ON conversation_episodes (guild_id, topic_id, started_at)"
    )
    _execute(
        "\nCREATE TABLE discord_actions (\n\tid VARCHAR(36) NOT NULL, \n\tguild_id VARCHAR(100) NOT NULL, \n\tchannel_id VARCHAR(100) NOT NULL, \n\ttopic_id VARCHAR(36) NOT NULL, \n\taction_type VARCHAR(40) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tpayload JSON NOT NULL, \n\tdependency_id VARCHAR(36), \n\tattempt_count INTEGER NOT NULL, \n\tmax_attempts INTEGER NOT NULL, \n\tlease_owner VARCHAR(100), \n\tlease_expires_at DATETIME, \n\tavailable_at DATETIME NOT NULL, \n\terror_type VARCHAR(100), \n\terror_message TEXT, \n\tdiscord_thread_id VARCHAR(100), \n\tdiscord_message_id VARCHAR(100), \n\tcreated_at DATETIME NOT NULL, \n\tcompleted_at DATETIME, \n\tPRIMARY KEY (id), \n\tFOREIGN KEY(topic_id) REFERENCES topics (id) ON DELETE CASCADE, \n\tFOREIGN KEY(dependency_id) REFERENCES discord_actions (id) ON DELETE CASCADE\n)\n\n"
    )
    _execute("CREATE INDEX ix_actions_lease ON discord_actions (status, lease_expires_at)")
    _execute("CREATE INDEX ix_actions_status_created ON discord_actions (status, created_at)")
    _execute("CREATE INDEX ix_discord_actions_guild_id ON discord_actions (guild_id)")
    _execute(
        "\nCREATE TABLE message_topic_associations (\n\tid VARCHAR(36) NOT NULL, \n\tguild_id VARCHAR(100) NOT NULL, \n\tmessage_record_id VARCHAR(36) NOT NULL, \n\ttopic_id VARCHAR(36), \n\tkind VARCHAR(30) NOT NULL, \n\tconfidence FLOAT NOT NULL, \n\treason TEXT NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_message_association_guild_message UNIQUE (guild_id, message_record_id), \n\tFOREIGN KEY(message_record_id) REFERENCES messages (id) ON DELETE CASCADE, \n\tFOREIGN KEY(topic_id) REFERENCES topics (id) ON DELETE CASCADE\n)\n\n"
    )
    _execute(
        "CREATE INDEX ix_associations_guild_topic ON message_topic_associations (guild_id, topic_id)"
    )
    _execute(
        "CREATE INDEX ix_message_topic_associations_guild_id ON message_topic_associations (guild_id)"
    )
    _execute(
        "\nCREATE TABLE processing_jobs (\n\tid VARCHAR(36) NOT NULL, \n\tguild_id VARCHAR(100) NOT NULL, \n\tmessage_record_id VARCHAR(36) NOT NULL, \n\tstatus VARCHAR(20) NOT NULL, \n\tattempt_count INTEGER NOT NULL, \n\tmax_attempts INTEGER NOT NULL, \n\tlease_owner VARCHAR(100), \n\tlease_expires_at DATETIME, \n\tavailable_at DATETIME NOT NULL, \n\terror_type VARCHAR(100), \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tUNIQUE (message_record_id), \n\tFOREIGN KEY(message_record_id) REFERENCES messages (id) ON DELETE CASCADE\n)\n\n"
    )
    _execute("CREATE INDEX ix_jobs_status_available ON processing_jobs (status, available_at)")
    _execute("CREATE INDEX ix_processing_jobs_guild_id ON processing_jobs (guild_id)")
    _execute(
        "\nCREATE TABLE topic_summaries (\n\tid VARCHAR(36) NOT NULL, \n\tguild_id VARCHAR(100) NOT NULL, \n\ttopic_id VARCHAR(36) NOT NULL, \n\tversion INTEGER NOT NULL, \n\tdata JSON NOT NULL, \n\tsource_message_ids JSON NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_summary_version UNIQUE (guild_id, topic_id, version), \n\tFOREIGN KEY(topic_id) REFERENCES topics (id) ON DELETE CASCADE\n)\n\n"
    )
    _execute("CREATE INDEX ix_topic_summaries_guild_id ON topic_summaries (guild_id)")


def downgrade() -> None:
    op.drop_table("topic_summaries")
    op.drop_table("processing_jobs")
    op.drop_table("message_topic_associations")
    op.drop_table("discord_actions")
    op.drop_table("conversation_episodes")
    op.drop_table("ai_decisions")
    op.drop_table("worker_heartbeats")
    op.drop_table("topics")
    op.drop_table("model_configs")
    op.drop_table("messages")
    op.drop_table("guild_settings")
    op.drop_table("api_rate_limits")
