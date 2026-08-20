from __future__ import annotations

import sqlite3
from pathlib import Path

from .schemas import BackupManifest


class InvalidBackupError(Exception):
    pass


class BackupValidator:
    """Verifies a backup before it can be restored: manifest present
    and parseable, every part's sha256 matches, and the embedded
    database copy passes SQLite's integrity check. Corrupt backups are
    rejected loudly, never restored."""

    @staticmethod
    def _hash_file(path: Path) -> str:
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def load_manifest(self, backup_dir: Path) -> BackupManifest:
        manifest_path = backup_dir / "manifest.json"
        if not manifest_path.exists():
            raise InvalidBackupError("Backup has no manifest.json")
        try:
            return BackupManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
        except Exception as error:
            raise InvalidBackupError(f"Backup manifest is unreadable: {error}") from error

    def validate(self, backup_dir: Path) -> BackupManifest:
        manifest = self.load_manifest(backup_dir)
        for relative, expected_hash in manifest.parts.items():
            part = backup_dir / relative
            if not part.exists():
                raise InvalidBackupError(f"Missing backup part: {relative}")
            if self._hash_file(part) != expected_hash:
                raise InvalidBackupError(f"Checksum mismatch for {relative}; backup is corrupt")
        database = backup_dir / "vyom-brain.db"
        if database.exists():
            connection = sqlite3.connect(database)
            try:
                row = connection.execute("PRAGMA integrity_check").fetchone()
                if row is None or row[0] != "ok":
                    raise InvalidBackupError(f"Backup database failed integrity check: {row[0] if row else 'no result'}")
            finally:
                connection.close()
        return manifest
