from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4

from pydantic import BaseModel, Field

from app.persistence.database import Database


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KanbanStatus(str, Enum):
    PENDING = "pending"
    CLAIMED = "claimed"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    FAILED = "failed"


class KanbanCard(BaseModel):
    """One card on the board - mirrors Hermes's own kanban_db.py task
    shape (claim -> in_progress -> completed/blocked), scoped down to
    what VYOM's single-Brain-process deployment actually needs: no
    multi-profile/multi-board split (Hermes has that because it runs
    many separate profiles; VYOM is one Brain), just the real
    parallel-worker-subprocess lifecycle."""

    id: str = Field(default_factory=lambda: f"card_{uuid4().hex}")
    board: str = "default"
    title: str
    goal: str
    status: KanbanStatus = KanbanStatus.PENDING
    worker_pid: int | None = None
    claimed_at: datetime | None = None
    completed_at: datetime | None = None
    result: dict | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class KanbanStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def create(self, *, board: str = "default", title: str, goal: str) -> KanbanCard:
        card = KanbanCard(board=board, title=title, goal=goal)
        await self._insert(card)
        return card

    async def create_batch(self, *, board: str = "default", goals: list[dict]) -> list[KanbanCard]:
        """Create several PENDING cards in one call - the batch parallel
        dispatch VYOM was missing, mirroring Hermes's own
        delegate_task(tasks=[...]) batch form. Each goals[i] is
        {"title": optional, "goal": required}. All cards land as
        genuinely independent PENDING cards; the dispatcher (bounded by
        max_concurrent_workers) then claims and runs them as real,
        separate OS subprocesses - not sequentially, not as one big
        multi-step task."""
        cards: list[KanbanCard] = []
        for spec in goals:
            goal_text = spec["goal"]
            title = spec.get("title") or goal_text[:80]
            card = KanbanCard(board=board, title=title, goal=goal_text)
            await self._insert(card)
            cards.append(card)
        return cards

    async def _insert(self, card: KanbanCard) -> None:
        connection = self.database.require_connection()
        await connection.execute(
            "INSERT INTO kanban_cards(id, board, title, goal, status, worker_pid, claimed_at, "
            "completed_at, result_json, error, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                card.id, card.board, card.title, card.goal, card.status.value, card.worker_pid,
                card.claimed_at.isoformat() if card.claimed_at else None,
                card.completed_at.isoformat() if card.completed_at else None,
                json.dumps(card.result) if card.result is not None else None,
                card.error, card.created_at.isoformat(), card.updated_at.isoformat(),
            ),
        )
        await connection.commit()

    @staticmethod
    def _row_to_card(row) -> KanbanCard:
        return KanbanCard(
            id=row["id"], board=row["board"], title=row["title"], goal=row["goal"],
            status=KanbanStatus(row["status"]), worker_pid=row["worker_pid"],
            claimed_at=row["claimed_at"], completed_at=row["completed_at"],
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=row["error"], created_at=row["created_at"], updated_at=row["updated_at"],
        )

    async def get(self, card_id: str) -> KanbanCard | None:
        connection = self.database.require_connection()
        row = await (await connection.execute(
            "SELECT * FROM kanban_cards WHERE id = ?", (card_id,)
        )).fetchone()
        return self._row_to_card(row) if row else None

    async def list(self, *, board: str = "default", status: KanbanStatus | None = None, limit: int = 100) -> list[KanbanCard]:
        connection = self.database.require_connection()
        if status:
            rows = await (await connection.execute(
                "SELECT * FROM kanban_cards WHERE board = ? AND status = ? ORDER BY created_at DESC LIMIT ?",
                (board, status.value, limit),
            )).fetchall()
        else:
            rows = await (await connection.execute(
                "SELECT * FROM kanban_cards WHERE board = ? ORDER BY created_at DESC LIMIT ?",
                (board, limit),
            )).fetchall()
        return [self._row_to_card(row) for row in rows]

    async def claim_next(self, *, board: str = "default", worker_pid: int) -> KanbanCard | None:
        """Atomically claims the oldest PENDING card - the same
        single-writer-lock shape Hermes's dispatcher uses so two
        dispatcher ticks (or a race with a manual claim) can never claim
        the same card twice."""
        connection = self.database.require_connection()
        row = await (await connection.execute(
            "SELECT id FROM kanban_cards WHERE board = ? AND status = ? ORDER BY created_at ASC LIMIT 1",
            (board, KanbanStatus.PENDING.value),
        )).fetchone()
        if row is None:
            return None
        card_id = row["id"]
        now = utc_now().isoformat()
        cursor = await connection.execute(
            "UPDATE kanban_cards SET status = ?, worker_pid = ?, claimed_at = ?, updated_at = ? "
            "WHERE id = ? AND status = ?",
            (KanbanStatus.CLAIMED.value, worker_pid, now, now, card_id, KanbanStatus.PENDING.value),
        )
        await connection.commit()
        if cursor.rowcount == 0:
            # Lost the race to another claimant between SELECT and UPDATE.
            return None
        return await self.get(card_id)

    async def mark_in_progress(self, card_id: str) -> None:
        await self._set_status(card_id, KanbanStatus.IN_PROGRESS)

    async def complete(self, card_id: str, *, result: dict) -> None:
        connection = self.database.require_connection()
        now = utc_now().isoformat()
        await connection.execute(
            "UPDATE kanban_cards SET status = ?, result_json = ?, completed_at = ?, updated_at = ? WHERE id = ?",
            (KanbanStatus.COMPLETED.value, json.dumps(result), now, now, card_id),
        )
        await connection.commit()

    async def block(self, card_id: str, *, reason: str) -> None:
        connection = self.database.require_connection()
        now = utc_now().isoformat()
        await connection.execute(
            "UPDATE kanban_cards SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (KanbanStatus.BLOCKED.value, reason, now, card_id),
        )
        await connection.commit()

    async def fail(self, card_id: str, *, error: str) -> None:
        connection = self.database.require_connection()
        now = utc_now().isoformat()
        await connection.execute(
            "UPDATE kanban_cards SET status = ?, error = ?, updated_at = ? WHERE id = ?",
            (KanbanStatus.FAILED.value, error, now, card_id),
        )
        await connection.commit()

    async def _set_status(self, card_id: str, status: KanbanStatus) -> None:
        connection = self.database.require_connection()
        now = utc_now().isoformat()
        await connection.execute(
            "UPDATE kanban_cards SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, now, card_id),
        )
        await connection.commit()

    async def reclaim_stale(self, *, board: str = "default", older_than_seconds: float = 3600) -> list[str]:
        """Cards stuck in CLAIMED/IN_PROGRESS whose worker process is no
        longer alive (crash, kill, power loss) go back to PENDING so a
        later dispatcher tick can retry them - the same crash-recovery
        invariant VYOM's own TaskRuntime.resume_incomplete_tasks already
        applies to regular tasks, extended to kanban cards."""
        import os

        connection = self.database.require_connection()
        rows = await (await connection.execute(
            "SELECT id, worker_pid FROM kanban_cards WHERE board = ? AND status IN (?, ?)",
            (board, KanbanStatus.CLAIMED.value, KanbanStatus.IN_PROGRESS.value),
        )).fetchall()
        reclaimed: list[str] = []
        for row in rows:
            pid = row["worker_pid"]
            alive = False
            if pid:
                try:
                    os.kill(pid, 0)
                    alive = True
                except (OSError, ProcessLookupError, PermissionError):
                    alive = pid and _pid_alive_windows(pid)
            if not alive:
                await connection.execute(
                    "UPDATE kanban_cards SET status = ?, worker_pid = NULL, updated_at = ? WHERE id = ?",
                    (KanbanStatus.PENDING.value, utc_now().isoformat(), row["id"]),
                )
                reclaimed.append(row["id"])
        if reclaimed:
            await connection.commit()
        return reclaimed


def _pid_alive_windows(pid: int) -> bool:
    """os.kill(pid, 0) raises PermissionError on Windows even for a live
    process it can't signal - fall back to an explicit existence check
    so a live-but-unsignalable worker is never wrongly reclaimed."""
    try:
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        return False


class AgentMessageStore:
    """Agent-to-agent messaging between kanban workers - the
    single-Brain scoped equivalent of Hermes's tools/bot_relay.py
    message_agent. A worker (identified by its card_id) leaves a
    message for another card's worker to read on its next poll."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def send(self, *, from_card_id: str, to_card_id: str, content: str) -> str:
        connection = self.database.require_connection()
        message_id = f"msg_{uuid4().hex}"
        await connection.execute(
            "INSERT INTO agent_messages(id, from_card_id, to_card_id, content, delivered, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?)",
            (message_id, from_card_id, to_card_id, content, utc_now().isoformat()),
        )
        await connection.commit()
        return message_id

    async def inbox(self, card_id: str, *, mark_delivered: bool = True) -> list[dict]:
        """Undelivered messages for `card_id`, oldest first. Marks them
        delivered unless mark_delivered=False (e.g. a dry-run peek)."""
        connection = self.database.require_connection()
        rows = await (await connection.execute(
            "SELECT id, from_card_id, to_card_id, content, created_at FROM agent_messages "
            "WHERE to_card_id = ? AND delivered = 0 ORDER BY created_at ASC",
            (card_id,),
        )).fetchall()
        messages = [dict(row) for row in rows]
        if mark_delivered and messages:
            ids = [m["id"] for m in messages]
            placeholders = ",".join("?" for _ in ids)
            await connection.execute(
                f"UPDATE agent_messages SET delivered = 1 WHERE id IN ({placeholders})", tuple(ids)
            )
            await connection.commit()
        return messages

    async def history(self, card_id: str, *, limit: int = 100) -> list[dict]:
        """Every message sent OR received by card_id, including
        delivered ones - the inspectable audit trail."""
        connection = self.database.require_connection()
        rows = await (await connection.execute(
            "SELECT id, from_card_id, to_card_id, content, delivered, created_at FROM agent_messages "
            "WHERE from_card_id = ? OR to_card_id = ? ORDER BY created_at DESC LIMIT ?",
            (card_id, card_id, limit),
        )).fetchall()
        return [dict(row) for row in rows]
