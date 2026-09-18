"""Tests for `luna.capabilities.design_review`.

The git-commit machinery (`commit_package_to_docs_repo`) is tested against a
real local bare git repository (created via `git init --bare` in a tmp
dir) -- no network, no real Forgejo -- proving the actual `subprocess` git
flow (clone/branch/commit/push) works end-to-end, not just that the
function was called with the right arguments.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from luna.capabilities.design_review import (
    DocsRepoError,
    PackageDraft,
    PackageSectionInput,
    PackageSpec,
    RenderedSection,
    _with_token,
    assemble_package,
    commit_package_to_docs_repo,
    generate_and_commit_package,
)
from luna.db.models import AgentRun, ArtifactType, RunStatus
from luna.decision.schemas import NoulAnswer


class _StubProvider:
    provider_name = "stub"
    model_id = "stub"

    def __init__(self, *, sufficient: bool = True) -> None:
        self.sufficient = sufficient

    async def decide(self, state, questions):
        return {"section_sufficient": NoulAnswer(noul=1.0 if self.sufficient else 0.0)}


class _EchoGeneration:
    async def generate(self, *, instructions, untrusted=None, **kwargs):
        return f"DRAFTED PROSE FOR: {untrusted.value[:40]}"  # type: ignore[union-attr]


# --- assemble_package (no git, no network) ----------------------------------


async def test_section_with_no_items_becomes_todo_placeholder(db_session) -> None:
    run = AgentRun(capability="design_review", trigger_source="test", status=RunStatus.decide)
    db_session.add(run)
    await db_session.flush()

    spec = PackageSpec(
        package_kind="PDR",
        title="Test PDR",
        sections=[PackageSectionInput(heading="Requirements", items=[])],
    )
    draft = await assemble_package(db_session, run.id, _StubProvider(), _EchoGeneration(), spec)
    assert draft.sections[0].sufficient is False
    assert "TODO" in draft.sections[0].body


async def test_section_failing_sufficiency_gate_becomes_todo_placeholder(db_session) -> None:
    run = AgentRun(capability="design_review", trigger_source="test", status=RunStatus.decide)
    db_session.add(run)
    await db_session.flush()

    spec = PackageSpec(
        package_kind="PDR",
        title="Test PDR",
        sections=[PackageSectionInput(heading="Risks", items=["vague note"])],
    )
    draft = await assemble_package(
        db_session, run.id, _StubProvider(sufficient=False), _EchoGeneration(), spec
    )
    assert draft.sections[0].sufficient is False
    assert "insufficient" in draft.sections[0].body.lower()


async def test_section_passing_gate_gets_generated_prose(db_session) -> None:
    run = AgentRun(capability="design_review", trigger_source="test", status=RunStatus.decide)
    db_session.add(run)
    await db_session.flush()

    spec = PackageSpec(
        package_kind="CDR",
        title="Test CDR",
        sections=[
            PackageSectionInput(
                heading="Test Results",
                items=["REQ-EXC-014 verified via demonstration on 2026-09-01"],
            )
        ],
    )
    draft = await assemble_package(db_session, run.id, _StubProvider(sufficient=True), _EchoGeneration(), spec)
    assert draft.sections[0].sufficient is True
    assert "DRAFTED PROSE" in draft.sections[0].body
    assert "# Test CDR" in draft.markdown
    assert "## Test Results" in draft.markdown


# --- git commit flow, against a real local bare repo -------------------------


@pytest.fixture
def bare_repo(tmp_path: Path) -> Path:
    bare = tmp_path / "docs-repo.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(bare)], check=True, capture_output=True)

    seed_clone = tmp_path / "seed-clone"
    subprocess.run(["git", "clone", str(bare), str(seed_clone)], check=True, capture_output=True)
    (seed_clone / "README.md").write_text("# Docs repo\n")
    subprocess.run(["git", "add", "README.md"], cwd=seed_clone, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.name=seed", "-c", "user.email=seed@test.local", "commit", "-m", "seed"],
        cwd=seed_clone,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push", "origin", "main"], cwd=seed_clone, check=True, capture_output=True)
    return bare


def test_with_token_splices_https_url() -> None:
    assert _with_token("https://forgejo.local/c3/docs.git", "tok123") == (
        "https://luna:tok123@forgejo.local/c3/docs.git"
    )


def test_with_token_leaves_file_url_untouched() -> None:
    assert _with_token("file:///tmp/repo.git", "tok123") == "file:///tmp/repo.git"


def test_with_token_leaves_already_authed_url_untouched() -> None:
    url = "https://someone:existing@forgejo.local/c3/docs.git"
    assert _with_token(url, "tok123") == url


def test_commit_package_to_docs_repo_clones_commits_and_pushes(bare_repo: Path, tmp_path: Path) -> None:
    draft = PackageDraft(
        title="Test PDR",
        package_kind="PDR",
        sections=[RenderedSection(heading="Overview", body="body text", sufficient=True)],
        markdown="# Test PDR\n\n## Overview\n\nbody text\n",
    )
    clone_dir = tmp_path / "luna-clone"

    commit_sha = commit_package_to_docs_repo(
        draft,
        repo_url=f"file://{bare_repo}",
        repo_token="",
        clone_dir=clone_dir,
        branch_name="luna/pdr-test",
        file_path="packages/pdr-test.md",
        commit_message="Add draft PDR package",
        push=True,
    )
    assert len(commit_sha) == 40

    # Verify the branch actually landed on the "remote" (the bare repo).
    result = subprocess.run(
        ["git", "branch", "-a"], cwd=bare_repo, capture_output=True, text=True, check=True
    )
    assert "luna/pdr-test" in result.stdout

    written = clone_dir / "packages" / "pdr-test.md"
    assert written.exists()
    assert "body text" in written.read_text()


def test_commit_package_to_docs_repo_raises_docs_repo_error_on_git_failure(tmp_path: Path) -> None:
    draft = PackageDraft(title="x", package_kind="PDR", sections=[], markdown="# x\n")
    with pytest.raises(DocsRepoError):
        commit_package_to_docs_repo(
            draft,
            repo_url="file:///nonexistent/path/does-not-exist.git",
            repo_token="",
            clone_dir=tmp_path / "clone",
            branch_name="luna/x",
            file_path="x.md",
            commit_message="x",
            push=False,
        )


async def test_generate_and_commit_package_writes_artifact_row(
    db_session, bare_repo: Path, tmp_path: Path
) -> None:
    run = AgentRun(capability="design_review", trigger_source="test", status=RunStatus.decide)
    db_session.add(run)
    await db_session.flush()

    spec = PackageSpec(
        package_kind="PDR",
        title="Full Flow PDR",
        sections=[PackageSectionInput(heading="Overview", items=["one solid requirement bullet"])],
    )

    draft, artifact = await generate_and_commit_package(
        db_session,
        run.id,
        _StubProvider(sufficient=True),
        _EchoGeneration(),
        spec,
        repo_url=f"file://{bare_repo}",
        repo_token="",
        clone_dir=tmp_path / "luna-clone-2",
        push=True,
    )

    assert artifact.type == ArtifactType.draft
    assert artifact.git_commit and len(artifact.git_commit) == 40
    assert artifact.repo_path and artifact.repo_path.endswith(".md")
    assert "Overview" in draft.markdown
