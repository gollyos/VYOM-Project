from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import ArtifactRecord


class ArtifactStore:
    def __init__(self, database: Database):
        self.database = database

    async def save(self, record: ArtifactRecord) -> ArtifactRecord:
        record.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO artifacts(id, artifact_type, task_id, version, manifest_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               version=excluded.version, manifest_json=excluded.manifest_json, updated_at=excluded.updated_at""",
            (
                record.id, record.spec.type.value, record.spec.task_id, record.version,
                record.model_dump_json(), record.created_at.isoformat(), record.updated_at.isoformat(),
            ),
        )
        await connection.commit()
        return record

    async def get(self, artifact_id: str) -> ArtifactRecord:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT manifest_json FROM artifacts WHERE id = ?", (artifact_id,))).fetchone()
        if row is None:
            raise KeyError(artifact_id)
        return ArtifactRecord.model_validate_json(row["manifest_json"])

    async def list(self, task_id: str | None = None) -> list[ArtifactRecord]:
        connection = self.database.require_connection()
        if task_id:
            rows = await (await connection.execute(
                "SELECT manifest_json FROM artifacts WHERE task_id = ? ORDER BY updated_at DESC", (task_id,)
            )).fetchall()
        else:
            rows = await (await connection.execute("SELECT manifest_json FROM artifacts ORDER BY updated_at DESC")).fetchall()
        return [ArtifactRecord.model_validate_json(row["manifest_json"]) for row in rows]


class VersionManager:
    """Working client deliverables are never silently overwritten: each
    revision gets v1/v2/... and an explicit 'final' label."""

    @staticmethod
    def next_version(existing_versions: list[str]) -> str:
        numeric = [int(value[1:]) for value in existing_versions if value.startswith("v") and value[1:].isdigit()]
        return f"v{(max(numeric) + 1) if numeric else 1}"

    @staticmethod
    def mark_final(record: ArtifactRecord) -> ArtifactRecord:
        if record.version not in record.versions:
            record.versions.append(record.version)
        record.version = "final"
        if "final" not in record.versions:
            record.versions.append("final")
        return record
