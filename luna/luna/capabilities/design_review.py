"""Capability #7 -- deliverable / design-review package assembly (spec §3.3
#7, CONTRACT.md). Read-only against requirements/risks/tests/margins/docs
data -> draft prose via `Generation.generate()` -> git commit to the docs
repo, on a feature branch, never `main` and never auto-merged (a human
opens the PR by hand -- this module never talks to a Forgejo/GitHub PR API).

**This is the one capability that must NOT call
`guardrails.require_confirmation()`.** Per that function's own docstring: it
never touches Jira, so there is nothing for that guardrail to gate, and
calling it at all (even with `jira_write=False`) deliberately raises
`NotImplementedError` to prevent a second, quieter Jira-write bypass from
ever being added. This module does not import `require_confirmation` at
all.

Inputs are accepted as plain structured data (`PackageSpec`/
`PackageSectionInput`), never by reaching into `adapters.jira`/docs-repo
internals -- CONTRACT.md's scope boundary, same convention as
`rag_qna.reindex()`.

## Per-section sufficiency gate

Before drafting prose for a section, a `NoulQuestion` asks whether the
supplied input bullets are substantial enough to write a real section from.
This mirrors `rag_qna.answer_question()`'s insufficient-retrieval gate, for
the same spec §3.6 reason: don't let `Generation.generate()` hallucinate a
full PDR/CDR section from thin input. A section that fails the gate is
rendered as a `TODO: insufficient input` placeholder instead of invented
prose. This also happens to be what makes this file's `.generate()` call
pair with a `.decide()` call in the same file, per
`tests/test_jev_conformance.py` item 6's grep-based lint.
"""

from __future__ import annotations

import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from luna.db.models import Artifact, ArtifactType
from luna.decision.engine import DecisionProvider, decide_one
from luna.decision.schemas import NoulQuestion
from luna.generation.generator import Generation
from luna.guardrails import untrusted


@dataclass
class PackageSectionInput:
    """One section's worth of structured input. `items` are plain-text
    bullets (a requirement description, a risk statement, a test result, a
    margin-vs-budget line, a doc excerpt) -- this module has no opinion on
    where they came from."""

    heading: str
    items: list[str] = field(default_factory=list)


@dataclass
class PackageSpec:
    package_kind: str  # e.g. "PDR", "CDR", "Final-Outbrief", "technical-paper"
    title: str
    sections: list[PackageSectionInput]


@dataclass
class RenderedSection:
    heading: str
    body: str
    sufficient: bool


@dataclass
class PackageDraft:
    title: str
    package_kind: str
    sections: list[RenderedSection]
    markdown: str


async def assemble_package(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    generation: Generation,
    spec: PackageSpec,
) -> PackageDraft:
    rendered = [
        await _render_section(session, run_id, provider, generation, spec.package_kind, section)
        for section in spec.sections
    ]

    lines = [f"# {spec.title}", ""]
    for r in rendered:
        lines.append(f"## {r.heading}")
        lines.append("")
        lines.append(r.body)
        lines.append("")

    return PackageDraft(
        title=spec.title,
        package_kind=spec.package_kind,
        sections=rendered,
        markdown="\n".join(lines),
    )


async def _render_section(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    generation: Generation,
    package_kind: str,
    section: PackageSectionInput,
) -> RenderedSection:
    if not section.items:
        return RenderedSection(
            heading=section.heading,
            body="_TODO: no input data supplied for this section yet._",
            sufficient=False,
        )

    combined = "\n".join(f"- {item}" for item in section.items)
    gate_answer = await decide_one(
        session,
        run_id,
        provider,
        combined,
        "section_sufficient",
        NoulQuestion(
            instructions=(
                f"The INPUT DATA below is meant to support writing the '{section.heading}' "
                f"section of a {package_kind} engineering design-review document. Is it "
                "specific and substantial enough to draft a real section from, as opposed to "
                "being too sparse, vague, or off-topic to write more than a placeholder?"
            ),
        ),
    )
    if gate_answer.noul < 0.5:  # type: ignore[union-attr]
        return RenderedSection(
            heading=section.heading,
            body=(
                f"_TODO: input data for this section was judged insufficient "
                f"(noul={gate_answer.noul:.2f}) -- needs more detail before drafting._"  # type: ignore[union-attr]
            ),
            sufficient=False,
        )

    body = await generation.generate(
        instructions=(
            f"Write the '{section.heading}' section of a {package_kind} engineering "
            "design-review document, in formal technical-report prose, based only on the "
            "input bullets below. Do not invent requirements, numbers, or test results that "
            "aren't present in the input."
        ),
        untrusted=untrusted(combined, source=f"design_review:{section.heading}"),
    )
    return RenderedSection(heading=section.heading, body=body, sufficient=True)


# --- docs-repo git commit ----------------------------------------------------


class DocsRepoError(RuntimeError):
    pass


def commit_package_to_docs_repo(
    draft: PackageDraft,
    *,
    repo_url: str,
    repo_token: str,
    clone_dir: str | Path,
    branch_name: str,
    file_path: str,
    commit_message: str,
    author_name: str = "LUNA",
    author_email: str = "luna@csun-c3.local",
    push: bool = True,
) -> str:
    """Clones (or reuses) `repo_url` at `clone_dir`, checks out a new
    branch, writes `draft.markdown` to `file_path`, commits, and (if
    `push=True`) pushes the branch -- never `main`, never a merge or PR
    creation (spec §3.3#7/§3.6: "never auto-submits", a human opens the
    PR). Returns the new commit's SHA.

    Plain `git` CLI via `subprocess`, matching CONTRACT.md's pyproject
    guidance ("plain subprocess calls to the git CLI against a local clone
    is simplest"). `repo_token` is spliced into the clone URL for HTTPS
    auth (the conventional way to use a Forgejo/GitHub token non-
    interactively); a `file://` URL (what this module's own tests use, and
    what a local bare repo needs) is left untouched.
    """
    clone_dir = Path(clone_dir)
    auth_url = _with_token(repo_url, repo_token)

    if not (clone_dir / ".git").exists():
        clone_dir.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["clone", auth_url, str(clone_dir)], cwd=clone_dir.parent)
    else:
        default_branch = _current_branch(clone_dir)
        _run_git(["fetch", "origin"], cwd=clone_dir)
        _run_git(["checkout", default_branch], cwd=clone_dir)
        _run_git(["reset", "--hard", f"origin/{default_branch}"], cwd=clone_dir)

    _run_git(["checkout", "-b", branch_name], cwd=clone_dir)

    target = clone_dir / file_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(draft.markdown, encoding="utf-8")

    _run_git(["add", file_path], cwd=clone_dir)
    _run_git(
        [
            "-c",
            f"user.name={author_name}",
            "-c",
            f"user.email={author_email}",
            "commit",
            "-m",
            commit_message,
        ],
        cwd=clone_dir,
    )
    commit_sha = _run_git(["rev-parse", "HEAD"], cwd=clone_dir).strip()

    if push:
        _run_git(["push", "-u", "origin", branch_name], cwd=clone_dir)

    return commit_sha


def _with_token(repo_url: str, token: str) -> str:
    if not token or not repo_url.startswith("https://"):
        return repo_url
    scheme, rest = repo_url.split("://", 1)
    if "@" in rest.split("/", 1)[0]:
        return repo_url  # already has credentials embedded
    return f"{scheme}://luna:{token}@{rest}"


def _current_branch(clone_dir: Path) -> str:
    return _run_git(["symbolic-ref", "--short", "HEAD"], cwd=clone_dir).strip()


def _run_git(args: list[str], *, cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise DocsRepoError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


# --- top-level orchestration --------------------------------------------------


async def generate_and_commit_package(
    session: AsyncSession,
    run_id: uuid.UUID,
    provider: DecisionProvider,
    generation: Generation,
    spec: PackageSpec,
    *,
    repo_url: str,
    repo_token: str,
    clone_dir: str | Path,
    file_path: str | None = None,
    push: bool = True,
) -> tuple[PackageDraft, Artifact]:
    """Assembles the package, commits it to the docs repo, and writes the
    `Artifact` row (`type=draft`) capability #7 is responsible for. Does not
    commit the DB session -- caller controls the transaction."""
    draft = await assemble_package(session, run_id, provider, generation, spec)

    branch = f"luna/{spec.package_kind.lower()}-{run_id}"
    path = file_path or f"packages/{spec.package_kind.lower()}-{run_id}.md"
    commit_sha = commit_package_to_docs_repo(
        draft,
        repo_url=repo_url,
        repo_token=repo_token,
        clone_dir=clone_dir,
        branch_name=branch,
        file_path=path,
        commit_message=f"Add draft {spec.package_kind} package: {spec.title}",
        push=push,
    )

    artifact = Artifact(run_id=run_id, type=ArtifactType.draft, repo_path=path, git_commit=commit_sha)
    session.add(artifact)
    await session.flush()
    return draft, artifact
