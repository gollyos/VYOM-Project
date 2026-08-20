from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .schemas import Alert


class AlertStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def save(self, alert: Alert) -> Alert:
        alert.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO market_alerts(id, status, alert_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
               status=excluded.status, alert_json=excluded.alert_json, updated_at=excluded.updated_at""",
            (alert.id, alert.status.value, alert.model_dump_json(), alert.created_at.isoformat(), alert.updated_at.isoformat()),
        )
        await connection.commit()
        return alert

    async def get(self, alert_id: str) -> Alert | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT alert_json FROM market_alerts WHERE id = ?", (alert_id,))).fetchone()
        return Alert.model_validate_json(row["alert_json"]) if row else None

    async def list(self, *, enabled_only: bool = False) -> list[Alert]:
        connection = self.database.require_connection()
        if enabled_only:
            rows = await (await connection.execute("SELECT alert_json FROM market_alerts WHERE status = 'enabled' ORDER BY created_at DESC")).fetchall()
        else:
            rows = await (await connection.execute("SELECT alert_json FROM market_alerts ORDER BY created_at DESC")).fetchall()
        return [Alert.model_validate_json(row["alert_json"]) for row in rows]
