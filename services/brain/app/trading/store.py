from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import JournalEntry, PaperOrder


class PaperOrderStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, order: PaperOrder) -> PaperOrder:
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO paper_orders(id, portfolio_id, status, order_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, order_json=excluded.order_json, updated_at=excluded.updated_at""",
            (
                order.order_id, order.portfolio_id, order.status.value, order.model_dump_json(),
                order.timestamp.isoformat(), datetime.now(timezone.utc).isoformat(),
            ),
        )
        await connection.commit()
        return order

    async def get(self, order_id: str) -> PaperOrder | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT order_json FROM paper_orders WHERE id = ?", (order_id,))).fetchone()
        return PaperOrder.model_validate_json(row["order_json"]) if row else None

    async def list(self, portfolio_id: str, status: str | None = None) -> list[PaperOrder]:
        connection = self.database.require_connection()
        if status:
            rows = await (await connection.execute(
                "SELECT order_json FROM paper_orders WHERE portfolio_id = ? AND status = ? ORDER BY created_at DESC",
                (portfolio_id, status),
            )).fetchall()
        else:
            rows = await (await connection.execute(
                "SELECT order_json FROM paper_orders WHERE portfolio_id = ? ORDER BY created_at DESC", (portfolio_id,)
            )).fetchall()
        return [PaperOrder.model_validate_json(row["order_json"]) for row in rows]


class JournalStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, entry: JournalEntry) -> JournalEntry:
        entry.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO trade_journal(id, setup_id, portfolio_id, journal_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               journal_json=excluded.journal_json, updated_at=excluded.updated_at""",
            (entry.id, entry.setup_id, entry.portfolio_id, entry.model_dump_json(), entry.created_at.isoformat(), entry.updated_at.isoformat()),
        )
        await connection.commit()
        return entry

    async def get(self, entry_id: str) -> JournalEntry | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT journal_json FROM trade_journal WHERE id = ?", (entry_id,))).fetchone()
        return JournalEntry.model_validate_json(row["journal_json"]) if row else None

    async def list(self, portfolio_id: str | None = None) -> list[JournalEntry]:
        connection = self.database.require_connection()
        if portfolio_id:
            rows = await (await connection.execute(
                "SELECT journal_json FROM trade_journal WHERE portfolio_id = ? ORDER BY created_at DESC", (portfolio_id,)
            )).fetchall()
        else:
            rows = await (await connection.execute("SELECT journal_json FROM trade_journal ORDER BY created_at DESC")).fetchall()
        return [JournalEntry.model_validate_json(row["journal_json"]) for row in rows]
