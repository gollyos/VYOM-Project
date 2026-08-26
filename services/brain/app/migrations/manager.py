from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    statements: tuple[str, ...]
    validation_query: str            # must return a truthy value after upgrade
    validation_expected: tuple = ()

    def validate(self, connection) -> bool:
        cursor = connection.execute(self.validation_query)
        row = cursor.fetchone()
        return row is not None and tuple(row) == self.validation_expected if self.validation_expected else row is not None


class MigrationError(Exception):
    pass


class MigrationManager:
    """Versioned database migrations. The production schema is never
    mutated ad hoc: every change is a Migration with an upgrade and a
    validation, applied inside a transaction, recorded in
    `schema_migrations`. A failed migration marks startup degraded —
    the Brain never continues pretending the database is healthy."""

    BASELINE = Migration(
        version=1,
        name="baseline_schema_v0",
        statements=(),  # baseline: the CREATE TABLE IF NOT EXISTS schema already applied by Database.connect
        validation_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('tasks','memories','automations','nodes','sync_journal')",
        validation_expected=(5,),
    )

    ADAPTIVE = Migration(
        version=2,
        name="adaptive_tables_v1",
        statements=(
            """CREATE TABLE IF NOT EXISTS experiences (
                experience_id TEXT PRIMARY KEY, task_id TEXT, domain TEXT NOT NULL,
                task_type TEXT NOT NULL, success INTEGER NOT NULL, failure_signature TEXT,
                strategy_id TEXT, experience_json TEXT NOT NULL, created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_experiences_domain ON experiences(domain, success)",
            """CREATE TABLE IF NOT EXISTS adaptive_strategies (
                strategy_id TEXT PRIMARY KEY, domain TEXT NOT NULL, name TEXT NOT NULL,
                version TEXT NOT NULL, status TEXT NOT NULL, strategy_json TEXT NOT NULL,
                updated_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_adaptive_strategies_domain ON adaptive_strategies(domain, status)",
            """CREATE TABLE IF NOT EXISTS environment_changes (
                change_id TEXT PRIMARY KEY, dimension TEXT NOT NULL, old_value TEXT,
                new_value TEXT, detected_at TEXT NOT NULL, change_json TEXT NOT NULL)""",
        ),
        validation_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('experiences','adaptive_strategies','environment_changes')",
        validation_expected=(3,),
    )

    BRAIN_GRAPH = Migration(
        version=3,
        name="unified_brain_graph_v1",
        statements=(
            """CREATE TABLE IF NOT EXISTS brain_nodes (
                entity_id TEXT PRIMARY KEY, entity_type TEXT NOT NULL,
                native_id TEXT NOT NULL, label TEXT NOT NULL, status TEXT,
                source_store TEXT NOT NULL, node_json TEXT NOT NULL,
                updated_at TEXT NOT NULL, origin TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_brain_nodes_type ON brain_nodes(entity_type, updated_at)",
            """CREATE TABLE IF NOT EXISTS brain_relationships (
                id TEXT PRIMARY KEY, source_id TEXT NOT NULL, target_id TEXT NOT NULL,
                relation TEXT NOT NULL, confidence REAL NOT NULL, verified INTEGER NOT NULL,
                origin TEXT NOT NULL, provenance TEXT NOT NULL, edge_json TEXT NOT NULL,
                created_at TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_brain_rel_source ON brain_relationships(source_id, relation)",
            "CREATE INDEX IF NOT EXISTS idx_brain_rel_target ON brain_relationships(target_id, relation)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_brain_rel_semantic ON brain_relationships(source_id, target_id, relation, origin)",
        ),
        validation_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name IN ('brain_nodes','brain_relationships')",
        validation_expected=(2,),
    )

    REMOTE_DELIVERY = Migration(
        version=4,
        name="authenticated_remote_delivery_v1",
        statements=(
            """CREATE TABLE IF NOT EXISTS remote_deliveries (
                delivery_id TEXT PRIMARY KEY, node_id TEXT NOT NULL, status TEXT NOT NULL,
                delivery_json TEXT NOT NULL, created_at TEXT NOT NULL, acknowledged_at TEXT)""",
            "CREATE INDEX IF NOT EXISTS idx_remote_deliveries_node ON remote_deliveries(node_id, status, created_at)",
        ),
        validation_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='remote_deliveries'",
        validation_expected=(1,),
    )

    KNOWLEDGE_BASE = Migration(
        version=5,
        name="knowledge_base_v1",
        statements=(
            """CREATE TABLE IF NOT EXISTS knowledge_facts (
                id TEXT PRIMARY KEY, subject TEXT NOT NULL, subject_key TEXT NOT NULL,
                predicate TEXT NOT NULL, value TEXT NOT NULL, source_url TEXT, source_title TEXT,
                confidence REAL NOT NULL, first_learned_at TEXT NOT NULL, last_confirmed_at TEXT NOT NULL,
                confirmations INTEGER NOT NULL, task_id TEXT, memory_id TEXT, fact_json TEXT NOT NULL)""",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_subject_key ON knowledge_facts(subject_key)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_confirmed ON knowledge_facts(last_confirmed_at)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_subject_predicate ON knowledge_facts(subject_key, predicate)",
        ),
        validation_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='knowledge_facts'",
        validation_expected=(1,),
    )

    MESSAGING = Migration(
        version=6,
        name="messaging_v1",
        statements=(
            """CREATE TABLE IF NOT EXISTS telegram_chats (
                chat_id TEXT PRIMARY KEY, title TEXT, updated_at TEXT NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS telegram_state (
                key TEXT PRIMARY KEY, value TEXT NOT NULL)""",
        ),
        validation_query="SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='telegram_chats'",
        validation_expected=(1,),
    )

    KNOWLEDGE_NAMESPACE = Migration(
        version=7,
        name="knowledge_namespace_v1",
        statements=(
            # Add a per-agent namespace column to knowledge_facts so each
            # distinct agent/task-type (research, coding, email, video,
            # market data, ...) accumulates its OWN 'wiki' that improves
            # independently, instead of every fact mixing into one pool.
            "ALTER TABLE knowledge_facts ADD COLUMN domain TEXT NOT NULL DEFAULT 'general'",
            # The old unique index was (subject_key, predicate) — that would
            # now wrongly forbid the SAME subject+predicate from existing in
            # two different domains. Replace it with a composite that scopes
            # the reconfirm key per-domain.
            "DROP INDEX IF EXISTS idx_knowledge_subject_predicate",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_knowledge_domain_subject_predicate ON knowledge_facts(domain, subject_key, predicate)",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_domain ON knowledge_facts(domain)",
        ),
        validation_query="SELECT COUNT(*) FROM pragma_table_info('knowledge_facts') WHERE name='domain'",
        validation_expected=(1,),
    )

    KNOWLEDGE_CONTRADICTION = Migration(
        version=8,
        name="knowledge_contradiction_v1",
        statements=(
            # Karpathy-style contradiction handling: when a re-record finds
            # a DIFFERENT value for the same (subject, predicate, domain),
            # VYOM no longer silently overwrites — it flags the conflict so
            # lint can surface it for review instead of dropping a real
            # discrepancy. Adds the two columns that carry that signal.
            "ALTER TABLE knowledge_facts ADD COLUMN contradicted INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE knowledge_facts ADD COLUMN contradiction_count INTEGER NOT NULL DEFAULT 0",
            "CREATE INDEX IF NOT EXISTS idx_knowledge_contradicted ON knowledge_facts(domain, contradicted)",
        ),
        validation_query="SELECT COUNT(*) FROM pragma_table_info('knowledge_facts') WHERE name='contradicted'",
        validation_expected=(1,),
    )

    KNOWLEDGE_LIFECYCLE = Migration(
        version=9,
        name="knowledge_lifecycle_v1",
        statements=(
            # The reel-prompted memory-lifecycle gap: a contradiction flag
            # never auto-resolved (a fact stayed "contradicted" forever
            # even after the world settled and every later source agreed
            # again), and there was no distinction between "this subject
            # was looked at again" (last_confirmed_at) and "the VALUE
            # actually changed" (new: value_changed_at). See
            # app/knowledge/schemas.py KnowledgeFact for the full design
            # note. value_changed_at backfills to first_learned_at for
            # existing rows - the honest "we don't know when it last
            # changed before this column existed, only when it was first
            # learned" default.
            "ALTER TABLE knowledge_facts ADD COLUMN value_changed_at TEXT",
            "ALTER TABLE knowledge_facts ADD COLUMN consistent_reconfirmations INTEGER NOT NULL DEFAULT 0",
            "UPDATE knowledge_facts SET value_changed_at = first_learned_at WHERE value_changed_at IS NULL",
        ),
        validation_query="SELECT COUNT(*) FROM pragma_table_info('knowledge_facts') WHERE name='value_changed_at'",
        validation_expected=(1,),
    )

    def __init__(self, database, migrations: list[Migration] | None = None):
        self.database = database
        self.migrations = sorted(migrations or [self.BASELINE, self.ADAPTIVE, self.BRAIN_GRAPH, self.REMOTE_DELIVERY, self.KNOWLEDGE_BASE, self.MESSAGING, self.KNOWLEDGE_NAMESPACE, self.KNOWLEDGE_CONTRADICTION, self.KNOWLEDGE_LIFECYCLE], key=lambda item: item.version)
        self.last_error: str | None = None

    async def ensure_table(self) -> None:
        connection = self.database.require_connection()
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        await connection.commit()

    async def applied_versions(self) -> list[int]:
        await self.ensure_table()
        connection = self.database.require_connection()
        cursor = await connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        return [int(row["version"]) for row in await cursor.fetchall()]

    async def apply_pending(self) -> dict:
        applied = await self.applied_versions()
        results = {"applied": [], "already_applied": applied, "failed": None}
        connection = self.database.require_connection()
        for migration in self.migrations:
            if migration.version in applied:
                continue
            try:
                for statement in migration.statements:
                    await connection.execute(statement)
                await connection.commit()
                if not self._validate_sync(migration):
                    raise MigrationError(f"Migration v{migration.version} ({migration.name}) failed its validation query")
                await connection.execute(
                    "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration.version, migration.name, datetime.now(timezone.utc).isoformat()),
                )
                await connection.commit()
                results["applied"].append({"version": migration.version, "name": migration.name})
            except Exception as error:
                await connection.rollback()
                self.last_error = str(error)
                results["failed"] = {"version": migration.version, "name": migration.name, "error": str(error)}
                break
        return results

    def _validate_sync(self, migration: Migration) -> bool:
        import sqlite3

        connection = sqlite3.connect(self.database.path)
        try:
            cursor = connection.execute(migration.validation_query)
            row = cursor.fetchone()
            if migration.validation_expected:
                return tuple(row) == migration.validation_expected
            return row is not None
        finally:
            connection.close()

    async def status(self) -> dict:
        applied = await self.applied_versions()
        pending = [m.version for m in self.migrations if m.version not in applied]
        return {
            "current_version": max(applied) if applied else 0,
            "latest_version": self.migrations[-1].version,
            "pending": pending,
            "last_error": self.last_error,
        }
