"""initial schema - every table in CONTRACT.md's Data model section

Revision ID: 0001
Revises:
Create Date: 2026-09-17

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    run_status = postgresql.ENUM(
        "ingest",
        "normalize",
        "retrieve",
        "decide",
        "plan",
        "gate",
        "apply",
        "verify",
        "log",
        "respond",
        "completed",
        "failed",
        "cancelled",
        name="run_status",
    )
    proposal_status = postgresql.ENUM(
        "pending",
        "confirmed",
        "applied",
        "verified",
        "cancelled",
        "failed",
        name="proposal_status",
    )
    artifact_type = postgresql.ENUM("summary", "package", "draft", name="artifact_type")
    embedding_source_type = postgresql.ENUM(
        "jira", "doc", "decision", name="embedding_source_type"
    )

    # Each ENUM is created exactly once, the first time it's referenced by a
    # create_table column below (create_type=True is the default) -- don't
    # also call .create() explicitly here, or the type gets emitted twice.

    op.create_table(
        "agent_run",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("capability", sa.String(128), nullable=False),
        sa.Column("trigger_source", sa.String(64), nullable=False),
        sa.Column("actor_user", sa.String(255), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", run_status, nullable=False, server_default="ingest"),
        sa.Column(
            "checkpoint_json", postgresql.JSONB, nullable=False, server_default=sa.text("'{}'")
        ),
    )
    op.create_index("ix_agent_run_capability", "agent_run", ["capability"])

    op.create_table(
        "decision_call",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("state_hash", sa.String(64), nullable=False),
        sa.Column("questions_json", postgresql.JSONB, nullable=False),
        sa.Column("answers_json", postgresql.JSONB, nullable=False),
        sa.Column("logprobs_json", postgresql.JSONB, nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_decision_call_run_id", "decision_call", ["run_id"])
    op.create_index("ix_decision_call_state_hash", "decision_call", ["state_hash"])
    op.create_index(
        "ix_decision_call_cache_key", "decision_call", ["state_hash", "provider", "model_id"]
    )

    op.create_table(
        "proposal",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("target_jira_key", sa.String(32), nullable=True),
        sa.Column("diff_json", postgresql.JSONB, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("status", proposal_status, nullable=False, server_default="pending"),
        sa.Column("created_by_agent", sa.String(128), nullable=False),
        sa.Column("confirmed_by_user", sa.String(255), nullable=True),
        sa.Column("idempotency_key", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_proposal_run_id", "proposal", ["run_id"])

    op.create_table(
        "jira_change",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "proposal_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("proposal.id"),
            nullable=False,
        ),
        sa.Column("jira_key", sa.String(32), nullable=False),
        sa.Column("field", sa.String(128), nullable=False),
        sa.Column("before_json", postgresql.JSONB, nullable=True),
        sa.Column("after_json", postgresql.JSONB, nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verify_ok", sa.Boolean, nullable=True),
    )
    op.create_index("ix_jira_change_proposal_id", "jira_change", ["proposal_id"])
    op.create_index("ix_jira_change_jira_key", "jira_change", ["jira_key"])

    op.create_table(
        "artifact",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id"),
            nullable=False,
        ),
        sa.Column("type", artifact_type, nullable=False),
        sa.Column("repo_path", sa.Text, nullable=True),
        sa.Column("git_commit", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_artifact_run_id", "artifact", ["run_id"])

    op.create_table(
        "audit_event",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("agent_run.id"),
            nullable=True,
        ),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("actor", sa.String(255), nullable=False),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("prompt_ref", sa.Text, nullable=True),
        sa.Column("tool_call_json", postgresql.JSONB, nullable=True),
        sa.Column("result_ref", sa.Text, nullable=True),
        sa.Column("hash_prev", sa.String(64), nullable=True),
        sa.Column("hash_self", sa.String(64), nullable=False),
    )
    op.create_index("ix_audit_event_run_id", "audit_event", ["run_id"])

    op.create_table(
        "embedding",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("source_type", embedding_source_type, nullable=False),
        sa.Column("source_ref", sa.String(255), nullable=False),
        sa.Column("chunk", sa.Text, nullable=False),
        sa.Column("vector", Vector(768), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_embedding_source_ref", "embedding", ["source_ref"])

    op.create_table(
        "budget",
        sa.Column("component", sa.String(64), primary_key=True),
        sa.Column("metric", sa.String(64), primary_key=True),
        sa.Column("limit_value", sa.Float, nullable=False),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "margin_snapshot",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("rolled_up_value", sa.Float, nullable=False),
    )
    op.create_index("ix_margin_snapshot_ts", "margin_snapshot", ["ts"])

    op.create_table(
        "roster",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column(
            "subteams",
            postgresql.ARRAY(sa.String),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("discord_id", sa.String(64), nullable=True),
        sa.Column("slack_id", sa.String(64), nullable=True),
        sa.Column("jira_account_id", sa.String(128), nullable=True),
        sa.Column(
            "licensed_bool", sa.Boolean, nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "platform_link",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("jira_key", sa.String(32), nullable=True),
        sa.Column("discord_msg_id", sa.String(64), nullable=True),
        sa.Column("slack_ts", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "jira_key", "discord_msg_id", "slack_ts", name="uq_platform_link_triplet"
        ),
    )
    op.create_index("ix_platform_link_jira_key", "platform_link", ["jira_key"])


def downgrade() -> None:
    op.drop_table("platform_link")
    op.drop_table("roster")
    op.drop_table("margin_snapshot")
    op.drop_table("budget")
    op.drop_table("embedding")
    op.drop_table("audit_event")
    op.drop_table("artifact")
    op.drop_table("jira_change")
    op.drop_table("proposal")
    op.drop_table("decision_call")
    op.drop_table("agent_run")

    bind = op.get_bind()
    postgresql.ENUM(name="embedding_source_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="artifact_type").drop(bind, checkfirst=True)
    postgresql.ENUM(name="proposal_status").drop(bind, checkfirst=True)
    postgresql.ENUM(name="run_status").drop(bind, checkfirst=True)
