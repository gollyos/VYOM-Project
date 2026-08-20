from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from app.runtime.event_bus import EventBus
from app.schemas.events import BrainEvent, EventType

from .schemas import BackupKind, BackupManifest
from .snapshot import SnapshotService
from .validation import BackupValidator


class BackupManager:
    """Versioned backups with retention and schedules (manual/daily/
    weekly). Backups never overwrite the only known-good copy — each
    backup is a new timestamped directory and retention prunes only
    beyond the configured keep count."""

    def __init__(
        self,
        database,
        snapshot: SnapshotService,
        backup_root: Path,
        event_bus: EventBus | None = None,
        *,
        retention: int = 10,
        schedule: str = "manual",
    ):
        self.database = database
        self.snapshot = snapshot
        self.backup_root = Path(backup_root)
        self.event_bus = event_bus
        self.retention = retention
        self.schedule = schedule
        self.validator = BackupValidator()

    async def _record(self, manifest: BackupManifest) -> None:
        await self.database.require_connection().execute(
            """
            INSERT INTO backup_records (id, status, kind, manifest_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET status = excluded.status, manifest_json = excluded.manifest_json
            """,
            (manifest.backup_id, "completed", manifest.kind.value, manifest.model_dump_json(), manifest.created_at.isoformat()),
        )
        await self.database.require_connection().commit()

    async def run(self, kind: BackupKind | None = None) -> BackupManifest:
        kind = kind or BackupKind.MANUAL
        if self.event_bus is not None:
            await self.event_bus.publish(BrainEvent(
                task_id="system", type=EventType.BACKUP_STARTED,
                human_readable_message=f"{kind.value} backup starting",
                structured_payload={"kind": kind.value},
            ))
        try:
            manifest = self.snapshot.create(self.backup_root, kind)
            await self._record(manifest)
            self._apply_retention()
        except Exception as error:
            if self.event_bus is not None:
                await self.event_bus.publish(BrainEvent(
                    task_id="system", type=EventType.BACKUP_FAILED,
                    human_readable_message=f"Backup failed: {error}",
                    structured_payload={"error": str(error)},
                ))
            raise
        if self.event_bus is not None:
            await self.event_bus.publish(BrainEvent(
                task_id="system", type=EventType.BACKUP_COMPLETED,
                human_readable_message=f"{kind.value} backup completed ({manifest.size_bytes} bytes)",
                structured_payload={"backup_id": manifest.backup_id, "size_bytes": manifest.size_bytes},
            ))
        return manifest

    def list_backups(self) -> list[dict]:
        results: list[dict] = []
        if not self.backup_root.exists():
            return results
        for directory in sorted(self.backup_root.iterdir(), reverse=True):
            manifest_path = directory / "manifest.json"
            if not directory.is_dir() or not manifest_path.exists():
                continue
            try:
                manifest = BackupManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            results.append({
                "backup_id": manifest.backup_id,
                "kind": manifest.kind.value,
                "created_at": manifest.created_at.isoformat(),
                "size_bytes": manifest.size_bytes,
                "encrypted": manifest.encrypted,
                "directory": str(directory),
            })
        return results

    def _apply_retention(self) -> None:
        directories = sorted(
            (item for item in self.backup_root.iterdir() if item.is_dir() and (item / "manifest.json").exists()),
            reverse=True,
        )
        import shutil

        for stale in directories[self.retention:]:
            shutil.rmtree(stale, ignore_errors=True)

    async def due_scheduled(self) -> BackupKind | None:
        """Returns which scheduled backup kind is due, if any, based on
        the newest existing backup of the scheduled kind."""
        if self.schedule == "manual":
            return None
        kind = BackupKind.DAILY if self.schedule == "daily" else BackupKind.WEEKLY
        window = timedelta(days=1) if kind == BackupKind.DAILY else timedelta(weeks=1)
        existing = [item for item in self.list_backups() if item["kind"] == kind.value]
        if not existing:
            return kind
        newest = datetime.fromisoformat(existing[0]["created_at"])
        if datetime.now(newest.tzinfo) - newest >= window:
            return kind
        return None
