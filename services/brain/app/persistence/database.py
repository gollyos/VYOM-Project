from __future__ import annotations

from pathlib import Path

import aiosqlite


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        self.connection.row_factory = aiosqlite.Row
        await self.connection.execute("PRAGMA journal_mode=WAL")
        await self.connection.execute("PRAGMA foreign_keys=ON")
        await self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                task_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);

            CREATE TABLE IF NOT EXISTS model_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                model TEXT NOT NULL,
                provider TEXT NOT NULL,
                task_domain TEXT NOT NULL,
                complexity INTEGER NOT NULL,
                success INTEGER NOT NULL,
                verification_score REAL NOT NULL,
                latency_ms REAL NOT NULL,
                retries INTEGER NOT NULL,
                fallback_used INTEGER NOT NULL,
                usage_json TEXT NOT NULL,
                estimated_cost REAL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_performance_model_domain
                ON model_performance(model, task_domain);

            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                content TEXT NOT NULL,
                project_id TEXT,
                client_id TEXT,
                task_id TEXT,
                agent_id TEXT,
                sensitivity TEXT NOT NULL,
                verification_state TEXT NOT NULL,
                importance REAL NOT NULL,
                confidence REAL NOT NULL,
                memory_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_accessed_at TEXT NOT NULL,
                expires_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_memories_type_project
                ON memories(type, project_id);
            CREATE INDEX IF NOT EXISTS idx_memories_client
                ON memories(client_id);
            CREATE INDEX IF NOT EXISTS idx_memories_updated
                ON memories(updated_at);
            CREATE INDEX IF NOT EXISTS idx_memories_created
                ON memories(created_at);

            CREATE TABLE IF NOT EXISTS memory_relationships (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                relation TEXT NOT NULL,
                confidence REAL NOT NULL,
                relationship_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(source_id) REFERENCES memories(id) ON DELETE CASCADE,
                FOREIGN KEY(target_id) REFERENCES memories(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_relationship_source
                ON memory_relationships(source_id, relation);
            CREATE INDEX IF NOT EXISTS idx_relationship_target
                ON memory_relationships(target_id, relation);

            CREATE TABLE IF NOT EXISTS integrations (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                state_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS crm_records (
                id TEXT PRIMARY KEY,
                record_type TEXT NOT NULL,
                normalized_key TEXT NOT NULL,
                record_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(record_type, normalized_key)
            );
            CREATE INDEX IF NOT EXISTS idx_crm_type ON crm_records(record_type);

            CREATE TABLE IF NOT EXISTS email_drafts (
                id TEXT PRIMARY KEY,
                thread_id TEXT,
                status TEXT NOT NULL,
                draft_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS automations (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                next_run_at TEXT,
                automation_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_automations_due
                ON automations(status, next_run_at);

            CREATE TABLE IF NOT EXISTS automation_runs (
                id TEXT PRIMARY KEY,
                automation_id TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL,
                run_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY(automation_id) REFERENCES automations(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_automation_runs_parent
                ON automation_runs(automation_id, started_at);

            CREATE TABLE IF NOT EXISTS meeting_notes (
                event_id TEXT PRIMARY KEY,
                notes_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS booking_requests (
                id TEXT PRIMARY KEY,
                category TEXT NOT NULL,
                status TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                request_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS idx_booking_category_status
                ON booking_requests(category, status);

            CREATE TABLE IF NOT EXISTS artifacts (
                id TEXT PRIMARY KEY,
                artifact_type TEXT NOT NULL,
                task_id TEXT,
                version TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_artifacts_task ON artifacts(task_id);

            CREATE TABLE IF NOT EXISTS delivery_packages (
                id TEXT PRIMARY KEY,
                client TEXT NOT NULL,
                project TEXT NOT NULL,
                version TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                package_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(dedupe_key)
            );
            CREATE INDEX IF NOT EXISTS idx_delivery_client_project
                ON delivery_packages(client, project);

            CREATE TABLE IF NOT EXISTS portfolios (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                portfolio_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_portfolios_kind ON portfolios(kind);

            CREATE TABLE IF NOT EXISTS watchlists (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                watchlist_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS paper_orders (
                id TEXT PRIMARY KEY,
                portfolio_id TEXT NOT NULL,
                status TEXT NOT NULL,
                order_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_paper_orders_portfolio ON paper_orders(portfolio_id, status);

            CREATE TABLE IF NOT EXISTS trade_journal (
                id TEXT PRIMARY KEY,
                setup_id TEXT,
                portfolio_id TEXT,
                journal_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_journal_portfolio ON trade_journal(portfolio_id);

            CREATE TABLE IF NOT EXISTS strategies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT NOT NULL,
                strategy_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(name, version)
            );
            CREATE INDEX IF NOT EXISTS idx_strategies_name ON strategies(name);

            CREATE TABLE IF NOT EXISTS backtest_results (
                id TEXT PRIMARY KEY,
                strategy_id TEXT,
                strategy_name TEXT,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_name);

            CREATE TABLE IF NOT EXISTS market_alerts (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                alert_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_alerts_status ON market_alerts(status);

            CREATE TABLE IF NOT EXISTS personal_profile (
                id TEXT PRIMARY KEY,
                profile_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS commitments (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                deadline TEXT,
                commitment_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status, deadline);

            CREATE TABLE IF NOT EXISTS goals (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                category TEXT NOT NULL,
                goal_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_goals_status ON goals(status);

            CREATE TABLE IF NOT EXISTS milestones (
                id TEXT PRIMARY KEY,
                goal_id TEXT NOT NULL,
                status TEXT NOT NULL,
                milestone_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_milestones_goal ON milestones(goal_id);

            CREATE TABLE IF NOT EXISTS habits (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                habit_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_habits_status ON habits(status);

            CREATE TABLE IF NOT EXISTS habit_events (
                id TEXT PRIMARY KEY,
                habit_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_habit_events_habit ON habit_events(habit_id, timestamp);

            CREATE TABLE IF NOT EXISTS routines (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                enabled INTEGER NOT NULL,
                routine_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS routine_runs (
                id TEXT PRIMARY KEY,
                routine_id TEXT NOT NULL,
                status TEXT NOT NULL,
                run_json TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_routine_runs_routine ON routine_runs(routine_id, started_at);

            CREATE TABLE IF NOT EXISTS focus_sessions (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                session_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proactive_suggestions (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                dedupe_key TEXT NOT NULL,
                suggestion_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                surfaced_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_proactive_dedupe ON proactive_suggestions(dedupe_key, created_at);

            CREATE TABLE IF NOT EXISTS notification_records (
                id TEXT PRIMARY KEY,
                priority TEXT NOT NULL,
                outcome TEXT,
                notification_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_notification_priority ON notification_records(priority, created_at);

            -- Phase 12: persistent multi-device runtime -------------------

            CREATE TABLE IF NOT EXISTS nodes (
                node_id TEXT PRIMARY KEY,
                trust_level TEXT NOT NULL,
                node_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_trust ON nodes(trust_level);

            CREATE TABLE IF NOT EXISTS node_tokens (
                node_id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL,
                rotated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_leases (
                task_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                lease_id TEXT NOT NULL,
                acquired_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                heartbeat_at TEXT NOT NULL,
                lease_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_task_leases_node ON task_leases(node_id);

            CREATE TABLE IF NOT EXISTS task_checkpoints (
                task_id TEXT PRIMARY KEY,
                checkpoint_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sync_journal (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                entity TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                origin_node TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                occurred_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sync_journal_entity
                ON sync_journal(entity, entity_id, seq);

            CREATE TABLE IF NOT EXISTS sync_conflicts (
                id TEXT PRIMARY KEY,
                entity TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                resolution TEXT NOT NULL,
                conflict_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sync_conflicts_entity
                ON sync_conflicts(entity, entity_id);

            CREATE TABLE IF NOT EXISTS offline_commands (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                command_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                submitted_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_offline_commands_status
                ON offline_commands(status, expires_at);

            CREATE TABLE IF NOT EXISTS remote_commands (
                command_id TEXT PRIMARY KEY,
                source_node TEXT NOT NULL,
                nonce TEXT NOT NULL,
                status TEXT NOT NULL,
                command_json TEXT NOT NULL,
                received_at TEXT NOT NULL,
                UNIQUE(nonce)
            );

            CREATE TABLE IF NOT EXISTS remote_sessions (
                session_id TEXT PRIMARY KEY,
                node_id TEXT NOT NULL,
                state_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS distributed_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                node_id TEXT,
                action TEXT NOT NULL,
                result TEXT NOT NULL,
                evidence TEXT,
                recorded_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_distributed_audit_task
                ON distributed_audit(task_id, recorded_at);

            CREATE TABLE IF NOT EXISTS backup_records (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                kind TEXT NOT NULL,
                manifest_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS idempotency_records (
                action_key TEXT PRIMARY KEY,
                task_id TEXT,
                node_id TEXT,
                result_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS budget_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                budget_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(day)
            );

            -- Phase 14: adaptive cognitive layer -------------------------

            CREATE TABLE IF NOT EXISTS experiences (
                experience_id TEXT PRIMARY KEY,
                task_id TEXT,
                domain TEXT NOT NULL,
                task_type TEXT NOT NULL,
                success INTEGER NOT NULL,
                failure_signature TEXT,
                strategy_id TEXT,
                experience_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_experiences_domain
                ON experiences(domain, success);
            CREATE INDEX IF NOT EXISTS idx_experiences_failure
                ON experiences(failure_signature);

            CREATE TABLE IF NOT EXISTS adaptive_strategies (
                strategy_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                name TEXT NOT NULL,
                version TEXT NOT NULL,
                status TEXT NOT NULL,
                strategy_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_adaptive_strategies_domain
                ON adaptive_strategies(domain, status);

            CREATE TABLE IF NOT EXISTS environment_changes (
                change_id TEXT PRIMARY KEY,
                dimension TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                detected_at TEXT NOT NULL,
                change_json TEXT NOT NULL
            );
            """
        )
        await self.connection.commit()

    async def close(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    def require_connection(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Database is not connected")
        return self.connection
