from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import BookingRequest


class BookingStore:
    """Persists booking requests keyed by a stable idempotency key so that
    retries/restarts never silently create a duplicate reservation."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, request: BookingRequest) -> BookingRequest:
        request.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO booking_requests(id, category, status, idempotency_key, request_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(idempotency_key) DO UPDATE SET
               id=excluded.id, category=excluded.category, status=excluded.status,
               request_json=excluded.request_json, updated_at=excluded.updated_at""",
            (
                request.id, request.category.value, request.status.value, request.idempotency_key,
                request.model_dump_json(), request.created_at.isoformat(), request.updated_at.isoformat(),
            ),
        )
        await connection.commit()
        return request

    async def get(self, booking_id: str) -> BookingRequest:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT request_json FROM booking_requests WHERE id = ?", (booking_id,))).fetchone()
        if row is None:
            raise KeyError(booking_id)
        return BookingRequest.model_validate_json(row["request_json"])

    async def find_by_idempotency_key(self, idempotency_key: str) -> BookingRequest | None:
        connection = self.database.require_connection()
        row = await (await connection.execute(
            "SELECT request_json FROM booking_requests WHERE idempotency_key = ?", (idempotency_key,)
        )).fetchone()
        return BookingRequest.model_validate_json(row["request_json"]) if row else None

    async def list(self, category: str | None = None) -> list[BookingRequest]:
        connection = self.database.require_connection()
        if category:
            rows = await (await connection.execute(
                "SELECT request_json FROM booking_requests WHERE category = ? ORDER BY updated_at DESC", (category,)
            )).fetchall()
        else:
            rows = await (await connection.execute("SELECT request_json FROM booking_requests ORDER BY updated_at DESC")).fetchall()
        return [BookingRequest.model_validate_json(row["request_json"]) for row in rows]
