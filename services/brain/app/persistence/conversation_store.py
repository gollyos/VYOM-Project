from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import BaseModel, Field

from app.persistence.database import Database


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ConversationTurn(BaseModel):
    """One turn in the raw conversation transcript - distinct from a Task
    (a unit of work) and from a MemoryEntry (a curated/summarized fact).
    This is what lets a later session literally search "what did I say
    about X" the way Hermes's own messages table does, instead of only
    being able to search structured task/memory rows."""

    id: str = Field(default_factory=lambda: f"turn_{uuid4().hex}")
    context_id: str
    task_id: str | None = None
    role: str  # "user" | "assistant"
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class ConversationStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def record(self, turn: ConversationTurn) -> ConversationTurn:
        connection = self.database.require_connection()
        await connection.execute(
            "INSERT INTO conversation_turns(id, context_id, task_id, role, content, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (turn.id, turn.context_id, turn.task_id, turn.role, turn.content, turn.created_at.isoformat()),
        )
        await connection.commit()
        return turn

    async def record_exchange(self, *, context_id: str, task_id: str | None,
                              user_message: str, assistant_response: str) -> list[ConversationTurn]:
        """Record one user turn + one assistant turn together - the shape
        every task actually produces (a request, then a result)."""
        turns = [
            ConversationTurn(context_id=context_id, task_id=task_id, role="user", content=user_message),
            ConversationTurn(context_id=context_id, task_id=task_id, role="assistant", content=assistant_response),
        ]
        for turn in turns:
            await self.record(turn)
        return turns

    async def history(self, context_id: str, *, limit: int = 50) -> list[ConversationTurn]:
        """Most recent turns for one context, oldest first (reading order)."""
        connection = self.database.require_connection()
        rows = await (await connection.execute(
            "SELECT id, context_id, task_id, role, content, created_at FROM conversation_turns "
            "WHERE context_id = ? ORDER BY created_at DESC LIMIT ?",
            (context_id, limit),
        )).fetchall()
        turns = [
            ConversationTurn(
                id=row["id"], context_id=row["context_id"], task_id=row["task_id"],
                role=row["role"], content=row["content"], created_at=row["created_at"],
            )
            for row in rows
        ]
        return list(reversed(turns))

    async def search(self, text: str, *, context_id: str | None = None, limit: int = 20) -> list[ConversationTurn]:
        """Full-text search across the raw transcript. Tokens are quoted
        so user text can never break the FTS query language; when FTS is
        unavailable an empty result is returned rather than raising (same
        degrade-gracefully contract as MemoryStore.search_fts).

        Two-step lookup (FTS ids, then row fetch) rather than a JOIN -
        FTS5 does not resolve `MATCH` against a query alias reliably
        inside a JOIN, matching the pattern MemoryStore.search_fts
        already uses successfully."""
        tokens = [token for token in text.lower().split() if token.strip()]
        if not tokens:
            return []
        match = " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)
        connection = self.database.require_connection()
        try:
            fts_rows = await (await connection.execute(
                "SELECT id FROM conversation_turns_fts WHERE conversation_turns_fts MATCH ? "
                "ORDER BY rank LIMIT ?",
                (match, limit * 3 if context_id else limit),
            )).fetchall()
        except Exception:
            return []
        ids = [row["id"] for row in fts_rows]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        if context_id:
            rows = await (await connection.execute(
                f"SELECT id, context_id, task_id, role, content, created_at FROM conversation_turns "
                f"WHERE id IN ({placeholders}) AND context_id = ?",
                (*ids, context_id),
            )).fetchall()
        else:
            rows = await (await connection.execute(
                f"SELECT id, context_id, task_id, role, content, created_at FROM conversation_turns "
                f"WHERE id IN ({placeholders})",
                tuple(ids),
            )).fetchall()
        by_id = {
            row["id"]: ConversationTurn(
                id=row["id"], context_id=row["context_id"], task_id=row["task_id"],
                role=row["role"], content=row["content"], created_at=row["created_at"],
            )
            for row in rows
        }
        # Preserve FTS rank order, drop ids filtered out by context_id.
        return [by_id[i] for i in ids if i in by_id][:limit]

    async def count(self, context_id: str | None = None) -> int:
        connection = self.database.require_connection()
        if context_id:
            row = await (await connection.execute(
                "SELECT COUNT(*) AS total FROM conversation_turns WHERE context_id = ?", (context_id,)
            )).fetchone()
        else:
            row = await (await connection.execute("SELECT COUNT(*) AS total FROM conversation_turns")).fetchone()
        return int(row["total"])
