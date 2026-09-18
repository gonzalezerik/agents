"""SQLAlchemy 2.0 async declarative models for every table in CONTRACT.md's
"Data model" section (spec §3.5).

Primary keys: UUID for everything except `audit_event.id`, which is a
monotonic bigserial (the hash chain needs strict, gap-aware ordering that a
random UUID can't give you). CONTRACT.md says "UUIDv7 (or plain UUID4 if the
library isn't handy -- note the choice)": this project's approved dependency
list (pyproject.toml, fixed by CONTRACT.md's owning task) does not include a
uuid7 library, so we use stdlib `uuid.uuid4`. Noted in NOTES.md.

Timestamp columns: CONTRACT.md says "every table gets created_at/updated_at
unless already listed with its own timestamp columns" in the Data model
section. Applied literally: tables that already list a timestamp column
(agent_run: started_at/ended_at; decision_call/artifact: created_at;
jira_change: applied_at; audit_event: ts; margin_snapshot: ts; budget:
updated_at; embedding: updated_at) get exactly the listed columns and no
extra generic pair. Tables listing no timestamp column at all (proposal,
roster, platform_link) get created_at+updated_at added.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class ProposalStatus(enum.StrEnum):
    pending = "pending"
    confirmed = "confirmed"
    applied = "applied"
    verified = "verified"
    cancelled = "cancelled"
    failed = "failed"


class ArtifactType(enum.StrEnum):
    summary = "summary"
    package = "package"
    draft = "draft"


class EmbeddingSourceType(enum.StrEnum):
    jira = "jira"
    doc = "doc"
    decision = "decision"


class RunStatus(enum.StrEnum):
    """agent_run.status -- control_loop.py node names plus terminal states.

    Not spelled out as an enum in CONTRACT.md's Data model section (the
    column is just `status`), but control_loop.py (spec §3.4) needs a closed
    set of node names to drive its state machine and to know which runs are
    "non-terminal" and eligible for `resume()`. Shared here so both modules
    import the same source of truth instead of duplicating string literals.
    """

    ingest = "ingest"
    normalize = "normalize"
    retrieve = "retrieve"
    decide = "decide"
    plan = "plan"
    gate = "gate"
    apply = "apply"
    verify = "verify"
    log = "log"
    respond = "respond"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


NON_TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.ingest,
        RunStatus.normalize,
        RunStatus.retrieve,
        RunStatus.decide,
        RunStatus.plan,
        RunStatus.gate,
        RunStatus.apply,
        RunStatus.verify,
        RunStatus.log,
        RunStatus.respond,
    }
)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class AgentRun(Base):
    __tablename__ = "agent_run"

    id: Mapped[uuid.UUID] = _uuid_pk()
    capability: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    trigger_source: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[RunStatus] = mapped_column(
        SAEnum(RunStatus, name="run_status"), nullable=False, default=RunStatus.ingest
    )
    checkpoint_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    decision_calls: Mapped[list[DecisionCall]] = relationship(back_populates="run")
    proposals: Mapped[list[Proposal]] = relationship(back_populates="run")
    artifacts: Mapped[list[Artifact]] = relationship(back_populates="run")
    audit_events: Mapped[list[AuditEvent]] = relationship(back_populates="run")


class DecisionCall(Base):
    __tablename__ = "decision_call"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_run.id"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    questions_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    answers_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    logprobs_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[AgentRun] = relationship(back_populates="decision_calls")

    __table_args__ = (
        Index(
            "ix_decision_call_cache_key",
            "state_hash",
            "provider",
            "model_id",
        ),
    )


class Proposal(Base, TimestampMixin):
    __tablename__ = "proposal"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_run.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    target_jira_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    diff_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[ProposalStatus] = mapped_column(
        SAEnum(ProposalStatus, name="proposal_status"),
        nullable=False,
        default=ProposalStatus.pending,
    )
    created_by_agent: Mapped[str] = mapped_column(String(128), nullable=False)
    confirmed_by_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    run: Mapped[AgentRun] = relationship(back_populates="proposals")
    jira_changes: Mapped[list[JiraChange]] = relationship(back_populates="proposal")


class JiraChange(Base):
    __tablename__ = "jira_change"

    id: Mapped[uuid.UUID] = _uuid_pk()
    proposal_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("proposal.id"), nullable=False, index=True
    )
    jira_key: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(128), nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verify_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    proposal: Mapped[Proposal] = relationship(back_populates="jira_changes")


class Artifact(Base):
    __tablename__ = "artifact"

    id: Mapped[uuid.UUID] = _uuid_pk()
    run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_run.id"), nullable=False, index=True
    )
    type: Mapped[ArtifactType] = mapped_column(
        SAEnum(ArtifactType, name="artifact_type"), nullable=False
    )
    repo_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    git_commit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[AgentRun] = relationship(back_populates="artifacts")


class AuditEvent(Base):
    """Hash-chained audit log. See luna/audit.py for the writer/verifier.

    `id` is a plain autoincrement bigserial (not UUID) so the chain has a
    strict, gapless-enough total order to walk deterministically -- a random
    UUID primary key would not let us cheaply answer "what's the previous
    row" without a secondary ordering column, and hash-chaining depends on an
    unambiguous predecessor.
    """

    __tablename__ = "audit_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("agent_run.id"), nullable=True, index=True
    )
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_call_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    hash_prev: Mapped[str | None] = mapped_column(String(64), nullable=True)
    hash_self: Mapped[str] = mapped_column(String(64), nullable=False)

    run: Mapped[AgentRun | None] = relationship(back_populates="audit_events")


class Embedding(Base):
    __tablename__ = "embedding"

    id: Mapped[uuid.UUID] = _uuid_pk()
    source_type: Mapped[EmbeddingSourceType] = mapped_column(
        SAEnum(EmbeddingSourceType, name="embedding_source_type"), nullable=False
    )
    source_ref: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chunk: Mapped[str] = mapped_column(Text, nullable=False)
    # 768 dims to match the local embedding model; fixed -- changing it needs
    # a full migration + reindex, don't casually alter (CONTRACT.md).
    vector: Mapped[list[float]] = mapped_column(Vector(768), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Budget(Base):
    __tablename__ = "budget"

    component: Mapped[str] = mapped_column(String(64), primary_key=True)
    metric: Mapped[str] = mapped_column(String(64), primary_key=True)
    limit_value: Mapped[float] = mapped_column(Float, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class MarginSnapshot(Base):
    __tablename__ = "margin_snapshot"

    id: Mapped[uuid.UUID] = _uuid_pk()
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    component: Mapped[str] = mapped_column(String(64), nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    rolled_up_value: Mapped[float] = mapped_column(Float, nullable=False)


class Roster(Base, TimestampMixin):
    __tablename__ = "roster"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    subteams: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    discord_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slack_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    jira_account_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    licensed_bool: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PlatformLink(Base, TimestampMixin):
    __tablename__ = "platform_link"

    id: Mapped[uuid.UUID] = _uuid_pk()
    jira_key: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    discord_msg_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    slack_ts: Mapped[str | None] = mapped_column(String(64), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "jira_key", "discord_msg_id", "slack_ts", name="uq_platform_link_triplet"
        ),
    )

