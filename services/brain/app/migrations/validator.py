from __future__ import annotations

import sqlite3

REQUIRED_TABLES = (
    "tasks", "model_performance", "memories", "memory_relationships",
    "brain_nodes", "brain_relationships",
    "integrations", "crm_records", "email_drafts", "automations", "automation_runs",
    "meeting_notes", "booking_requests", "artifacts", "delivery_packages",
    "portfolios", "watchlists", "paper_orders", "trade_journal", "strategies",
    "backtest_results", "market_alerts", "personal_profile", "commitments",
    "goals", "milestones", "habits", "habit_events", "routines", "routine_runs",
    "focus_sessions", "proactive_suggestions", "notification_records",
    "nodes", "node_tokens", "task_leases", "task_checkpoints", "sync_journal",
    "sync_conflicts", "offline_commands", "remote_commands", "remote_sessions", "remote_deliveries",
    "distributed_audit", "backup_records", "idempotency_records", "budget_usage",
    "schema_migrations",
)


class SchemaValidator:
    """Validates the database schema matches the expected table set and
    that the schema version is compatible with this build."""

    @staticmethod
    def validate(database_path) -> dict:
        connection = sqlite3.connect(database_path)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            rows = connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            present = {row[0] for row in rows}
            missing = [table for table in REQUIRED_TABLES if table not in present]
            version_row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone() if "schema_migrations" in present else (0,)
            return {
                "integrity": integrity,
                "missing_tables": missing,
                "schema_version": int(version_row[0]),
                "valid": integrity == "ok" and not missing,
            }
        finally:
            connection.close()
