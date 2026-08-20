from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RollbackPlan:
    """Rollbacks in VYOM are restore-based, not destructive in-place
    down-migrations: a failed update restores the pre-update backup
    (docs/BACKUP_RECOVERY.md). This module records and verifies the
    plan; it never mutates the live database by itself."""

    from_version: int
    to_version: int
    backup_id: str
    steps: list[str]

    @classmethod
    def for_update(cls, from_version: int, backup_id: str) -> "RollbackPlan":
        return cls(
            from_version=from_version,
            to_version=max(from_version - 1, 0),
            backup_id=backup_id,
            steps=[
                f"stop Brain services safely",
                f"validate backup {backup_id}",
                "restore database from backup",
                "restart and re-run startup checks",
                f"record schema rollback {from_version} -> {max(from_version - 1, 0)}",
            ],
        )

    def as_dict(self) -> dict:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "backup_id": self.backup_id,
            "steps": self.steps,
        }
