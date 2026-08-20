from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import Commitment, CommitmentStatus, PersonalProfile


class PersonalProfileStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, profile_id: str = "default") -> PersonalProfile:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT profile_json FROM personal_profile WHERE id = ?", (profile_id,))).fetchone()
        if row is None:
            return PersonalProfile(id=profile_id)
        return PersonalProfile.model_validate_json(row["profile_json"])

    async def save(self, profile: PersonalProfile) -> PersonalProfile:
        profile.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO personal_profile(id, profile_json, created_at, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET profile_json=excluded.profile_json, updated_at=excluded.updated_at""",
            (profile.id, profile.model_dump_json(), profile.created_at.isoformat(), profile.updated_at.isoformat()),
        )
        await connection.commit()
        return profile


class CommitmentStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, commitment: Commitment) -> Commitment:
        commitment.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO commitments(id, status, deadline, commitment_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, deadline=excluded.deadline, commitment_json=excluded.commitment_json, updated_at=excluded.updated_at""",
            (
                commitment.id, commitment.status.value, commitment.deadline.isoformat() if commitment.deadline else None,
                commitment.model_dump_json(), commitment.created_at.isoformat(), commitment.updated_at.isoformat(),
            ),
        )
        await connection.commit()
        return commitment

    async def get(self, commitment_id: str) -> Commitment | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT commitment_json FROM commitments WHERE id = ?", (commitment_id,))).fetchone()
        return Commitment.model_validate_json(row["commitment_json"]) if row else None

    async def list(self, status: CommitmentStatus | None = None) -> list[Commitment]:
        connection = self.database.require_connection()
        if status:
            rows = await (await connection.execute(
                "SELECT commitment_json FROM commitments WHERE status = ? ORDER BY deadline IS NULL, deadline ASC", (status.value,)
            )).fetchall()
        else:
            rows = await (await connection.execute("SELECT commitment_json FROM commitments ORDER BY created_at DESC")).fetchall()
        return [Commitment.model_validate_json(row["commitment_json"]) for row in rows]
