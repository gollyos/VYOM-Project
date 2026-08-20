from __future__ import annotations

import shutil
from pathlib import Path

from app.distributed.audit import DistributedAuditLog

from .schemas import BackupManifest
from .validation import BackupValidator, InvalidBackupError


class RestoreError(Exception):
    pass


class RestoreService:
    """select backup -> validate -> show metadata -> stop services
    safely -> restore -> verify -> restart. Restoration never
    overwrites current state silently: it requires an explicit
    confirmation, and Brain-side services must already be quiesced by
    the caller (the API layer stops the scheduler/supervisor first)."""

    def __init__(self, database_path: Path, audit: DistributedAuditLog | None = None, validator: BackupValidator | None = None):
        self.database_path = Path(database_path)
        self.audit = audit
        self.validator = validator or BackupValidator()

    def preview(self, backup_dir: Path | str) -> dict:
        manifest = self.validator.load_manifest(Path(backup_dir))
        return {
            "backup_id": manifest.backup_id,
            "kind": manifest.kind.value,
            "created_at": manifest.created_at.isoformat(),
            "size_bytes": manifest.size_bytes,
            "parts": sorted(manifest.parts),
            "encrypted": manifest.encrypted,
        }

    async def restore(self, backup_dir: Path | str, *, confirm: bool, on_quiesce=None) -> dict:
        backup_dir = Path(backup_dir)
        if not confirm:
            raise RestoreError("Restore requires explicit confirmation; current state is never overwritten silently")
        manifest: BackupManifest
        try:
            manifest = self.validator.validate(backup_dir)
        except InvalidBackupError as error:
            if self.audit is not None:
                await self.audit.record("restore_rejected", result="invalid_backup", evidence=str(error))
            raise
        if on_quiesce is not None:
            await on_quiesce()  # caller stops scheduler/supervisor/tasks safely

        backup_db = backup_dir / "vyom-brain.db"
        if backup_db.exists():
            temporary = self.database_path.with_suffix(".restore-tmp")
            shutil.copy2(backup_db, temporary)
            # Post-restore migration safety: the copied DB must open and
            # pass integrity before it replaces the live database.
            import sqlite3

            connection = sqlite3.connect(temporary)
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
                if row is None or row[0] != "ok":
                    raise RestoreError("Restored database failed integrity check")
            finally:
                connection.close()
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(temporary, self.database_path)
            temporary.unlink(missing_ok=True)
        if self.audit is not None:
            await self.audit.record("restore_completed", result=manifest.backup_id)
        return {"restored": manifest.backup_id, "created_at": manifest.created_at.isoformat()}
