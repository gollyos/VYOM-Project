from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.backup.restore import RestoreError
from app.backup.validation import InvalidBackupError

router = APIRouter(prefix="/api/backup", tags=["backup"])


class RunBackupRequest(BaseModel):
    kind: str = "manual"  # manual | daily | weekly


class RestoreRequest(BaseModel):
    backup_dir: str
    confirm: bool = False


@router.get("")
async def list_backups(request: Request) -> list[dict]:
    return request.app.state.backup_manager.list_backups()


@router.post("")
async def run_backup(payload: RunBackupRequest, request: Request) -> dict:
    from app.backup.schemas import BackupKind

    try:
        kind = BackupKind(payload.kind)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=f"Unknown backup kind {payload.kind!r}") from error
    manifest = await request.app.state.backup_manager.run(kind)
    return {
        "backup_id": manifest.backup_id, "kind": manifest.kind.value,
        "size_bytes": manifest.size_bytes, "parts": len(manifest.parts),
    }


@router.get("/{backup_id}/preview")
async def preview_backup(backup_id: str, request: Request) -> dict:
    manager = request.app.state.backup_manager
    import json

    for candidate in sorted(manager.backup_root.glob("*-*")):
        manifest_path = candidate / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("backup_id") == backup_id:
            return request.app.state.restore_service.preview(candidate)
    raise HTTPException(status_code=404, detail="Backup not found")


@router.post("/restore")
async def restore_backup(payload: RestoreRequest, request: Request) -> dict:
    restore_service = request.app.state.restore_service

    async def quiesce() -> None:
        state = request.app.state
        await state.supervisor.stop()
        await state.automation_scheduler.stop()

    try:
        result = await restore_service.restore(payload.backup_dir, confirm=payload.confirm, on_quiesce=quiesce)
    except (InvalidBackupError, RestoreError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    # A restore requires a Brain restart to reload state; that is the
    # documented operator step, never something VYOM does silently.
    result["restart_required"] = True
    return result
