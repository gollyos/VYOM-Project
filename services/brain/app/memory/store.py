from __future__ import annotations

import json
from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import MemoryEntry, MemoryRelationship, MemoryType, Sensitivity, VerificationState

#: Fields whose change is SUBSTANTIVE: touching one snapshots the outgoing
#: state into memory_history and bumps the version. Access-time updates
#: (last_accessed_at) and metadata touches do not - versioning every read
#: would bury real history in noise.
_SUBSTANTIVE_FIELDS = (
    "title", "summary", "content", "entities", "tags",
    "importance", "confidence", "sensitivity", "verification_state",
)


class MemoryStore:
    def __init__(self, database: Database, vault=None):
        self.database = database
        #: Optional MemoryVault - every successful save mirrors to the
        #: human-readable markdown vault AFTER the commit.
        self.vault = vault

    def _substantive(self, old: MemoryEntry, new: MemoryEntry) -> bool:
        return any(getattr(old, field) != getattr(new, field) for field in _SUBSTANTIVE_FIELDS)

    async def save(self, memory: MemoryEntry) -> MemoryEntry:
        connection = self.database.require_connection()
        cursor = await connection.execute(
            "SELECT memory_json FROM memories WHERE id = ?", (memory.id,)
        )
        row = await cursor.fetchone()
        previous = MemoryEntry.model_validate_json(row["memory_json"]) if row else None
        memory.updated_at = datetime.now(timezone.utc)
        if previous is not None and self._substantive(previous, memory):
            # Append-only history: the outgoing state is snapshotted
            # BEFORE the row changes. Nothing is overwritten, ever.
            memory.version = max(previous.version, 1) + 1
            await connection.execute(
                "INSERT INTO memory_history(memory_id, version, memory_json, saved_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    previous.id,
                    previous.version,
                    json.dumps(previous.model_dump(mode="json"), separators=(",", ":")),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        elif previous is not None:
            memory.version = max(previous.version, memory.version, 1)
        payload = json.dumps(memory.model_dump(mode="json"), separators=(",", ":"))
        await connection.execute(
            """
            INSERT INTO memories(
                id, type, title, summary, content, project_id, client_id, task_id,
                agent_id, sensitivity, verification_state, importance, confidence,
                memory_json, created_at, updated_at, last_accessed_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                type=excluded.type, title=excluded.title, summary=excluded.summary,
                content=excluded.content, project_id=excluded.project_id,
                client_id=excluded.client_id, task_id=excluded.task_id,
                agent_id=excluded.agent_id, sensitivity=excluded.sensitivity,
                verification_state=excluded.verification_state,
                importance=excluded.importance, confidence=excluded.confidence,
                memory_json=excluded.memory_json, updated_at=excluded.updated_at,
                last_accessed_at=excluded.last_accessed_at, expires_at=excluded.expires_at
            """,
            (
                memory.id, memory.type.value, memory.title, memory.summary, memory.content,
                memory.project_id, memory.client_id, memory.task_id, memory.agent_id,
                memory.sensitivity.value, memory.verification_state.value,
                memory.importance, memory.confidence, payload,
                memory.created_at.isoformat(), memory.updated_at.isoformat(),
                memory.last_accessed_at.isoformat(),
                memory.expires_at.isoformat() if memory.expires_at else None,
            ),
        )
        await connection.commit()
        if self.vault is not None:
            self.vault.write(memory)
        return memory

    async def get(self, memory_id: str, *, touch: bool = True) -> MemoryEntry | None:
        connection = self.database.require_connection()
        cursor = await connection.execute("SELECT memory_json FROM memories WHERE id = ?", (memory_id,))
        row = await cursor.fetchone()
        if not row:
            return None
        memory = MemoryEntry.model_validate_json(row["memory_json"])
        if touch:
            memory.last_accessed_at = datetime.now(timezone.utc)
            await self.save(memory)
        return memory

    async def list(
        self,
        *,
        types: set[MemoryType] | None = None,
        project_id: str | None = None,
        client_id: str | None = None,
        agent_id: str | None = None,
        entities: set[str] | None = None,
        sources: set[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        include_expired: bool = False,
        include_deleted: bool = False,
        ids: list[str] | None = None,
        max_sensitivity: Sensitivity = Sensitivity.HIGHLY_SENSITIVE,
        verification_states: set[VerificationState] | None = None,
        limit: int = 500,
    ) -> list[MemoryEntry]:
        # Filter in SQLite BEFORE LIMIT.  The former implementation loaded
        # only the newest 500 memories and then filtered in Python, making
        # an otherwise healthy ten-year-old project/client record
        # impossible to recall once 500 newer rows existed.
        sensitivity_order = (
            Sensitivity.NORMAL,
            Sensitivity.SENSITIVE,
            Sensitivity.HIGHLY_SENSITIVE,
        )
        allowed_sensitivity = [
            value.value for value in sensitivity_order
            if sensitivity_order.index(value) <= sensitivity_order.index(max_sensitivity)
        ]
        clauses: list[str] = []
        parameters: list[object] = []

        def add_membership(column: str, values: list[str]) -> None:
            if not values:
                return
            placeholders = ",".join("?" for _ in values)
            clauses.append(f"{column} IN ({placeholders})")
            parameters.extend(values)

        add_membership("type", [value.value for value in (types or set())])
        add_membership("sensitivity", allowed_sensitivity)
        add_membership(
            "verification_state",
            [value.value for value in (verification_states or set())],
        )
        for column, value in (
            ("project_id", project_id),
            ("client_id", client_id),
            ("agent_id", agent_id),
        ):
            if value:
                clauses.append(f"{column} = ?")
                parameters.append(value)
        if created_after:
            clauses.append("created_at >= ?")
            parameters.append(created_after.isoformat())
        if created_before:
            clauses.append("created_at < ?")
            parameters.append(created_before.isoformat())
        if not include_expired:
            clauses.append("(expires_at IS NULL OR expires_at > ?)")
            parameters.append(datetime.now(timezone.utc).isoformat())
        # Soft-deleted (forgotten) memories stay in the store forever but
        # leave ordinary retrieval - only an explicit history query sees
        # them. The tombstone lives inside memory_json, so no migration
        # was needed to give every existing row this behaviour.
        if not include_deleted:
            clauses.append("json_extract(memory_json, '$.deleted_at') IS NULL")
        if ids:
            placeholders = ",".join("?" for _ in ids)
            clauses.append(f"id IN ({placeholders})")
            parameters.extend(ids)
        if sources:
            placeholders = ",".join("?" for _ in sources)
            clauses.append(
                f"lower(json_extract(memory_json, '$.source')) IN ({placeholders})"
            )
            parameters.extend(source.lower() for source in sources)
        if entities:
            entity_clauses = []
            for entity in entities:
                entity_clauses.append(
                    "EXISTS (SELECT 1 FROM json_each(memory_json, '$.entities') "
                    "WHERE lower(CAST(value AS TEXT)) = ?)"
                )
                parameters.append(entity.lower())
            clauses.append("(" + " OR ".join(entity_clauses) + ")")

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        parameters.append(limit)
        connection = self.database.require_connection()
        cursor = await connection.execute(
            f"SELECT memory_json FROM memories{where} ORDER BY created_at DESC LIMIT ?",
            parameters,
        )
        return [
            MemoryEntry.model_validate_json(row["memory_json"])
            for row in await cursor.fetchall()
        ]

    async def forget(self, memory_id: str) -> bool:
        """Soft-forget: tombstone, never erase.

        "Uski memory se kuch erase bhi na ho" - a hard DELETE would make
        the user's own history unknowable, including by them. The row
        stays; retrieval skips it; include_deleted=True answers "what was
        this" ten years later. Returns True when the memory existed and
        was not already tombstoned."""
        memory = await self.get(memory_id, touch=False)
        if memory is None or memory.deleted_at is not None:
            return False
        memory.deleted_at = datetime.now(timezone.utc)
        await self.save(memory)
        return True

    async def purge(self, memory_id: str) -> bool:
        """True erasure. NOT exposed through the API or the voice
        interface - this exists for explicit, deliberate maintenance only
        (e.g. a legal erasure request), never for ordinary 'forget'."""
        memory = await self.get(memory_id, touch=False)
        connection = self.database.require_connection()
        cursor = await connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        await connection.commit()
        if cursor.rowcount > 0 and memory is not None and self.vault is not None:
            # The vault must not keep what the authority dropped.
            self.vault.discard(memory)
        return cursor.rowcount > 0

    async def history(self, memory_id: str) -> list[MemoryEntry]:
        """Every prior version of a memory, oldest first."""
        connection = self.database.require_connection()
        cursor = await connection.execute(
            "SELECT memory_json FROM memory_history WHERE memory_id = ? ORDER BY version ASC",
            (memory_id,),
        )
        return [
            MemoryEntry.model_validate_json(row["memory_json"])
            for row in await cursor.fetchall()
        ]

    async def search_fts(self, text: str, limit: int = 200) -> list[str]:
        """Full-text search over memory text, best matches first.

        Returns memory ids. Tokens are quoted so user text can never
        break the FTS query language; when FTS is unavailable (older
        SQLite) an empty result is returned and the caller falls back to
        the structured candidate path."""
        tokens = [token for token in text.lower().split() if token.strip()]
        if not tokens:
            return []
        match = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        connection = self.database.require_connection()
        try:
            cursor = await connection.execute(
                "SELECT id FROM memories_fts WHERE memories_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (match, limit),
            )
            return [row["id"] for row in await cursor.fetchall()]
        except Exception:
            return []

    async def relationship_counts(self, memory_ids: list[str]) -> dict[str, int]:
        """Relationship counts for many memories in ONE query - the
        per-candidate lookup was N+1 and would not stay sub-second at
        ten-year scale."""
        if not memory_ids:
            return {}
        placeholders = ",".join("?" for _ in memory_ids)
        connection = self.database.require_connection()
        cursor = await connection.execute(
            "SELECT memory_id, COUNT(*) AS total FROM ("
            " SELECT source_id AS memory_id FROM memory_relationships"
            f" WHERE source_id IN ({placeholders})"
            " UNION ALL"
            " SELECT target_id FROM memory_relationships"
            f" WHERE target_id IN ({placeholders})"
            ") GROUP BY memory_id",
            (*memory_ids, *memory_ids),
        )
        return {row["memory_id"]: int(row["total"]) for row in await cursor.fetchall()}

    async def save_relationship(self, relationship: MemoryRelationship) -> MemoryRelationship:
        connection = self.database.require_connection()
        await connection.execute(
            """
            INSERT INTO memory_relationships(id, source_id, target_id, relation, confidence, relationship_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET confidence=excluded.confidence, relationship_json=excluded.relationship_json
            """,
            (
                relationship.id, relationship.source_id, relationship.target_id,
                relationship.relation.value, relationship.confidence,
                json.dumps(relationship.model_dump(mode="json"), separators=(",", ":")),
                relationship.created_at.isoformat(),
            ),
        )
        await connection.commit()
        return relationship

    async def relationships(self, memory_id: str, relation: str | None = None) -> list[MemoryRelationship]:
        connection = self.database.require_connection()
        if relation:
            cursor = await connection.execute(
                "SELECT relationship_json FROM memory_relationships WHERE (source_id=? OR target_id=?) AND relation=?",
                (memory_id, memory_id, relation),
            )
        else:
            cursor = await connection.execute(
                "SELECT relationship_json FROM memory_relationships WHERE source_id=? OR target_id=?",
                (memory_id, memory_id),
            )
        return [MemoryRelationship.model_validate_json(row["relationship_json"]) for row in await cursor.fetchall()]

    async def count(self) -> int:
        cursor = await self.database.require_connection().execute("SELECT COUNT(*) AS total FROM memories")
        row = await cursor.fetchone()
        return int(row["total"])
