"""`POST /packages/generate`.

Defines an `APIRouter` named `router`; `luna/api/main.py` mounts it with
`app.include_router(packages.router)`.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from luna.api.deps import get_db, require_service_token
from luna.capabilities.design_review import (
    PackageSectionInput,
    PackageSpec,
    generate_and_commit_package,
)
from luna.config import get_settings
from luna.db.models import AgentRun, RunStatus
from luna.decision.engine import get_decision_provider
from luna.generation.generator import Generation

router = APIRouter(tags=["packages"], dependencies=[Depends(require_service_token)])


class SectionIn(BaseModel):
    heading: str
    items: list[str] = []


class PackagesGenerateIn(BaseModel):
    package_kind: str
    title: str
    sections: list[SectionIn]
    push: bool = True


class PackagesGenerateOut(BaseModel):
    run_id: uuid.UUID
    artifact_id: uuid.UUID
    repo_path: str
    git_commit: str
    markdown_preview: str


@router.post("/packages/generate", response_model=PackagesGenerateOut)
async def packages_generate(
    body: PackagesGenerateIn, session: AsyncSession = Depends(get_db)
) -> PackagesGenerateOut:
    settings = get_settings()
    if not (settings.docs_repo_url and settings.docs_repo_token):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "DOCS_REPO_URL/DOCS_REPO_TOKEN are not configured -- capability #7 cannot "
                "commit a draft without a docs repo to commit to."
            ),
        )

    run = AgentRun(capability="design_review", trigger_source="api", status=RunStatus.decide)
    session.add(run)
    await session.flush()

    provider = get_decision_provider()
    generation = Generation.from_settings(settings)
    spec = PackageSpec(
        package_kind=body.package_kind,
        title=body.title,
        sections=[PackageSectionInput(heading=s.heading, items=s.items) for s in body.sections],
    )
    try:
        draft, artifact = await generate_and_commit_package(
            session,
            run.id,
            provider,
            generation,
            spec,
            repo_url=settings.docs_repo_url,
            repo_token=settings.docs_repo_token,
            clone_dir=Path(tempfile.mkdtemp(prefix="luna-docs-repo-")),
            push=body.push,
        )
    finally:
        aclose = getattr(provider, "aclose", None)
        if aclose is not None:
            await aclose()
        await generation.aclose()

    run.status = RunStatus.completed
    await session.commit()

    return PackagesGenerateOut(
        run_id=run.id,
        artifact_id=artifact.id,
        repo_path=artifact.repo_path or "",
        git_commit=artifact.git_commit or "",
        markdown_preview=draft.markdown[:2000],
    )
