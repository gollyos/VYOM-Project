from __future__ import annotations

from .schemas import DeviceNode, DeviceTrustLevel


class DeviceNodeStore:
    """Durable SQLite backing for the node registry so paired nodes,
    trust, and revocations survive Brain restarts (Phase 12)."""

    def __init__(self, database):
        self.database = database

    async def save(self, node: DeviceNode) -> None:
        await self.database.require_connection().execute(
            """
            INSERT INTO nodes (node_id, trust_level, node_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                trust_level = excluded.trust_level,
                node_json = excluded.node_json,
                updated_at = excluded.updated_at
            """,
            (
                node.node_id,
                node.trust_level.value,
                node.model_dump_json(),
                node.created_at.isoformat(),
                node.updated_at.isoformat(),
            ),
        )
        await self.database.require_connection().commit()

    async def load_all(self) -> list[DeviceNode]:
        cursor = await self.database.require_connection().execute(
            "SELECT node_json FROM nodes"
        )
        rows = await cursor.fetchall()
        return [DeviceNode.model_validate_json(row["node_json"]) for row in rows]

    async def delete(self, node_id: str) -> None:
        await self.database.require_connection().execute(
            "DELETE FROM nodes WHERE node_id = ?", (node_id,)
        )
        await self.database.require_connection().commit()


class NodeTokenStore:
    """Durable storage for SHA-256 hashed node credentials. Plaintext
    tokens exist only in the pairing/rotation response, never on disk."""

    def __init__(self, database):
        self.database = database

    async def save(self, node_id: str, token_hash: str) -> None:
        from app.devices.schemas import utc_now

        await self.database.require_connection().execute(
            """
            INSERT INTO node_tokens (node_id, token_hash, rotated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                token_hash = excluded.token_hash,
                rotated_at = excluded.rotated_at
            """,
            (node_id, token_hash, utc_now().isoformat()),
        )
        await self.database.require_connection().commit()

    async def get(self, node_id: str) -> str | None:
        cursor = await self.database.require_connection().execute(
            "SELECT token_hash FROM node_tokens WHERE node_id = ?", (node_id,)
        )
        row = await cursor.fetchone()
        return row["token_hash"] if row else None

    async def delete(self, node_id: str) -> None:
        await self.database.require_connection().execute(
            "DELETE FROM node_tokens WHERE node_id = ?", (node_id,)
        )
        await self.database.require_connection().commit()
