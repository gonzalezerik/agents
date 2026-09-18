"""Tests for `luna.capabilities.rag_qna`.

`embed_texts()` uses a real `sentence-transformers` model (see
`rag_qna.py`'s module docstring for why: the local LLM endpoint has no
working `/v1/embeddings` route, verified for real). The first call in a
test run downloads/loads that model, which is slow-ish (~15s observed
here) but not marked `@pytest.mark.llm` -- it needs no live LLM endpoint
and no network beyond the one-time Hugging Face download, matching
`faster-whisper`'s treatment in `test_transcript_adapter.py`. Tests that
also need Postgres+pgvector use the shared `db_session` fixture and skip
automatically if it's unreachable (`conftest.py`).

The one `@pytest.mark.llm` test is the important one CONTRACT.md/the task
brief calls out by name: verifying, for real against the live endpoint,
that thin/irrelevant retrieval makes `answer_question()` say "I don't know"
instead of letting `Generation.generate()` guess.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from luna.capabilities.rag_qna import (
    EMBEDDING_DIM,
    ReindexSourceDoc,
    answer_question,
    embed_texts,
    reindex,
    similarity_search,
)
from luna.db.models import AgentRun, RunStatus
from luna.decision.engine import get_decision_provider
from luna.generation.generator import Generation


def test_embed_texts_produces_768_dim_vectors_matching_schema() -> None:
    vectors = embed_texts(["hello world", "the rover excavation subteam"])
    assert len(vectors) == 2
    for v in vectors:
        assert len(v) == EMBEDDING_DIM  # must match db.models.Embedding.vector's Vector(768)


def test_embed_texts_empty_input_returns_empty_list() -> None:
    assert embed_texts([]) == []


async def test_reindex_and_similarity_search_roundtrip(db_session) -> None:
    docs = [
        ReindexSourceDoc(
            source_type="jira",
            source_ref="C3-142",
            title="Chassis wiring harness",
            text=(
                "The chassis subteam finished routing the main wiring harness through the "
                "frame this week. Remaining work: strain relief at the motor controller."
            ),
            updated_at=datetime.now(UTC),
        ),
        ReindexSourceDoc(
            source_type="doc",
            source_ref="docs/power-budget.md",
            title="Power budget",
            text=(
                "The power budget currently allocates 45W to the excavation subsystem and "
                "30W to the processing subsystem, against a 120W total mission budget."
            ),
            updated_at=datetime.now(UTC),
        ),
    ]

    written = await reindex(db_session, docs)
    assert written >= 2
    await db_session.commit()

    hits = await similarity_search(db_session, "how much power does excavation use?", k=3)
    assert hits
    assert any(h.source_ref == "docs/power-budget.md" for h in hits)


async def test_reindex_is_idempotent_per_source_ref(db_session) -> None:
    doc = ReindexSourceDoc(
        source_type="doc",
        source_ref="docs/dup-test.md",
        title="Dup test",
        text="short doc body",
        updated_at=datetime.now(UTC),
    )
    first = await reindex(db_session, [doc])
    second = await reindex(db_session, [doc])
    await db_session.commit()

    hits = await similarity_search(db_session, "short doc body", k=10)
    matching = [h for h in hits if h.source_ref == "docs/dup-test.md"]
    # re-embedding the same source_ref replaces, not appends
    assert len(matching) == first == second


async def test_answer_question_with_no_index_says_i_dont_know(db_session) -> None:
    class _StubProvider:
        provider_name = "stub"
        model_id = "stub"

        async def decide(self, state, questions):  # pragma: no cover - should never be called
            raise AssertionError("decide() should not be called when there are zero retrieval hits")

    class _StubGeneration:
        async def generate(self, **kwargs):  # pragma: no cover
            raise AssertionError("generate() should not be called when there are zero retrieval hits")

    run = AgentRun(capability="rag_qna", trigger_source="test", status=RunStatus.decide)
    db_session.add(run)
    await db_session.flush()

    result = await answer_question(
        db_session, run.id, _StubProvider(), _StubGeneration(), "what is the meaning of life?"
    )
    assert result.sufficient is False
    assert "don't know" in result.answer.lower()
    assert result.citations == []


@pytest.mark.llm
async def test_answer_question_insufficient_retrieval_says_i_dont_know_live(db_session) -> None:
    """The genuinely important behavior CONTRACT.md/the task brief calls
    out: index something narrow and unrelated, ask an off-topic question,
    and verify the live Decision Engine gate + Generation path actually
    produces an honest "I don't know" rather than a hallucinated answer."""
    doc = ReindexSourceDoc(
        source_type="doc",
        source_ref="docs/unrelated-topic.md",
        title="Coffee machine maintenance",
        text=(
            "The team room coffee machine's water filter should be replaced every 60 days. "
            "Descale monthly with a 1:4 vinegar-water solution."
        ),
        updated_at=datetime.now(UTC),
    )
    await reindex(db_session, [doc])
    await db_session.commit()

    run = AgentRun(capability="rag_qna", trigger_source="test", status=RunStatus.decide)
    db_session.add(run)
    await db_session.flush()

    provider = get_decision_provider()
    generation = Generation.from_settings()
    try:
        result = await answer_question(
            db_session,
            run.id,
            provider,
            generation,
            "What is the rover's maximum excavation depth requirement per REQ-EXC-014?",
        )
    finally:
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()
        await generation.aclose()

    assert result.sufficient is False
    assert "don't" in result.answer.lower() or "enough" in result.answer.lower()


async def test_answer_question_sufficient_retrieval_includes_citation(db_session) -> None:
    """Mocked (no live LLM): a stub provider that always answers the gate
    'true' and a stub generation that echoes citations, verifying the
    plumbing between retrieval -> gate -> generate -> citations without
    depending on the real model's judgment."""
    from luna.decision.schemas import NoulAnswer

    class _AlwaysSufficientProvider:
        provider_name = "stub"
        model_id = "stub"

        async def decide(self, state, questions):
            return {qid: NoulAnswer(noul=1.0) for qid in questions}

    class _EchoGeneration:
        async def generate(self, *, instructions, untrusted=None, **kwargs):
            blocks = untrusted if isinstance(untrusted, list) else ([untrusted] if untrusted else [])
            return " ".join(f"[{b.source}]" for b in blocks)

    doc = ReindexSourceDoc(
        source_type="jira",
        source_ref="C3-999",
        title="Test requirement",
        text="This is a specific, indexed requirement about excavation depth.",
        updated_at=datetime.now(UTC),
    )
    await reindex(db_session, [doc])
    await db_session.commit()

    run = AgentRun(capability="rag_qna", trigger_source="test", status=RunStatus.decide)
    db_session.add(run)
    await db_session.flush()

    result = await answer_question(
        db_session, run.id, _AlwaysSufficientProvider(), _EchoGeneration(), "excavation depth?"
    )
    assert result.sufficient is True
    assert "C3-999" in result.answer
    assert "C3-999" in result.citations
