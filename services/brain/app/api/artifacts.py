from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.artifacts.schemas import ArtifactRecord

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/{artifact_id}", response_model=ArtifactRecord)
async def get_artifact(artifact_id: str, request: Request) -> ArtifactRecord:
    try:
        return await request.app.state.artifact_store.get(artifact_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Artifact not found") from error


@router.get("", response_model=list[ArtifactRecord])
async def list_artifacts(request: Request, task_id: str | None = None) -> list[ArtifactRecord]:
    return await request.app.state.artifact_store.list(task_id)
