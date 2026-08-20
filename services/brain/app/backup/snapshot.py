from __future__ import annotations

import hashlib
import shutil
import sqlite3
from pathlib import Path

from app.devices.schemas import utc_now

from .schemas import BackupKind, BackupManifest


class SnapshotService:
    """Creates consistent, versioned backup snapshots: the SQLite
    database is copied through sqlite3's backup API (safe while the
    Brain is running), and configured data/config directories are
    copied wholesale. Secrets are excluded — backups never contain
    plaintext credentials (see docs/BACKUP_RECOVERY.md)."""

    EXCLUDED_NAMES = {"secrets", "node_modules", "__pycache__", ".venv", "dist"}

    def __init__(self, database_path: Path, roots: list[Path] | None = None):
        self.database_path = Path(database_path)
        self.roots = [Path(root) for root in (roots or [])]

    def _copy_database(self, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(self.database_path)
        try:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        finally:
            source.close()

    def _copy_roots(self, backup_dir: Path) -> dict[str, str]:
        parts: dict[str, str] = {}
        for root in self.roots:
            if not root.exists():
                continue
            for item in sorted(root.rglob("*")):
                if any(part in self.EXCLUDED_NAMES for part in item.parts):
                    continue
                if not item.is_file():
                    continue
                relative = item.relative_to(root.parent)
                target = backup_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
                parts[str(relative).replace("\\", "/")] = self._hash_file(target)
        return parts

    @staticmethod
    def _hash_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def create(self, backup_root: Path, kind: BackupKind = BackupKind.MANUAL, *, encrypt: bool = False) -> BackupManifest:
        stamp = utc_now().strftime("%Y%m%d-%H%M%S")
        backup_dir = backup_root / f"{kind.value}-{stamp}"
        backup_dir.mkdir(parents=True, exist_ok=True)
        manifest = BackupManifest(kind=kind, encrypted=encrypt)
        self._copy_database(backup_dir / "vyom-brain.db")
        parts = {"vyom-brain.db": self._hash_file(backup_dir / "vyom-brain.db")}
        parts.update(self._copy_roots(backup_dir))
        manifest.parts = parts
        manifest.size_bytes = sum((backup_dir / rel).stat().st_size for rel in parts)
        (backup_dir / "manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")
        return manifest
