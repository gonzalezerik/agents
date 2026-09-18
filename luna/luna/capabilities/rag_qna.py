"""Capability #6 -- knowledge Q&A (RAG) with citations (spec §3.3 #6,
CONTRACT.md). Read-only.

pgvector similarity search over `Embedding` rows -> Decision Engine gates
"is retrieval sufficient to answer?" (`NoulQuestion`, spec §3.5/§3.6) ->
`Generation.generate()` synthesizes an answer **with citations**
(issue-key/page keys, never an uncited claim) only when the gate passes;
otherwise `answer_question()` returns an honest "I don't know / here's who
to ask" response instead of letting `Generation.generate()` guess from thin
context.

This module also owns embedding/reindex logic (`reindex()`): (re)embeds a
list of `{source_type, source_ref, title, text, updated_at}` records into
`Embedding` rows. Source data comes from Jira (another builder's adapter)
and a docs-repo KB (Forgejo Markdown, spec §3.2) -- `reindex()` deliberately
takes plain dicts/`ReindexSourceDoc`, never reaching into
`adapters.jira`/docs-repo internals itself, so it stays testable and
decoupled per CONTRACT.md's scope boundary.

## The embedding-endpoint finding (read before touching `embedding.vector`)

CONTRACT.md/the task brief assumed the local LLM endpoint
(`LLM_BASE_URL`) might expose a working `/v1/embeddings` route for one of
its chat models, with `EMBEDDING_MODEL` naming which one. **Verified against
the real endpoint (2026-09-18): it does not.**

```
$ curl -X POST $LLM_BASE_URL/embeddings -d '{"model":"qwen35-4b","input":"hello world"}'
{"error":{"code":501,"message":"This server does not support embeddings. Start it with `--embeddings`","type":"not_supported_error"}}
```

This is llama.cpp's server refusing outright -- the llama-swap instance
backing `LLM_BASE_URL` was not started with `--embeddings`, and none of the
11 models listed at `GET /v1/models` are exposed as embedding-capable. This
is a real, checked finding, not an assumption: **there is no usable
embedding model at `LLM_BASE_URL` today.**

**Fallback chosen: `sentence-transformers/all-mpnet-base-v2`, run
in-process on CPU.** This produces **768-dimensional** vectors --
deliberately chosen to exactly match `Embedding.vector`'s fixed
`Vector(768)` column (CONTRACT.md: "768 dims to match the local embedding
model; fixed, changing it needs a full migration+reindex, don't casually
alter"), so **no schema migration is needed**. The smaller, faster
`all-MiniLM-L6-v2` (384-dim) was deliberately *not* chosen even though it's
lighter, because it would silently break `Embedding.vector`'s dimension and
require a schema-breaking migration+reindex -- exactly what the task brief
said to flag loudly rather than paper over. Tradeoff being documented
honestly: `all-mpnet-base-v2` is a ~420MB model and noticeably slower than
MiniLM (CPU-only, no local GPU assumed here), which matters for reindex
throughput on a large Jira/docs corpus but not for the read-time
per-question embedding this module also does (one query embedding per
`answer_question()` call). If a real embedding-capable model ever becomes
available at `LLM_BASE_URL` (llama-swap restarted with `--embeddings` and a
768-dim-compatible model), swapping `_get_embedding_model()`'s
implementation for an HTTP call is a contained change -- every caller in
this file goes through `embed_texts()`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from luna.db.models import Embedding, EmbeddingSourceType
from luna.decision.engine import DecisionProvider, decide_one
from luna.decision.schemas import NoulQuestion
from luna.generation.generator import Generation
from luna.guardrails import untrusted

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

_EMBEDDING_MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
EMBEDDING_DIM = 768  # must match db.models.Embedding.vector's Vector(768)

_CHUNK_MAX_CHARS = 1500
_CHUNK_OVERLAP_CHARS = 200

_model_singleton: SentenceTransformer | None = None


def _get_embedding_model() -> SentenceTransformer:
    global _model_singleton
    if _model_singleton is None:
        from sentence_transformers import SentenceTransformer

        _model_singleton = SentenceTransformer(_EMBEDDING_MODEL_NAME, device="cpu")
    return _model_singleton


def embed_texts(texts: list[str]) -> list[list[float]]:
    """The one embedding function every caller in this file goes through.
    See module docstring for why this is a local `sentence-transformers`
    model rather than an HTTP call to `LLM_BASE_URL`."""
    if not texts:
        return []
    model = _get_embedding_model()
    vectors = model.encode(list(texts), normalize_embeddings=True)
    return [v.tolist() for v in vectors]


def _chunk_text(text: str, *, max_chars: int = _CHUNK_MAX_CHARS, overlap: int = _CHUNK_OVERLAP_CHARS) -> list[str]:
    """Simple fixed-size character chunking with overlap. Good enough for
    v1 -- requirements/decisions/meeting-notes/ICDs/test-plans/risks are
    generally short enough that most documents are 1-3 chunks; a smarter
    (sentence/paragraph-aware) splitter is a reasonable future improvement,
    not required for the read path (`answer_question`) to be correct."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


# --- reindex -----------------------------------------------------------------


@dataclass
class ReindexSourceDoc:
    source_type: str  # "jira" | "doc" | "decision" -- EmbeddingSourceType values
    source_ref: str
    title: str
    text: str
    updated_at: datetime


async def reindex(session: AsyncSession, docs: list[ReindexSourceDoc | dict]) -> int:
    """(Re)embeds `docs` into `embedding` rows. For each doc: deletes any
    existing rows sharing its `source_ref` (a doc that changed length gets a
    different chunk count, so "delete and re-insert" is the simplest
    correct behavior rather than trying to diff chunks), chunks
    `title + text`, embeds every chunk, and inserts one `Embedding` row per
    chunk. Returns the total number of rows written. Does not commit --
    caller controls the transaction, same convention as `decide_many`."""
    total = 0
    for raw in docs:
        doc = raw if isinstance(raw, ReindexSourceDoc) else ReindexSourceDoc(**raw)
        await session.execute(delete(Embedding).where(Embedding.source_ref == doc.source_ref))

        full_text = f"{doc.title}\n\n{doc.text}" if doc.title else doc.text
        chunks = _chunk_text(full_text)
        if not chunks:
            continue

        vectors = embed_texts(chunks)
        source_type = EmbeddingSourceType(doc.source_type)
        for chunk, vector in zip(chunks, vectors, strict=True):
            session.add(
                Embedding(
                    source_type=source_type,
                    source_ref=doc.source_ref,
                    chunk=chunk,
                    vector=vector,
                )
            )
            total += 1

    await session.flush()
    return total


# --- retrieval + synthesis ----------------------------------------------------


@dataclass
class RetrievedChunk:
    source_type: EmbeddingSourceType
    source_ref: str
    chunk: str
    distance: float


@dataclass
class RagAnswer:
    answer: str
    citations: list[str]
    sufficient: bool
    insufficient_reason: str | None = None


DEFAULT_K = 6


async def similarity_search(session: AsyncSession, query: str, *, k: int = DEFAULT_K) -> list[RetrievedChunk]:
    query_vector = embed_texts([query])[0]
    distance = Embedding.vector.cosine_distance(query_vector).label("distance")
    stmt = select(Embedding, distance).order_by(distance).limit(k)
    rows = (await session.execute(stmt)).all()
    return [
        RetrievedChunk(
            source_type=row.Embedding.source_type,
            source_ref=row.Embedding.source_ref,
            chunk=row.Embedding.chunk,
            distance=float(row.distance),
        )
        for row in rows
    ]


async def answer_question(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    generation: Generation,
    question: str,
    *,
    k: int = DEFAULT_K,
) -> RagAnswer:
    hits = await similarity_search(session, question, k=k)
    if not hits:
        return RagAnswer(
            answer=(
                "I don't know -- nothing is indexed yet that relates to this question. "
                "Try asking a subteam lead, or check Jira/the docs repo directly."
            ),
            citations=[],
            sufficient=False,
            insufficient_reason="no retrieval hits",
        )

    retrieval_state = {
        "question": question,
        "retrieved_context": [
            {"citation": h.source_ref, "excerpt": h.chunk[:800]} for h in hits
        ],
    }
    gate_answer = await decide_one(
        session,
        run_id,
        provider,
        retrieval_state,
        "retrieval_sufficient",
        NoulQuestion(
            instructions=(
                "Given the QUESTION and the RETRIEVED CONTEXT excerpts below (each labeled "
                "with a citation key from the project's Jira issues and docs), is the "
                "retrieved context sufficient to answer the QUESTION accurately and "
                "specifically -- without guessing or relying on outside knowledge? Answer "
                "false if the context is off-topic, too thin, or only tangentially related."
            ),
        ),
    )

    if gate_answer.noul < 0.5:  # type: ignore[union-attr]
        return RagAnswer(
            answer=(
                "I don't have enough indexed information to answer that confidently. "
                f"Closest related material: {', '.join(h.source_ref for h in hits[:3])}. "
                "Consider asking a subteam lead or checking Jira/the docs repo directly."
            ),
            citations=[h.source_ref for h in hits[:3]],
            sufficient=False,
            insufficient_reason=f"retrieval-sufficiency gate noul={gate_answer.noul:.3f}",  # type: ignore[union-attr]
        )

    untrusted_blocks = [untrusted(h.chunk, source=h.source_ref) for h in hits]
    answer_text = await generation.generate(
        instructions=(
            "Answer the QUESTION below using ONLY the retrieved UNTRUSTED CONTENT blocks. "
            "Cite every factual claim inline with its bracketed source key exactly as given "
            "(e.g. [C3-142] or [docs/pdr.md]). If the content doesn't actually support a "
            f"claim, don't make it.\n\nQUESTION: {question}"
        ),
        untrusted=untrusted_blocks,
    )
    return RagAnswer(answer=answer_text, citations=[h.source_ref for h in hits], sufficient=True)
