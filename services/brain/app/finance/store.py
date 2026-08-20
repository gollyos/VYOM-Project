from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import Portfolio, Watchlist


class PortfolioStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, portfolio: Portfolio) -> Portfolio:
        portfolio.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO portfolios(id, name, kind, portfolio_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, kind=excluded.kind, portfolio_json=excluded.portfolio_json, updated_at=excluded.updated_at""",
            (
                portfolio.id, portfolio.name, portfolio.kind.value, portfolio.model_dump_json(),
                portfolio.created_at.isoformat(), portfolio.updated_at.isoformat(),
            ),
        )
        await connection.commit()
        return portfolio

    async def get(self, portfolio_id: str) -> Portfolio | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT portfolio_json FROM portfolios WHERE id = ?", (portfolio_id,))).fetchone()
        return Portfolio.model_validate_json(row["portfolio_json"]) if row else None

    async def list(self, kind: str | None = None) -> list[Portfolio]:
        connection = self.database.require_connection()
        if kind:
            rows = await (await connection.execute("SELECT portfolio_json FROM portfolios WHERE kind = ? ORDER BY updated_at DESC", (kind,))).fetchall()
        else:
            rows = await (await connection.execute("SELECT portfolio_json FROM portfolios ORDER BY updated_at DESC")).fetchall()
        return [Portfolio.model_validate_json(row["portfolio_json"]) for row in rows]


class WatchlistStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, watchlist: Watchlist) -> Watchlist:
        watchlist.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO watchlists(id, name, watchlist_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               name=excluded.name, watchlist_json=excluded.watchlist_json, updated_at=excluded.updated_at""",
            (watchlist.id, watchlist.name, watchlist.model_dump_json(), watchlist.created_at.isoformat(), watchlist.updated_at.isoformat()),
        )
        await connection.commit()
        return watchlist

    async def get(self, watchlist_id: str) -> Watchlist | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT watchlist_json FROM watchlists WHERE id = ?", (watchlist_id,))).fetchone()
        return Watchlist.model_validate_json(row["watchlist_json"]) if row else None

    async def get_by_name(self, name: str) -> Watchlist | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT watchlist_json FROM watchlists WHERE name = ?", (name,))).fetchone()
        return Watchlist.model_validate_json(row["watchlist_json"]) if row else None

    async def list(self) -> list[Watchlist]:
        connection = self.database.require_connection()
        rows = await (await connection.execute("SELECT watchlist_json FROM watchlists ORDER BY updated_at DESC")).fetchall()
        return [Watchlist.model_validate_json(row["watchlist_json"]) for row in rows]

    async def get_or_create(self, name: str) -> Watchlist:
        existing = await self.get_by_name(name)
        if existing is not None:
            return existing
        return await self.save(Watchlist(name=name))
