from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from app.backup import (
    BackupKind,
    BackupManager,
    InvalidBackupError,
    RestoreService,
    SnapshotService,
)
from app.devices.heartbeat import HeartbeatMonitor
from app.devices.registry import DeviceRegistry
from app.devices.schemas import (
    DeviceCapability,
    DeviceNode,
    DeviceType,
    NodeRole,
    NodeVersionInfo,
    utc_now,
)
from app.distributed import (
    DistributedAuditLog,
    DistributedCoordinator,
    LeaseManager,
    TaskRequirements,
)
from app.persistence.database import Database
from app.reliability import CheckpointStore, HealthAggregator, HealthState, ReliabilityMetrics, Supervisor
from app.remote import (
    ApprovalExpiredError,
    RemoteApprovalService,
    RemoteCommandEnvelope,
    RemoteCommandGateway,
    RemoteNotificationRouter,
    RemoteSessionManager,
    StrongVerificationRequired,
)
from app.sync import (
    ConflictResolver,
    OfflineCommandQueue,
    ReplicationManager,
    SyncEngine,
    SyncEntity,
    SyncJournal,
    SyncRecord,
)


@pytest.fixture
async def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "phase12-sync.db")
    await db.connect()
    yield db
    await db.close()


def mobile_node(node_id="mobile-1"):
    node = DeviceNode(
        name="Phone", device_type=DeviceType.MOBILE, platform="android",
        capabilities=[DeviceCapability.NOTIFICATIONS_SEND, DeviceCapability.VOICE],
        roles=[NodeRole.CLIENT_DEVICE],
        version_info=NodeVersionInfo(),
    )
    node.node_id = node_id
    return node


# --- sync journal -----------------------------------------------------------


async def test_journal_append_and_pull_since(database):
    journal = SyncJournal(database)
    first = await journal.record_state_change(SyncEntity.TASK, "t1", {"status": "queued"})
    second = await journal.record_state_change(SyncEntity.TASK, "t2", {"status": "completed"})
    assert (first.seq or 0) < (second.seq or 0)
    pulled = await journal.since(first.seq or 0)
    assert [record.entity_id for record in pulled] == ["t2"]
    assert await journal.latest_seq() == second.seq


# --- conflict resolution ------------------------------------------------------


async def test_goal_conflict_field_merge_flags_overlapping_edits(database):
    resolver = ConflictResolver(database)
    base = {"title": "Launch Finora", "priority": "medium", "progress": 0.1}
    local = {**base, "priority": "high", "_base": base}          # edited priority on desktop
    remote = {**base, "progress": 0.5, "_base": base}            # edited progress on mobile
    conflict = await resolver.resolve(SyncEntity.GOAL, "goal-1", local, remote)
    resolved = conflict.resolved_payload
    assert resolved["progress"] == 0.5  # only edited remotely -> merged
    assert resolved["priority"] == "high"  # only edited locally -> kept

    overlapping_local = {**base, "priority": "high", "_base": base}
    overlapping_remote = {**base, "priority": "low", "_base": base}
    overlapping = await resolver.resolve(SyncEntity.GOAL, "goal-2", overlapping_local, overlapping_remote)
    assert "priority" in overlapping.resolution  # edited on both -> flagged, coordinator value kept


async def test_task_terminal_state_wins_not_last_write(database):
    resolver = ConflictResolver(database)
    conflict = await resolver.resolve(
        SyncEntity.TASK, "t1",
        {"status": "completed"},
        {"status": "executing", "updated": "later"},
    )
    assert conflict.resolved_payload["status"] == "completed"


async def test_conflicts_are_persisted_for_review(database):
    resolver = ConflictResolver(database)
    await resolver.resolve(SyncEntity.APPROVAL, "a1", {"decision": "approve"}, {"decision": "reject"})
    cursor = await database.require_connection().execute("SELECT conflict_json FROM sync_conflicts")
    rows = await cursor.fetchall()
    assert len(rows) == 1


# --- sync engine + freshness ---------------------------------------------------


async def test_sync_pull_applies_records_and_emits_conflict_events(database, tmp_path):
    from app.runtime.event_bus import EventBus

    peer_database = Database(tmp_path / "peer.db")
    await peer_database.connect()
    try:
        bus = EventBus()
        peer = SyncJournal(peer_database, origin_node="desktop")
        local = SyncEngine(SyncJournal(database, origin_node="brain-local"), ConflictResolver(database), bus)
        await peer.record_state_change(SyncEntity.TASK, "t1", {"status": "completed"})
        await local.journal.record_state_change(SyncEntity.TASK, "t1", {"status": "executing"})

        async def local_state(record):
            return {"status": "executing"} if record.entity_id == "t1" else None

        result = await local.pull(peer, since_seq=0, applier=local_state)
        assert result["pulled"] == 1
        assert result["conflicts"]
        assert any(event.type.value == "sync_conflict" for event in bus.history)
    finally:
        await peer_database.close()


async def test_freshness_flags_stale_cache():
    engine = SyncEngine(SyncJournal.__new__(SyncJournal), ConflictResolver())
    fresh = await engine.freshness(SyncEntity.TASK, {}, as_of=utc_now())
    assert not fresh.stale
    stale = await engine.freshness(SyncEntity.TASK, {}, as_of=utc_now() - timedelta(seconds=60))
    assert stale.stale  # mobile must never show this as live "running" state


# --- offline queue ----------------------------------------------------------------


async def test_offline_queue_submits_safe_command_exactly_once(database):
    queue = OfflineCommandQueue(database)
    await queue.enqueue({"command": "What is my status today?", "id": "q1"})
    submitted = []
    first = await queue.submit_due(lambda record: submitted.append(record["id"]) or {"ok": True})
    second = await queue.submit_due(lambda record: submitted.append(record["id"]) or {"ok": True})
    assert submitted == ["q1"]
    assert first[0]["executed"] and second == []


async def test_expired_consequential_offline_command_never_executes(database):
    queue = OfflineCommandQueue(database)
    record = await queue.enqueue({"command": "Send email to the client", "id": "q2"})
    assert record["consequential"] and record["requires_reconfirmation"]
    # age it past the 5-minute consequential TTL
    await database.require_connection().execute(
        "UPDATE offline_commands SET expires_at = ?", ((utc_now() - timedelta(seconds=1)).isoformat(),)
    )
    await database.require_connection().commit()
    results = await queue.submit_due(lambda record: {"ok": True})
    assert results[0]["executed"] is False
    assert results[0]["reason"] in {"expired", "reconfirmation_required"}


async def test_fresh_consequential_command_requires_reconfirmation(database):
    queue = OfflineCommandQueue(database)
    await queue.enqueue({"command": "Send email to the client", "id": "q3"})
    results = await queue.submit_due(lambda record: {"ok": True})
    assert results[0]["executed"] is False
    assert results[0]["reason"] == "reconfirmation_required"


# --- replication ------------------------------------------------------------------


async def test_replication_limits_mobile_entities_and_defers_poor_network(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    phone = mobile_node()
    phone.presence.network_type = "cellular"
    registry.heartbeat.record(phone.node_id)
    registry.register(phone)
    journal = SyncJournal(database)
    await journal.record_state_change(SyncEntity.MEMORY_METADATA, "m1", {"title": "private"})
    replication = ReplicationManager(registry, journal)
    snapshot = await replication.snapshot_for(phone.node_id)
    assert snapshot["deferred"] and "network" in snapshot["reason"]
    phone.presence.network_type = "wifi"
    snapshot = await replication.snapshot_for(phone.node_id)
    assert not snapshot["deferred"]
    entities = {record["entity"] for record in snapshot["records"]}
    assert entities <= {"tasks", "approvals", "notifications", "device_states", "automations", "goals"}
    assert "memory_metadata" not in entities  # private metadata never replicates to mobile


# --- notification routing + dedup --------------------------------------------------


async def test_notification_routing_by_priority_and_quiet_mode(database):
    router = RemoteNotificationRouter(SyncJournal(database))
    urgent = router.route("Approval needed", "Client email requires approval", "urgent")
    assert set(urgent.destinations) == {"desktop", "mobile"}
    info = router.route("Task done", "Research finished", "info")
    assert info.destinations == ["desktop"]
    quiet = router.route("Approval needed", "x", "urgent", quiet_mode=True)
    assert quiet.destinations == ["quiet_queue"]


async def test_push_payload_sanitizes_sensitive_content():
    router = RemoteNotificationRouter(SyncJournal.__new__(SyncJournal))
    title, body = router.sanitize_for_push("Client action", "Password for the client portal is hunter2")
    assert "hunter2" not in body


async def test_notification_read_state_syncs_through_journal(database):
    journal = SyncJournal(database)
    router = RemoteNotificationRouter(journal)
    await router.record_state("n1", "read")
    await router.record_state("n1", "acted_on")
    records = await journal.since(0)
    states = [record.payload.get("state") for record in records if record.entity == SyncEntity.NOTIFICATION]
    assert states == ["read", "acted_on"]  # desktop sees mobile's read


# --- remote sessions + command gateway ---------------------------------------------


def build_gateway(database, registry, sessions, bus=None):
    from app.runtime.event_bus import EventBus

    return RemoteCommandGateway(
        database, registry, sessions, DistributedAuditLog(database),
        event_bus=bus or EventBus(),
    )


async def test_command_rejected_for_unknown_and_untrusted_nodes(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    sessions = RemoteSessionManager(database)
    gateway = build_gateway(database, registry, sessions)
    untrusted = mobile_node("m-untrusted")
    registry.heartbeat.record(untrusted.node_id)
    registry.register(untrusted)
    session = await sessions.open(untrusted.node_id)

    from app.remote.command_gateway import CommandRejected

    with pytest.raises(CommandRejected) as unknown:
        await gateway.submit(RemoteCommandEnvelope(command="status", source_node="ghost", session_id="x"))
    assert unknown.value.status_code == 404
    with pytest.raises(CommandRejected) as rejected:
        await gateway.submit(RemoteCommandEnvelope(command="status", source_node="m-untrusted", session_id=session.session_id))
    assert "not trusted" in rejected.value.reason


async def test_command_replay_rejected_via_nonce(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    sessions = RemoteSessionManager(database)
    gateway = build_gateway(database, registry, sessions)
    phone = mobile_node("m-auth")
    phone.trust_level = phone.trust_level.__class__.TRUSTED
    registry.heartbeat.record(phone.node_id)
    registry.register(phone)
    session = await sessions.open(phone.node_id)

    envelope = RemoteCommandEnvelope(command="What's happening?", source_node="m-auth", session_id=session.session_id)
    accepted = await gateway.submit(envelope)
    assert accepted["accepted"]
    from app.remote.command_gateway import CommandRejected

    with pytest.raises(CommandRejected) as replay:
        await gateway.submit(envelope)  # same nonce = replay
    assert "Replay" in replay.value.reason


async def test_expired_command_timestamp_rejected(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    sessions = RemoteSessionManager(database)
    gateway = build_gateway(database, registry, sessions)
    phone = mobile_node("m-old")
    from app.devices.schemas import DeviceTrustLevel

    phone.trust_level = DeviceTrustLevel.TRUSTED
    registry.heartbeat.record(phone.node_id)
    registry.register(phone)
    session = await sessions.open(phone.node_id)
    stale = RemoteCommandEnvelope(
        command="status", source_node="m-old", session_id=session.session_id,
        timestamp=utc_now() - timedelta(seconds=600),
    )
    from app.remote.command_gateway import CommandRejected

    with pytest.raises(CommandRejected) as rejected:
        await gateway.submit(stale)
    assert "window" in rejected.value.reason


async def test_session_context_and_node_invalidation(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    sessions = RemoteSessionManager(database)
    phone = mobile_node("m-ctx")
    registry.register(phone)
    session = await sessions.open(phone.node_id)
    await sessions.update_context(session.session_id, active_task_id="task-9", last_command="research competitors")
    context = sessions.context_for_node(phone.node_id)
    assert context.active_task_id == "task-9"
    assert context.last_command == "research competitors"
    invalidated = await sessions.invalidate_node(phone.node_id)
    assert invalidated == 1
    assert sessions.get(session.session_id) is None


# --- remote approvals ---------------------------------------------------------------


async def test_remote_approval_lifecycle_with_l3_step_up(database):
    from tests.helpers import build_runtime, close_harness
    from app.schemas.tasks import Task, TaskStatus
    from app.schemas.approvals import PermissionLevel
    from app.runtime.event_bus import EventBus

    harness = await build_runtime(database.path.parent / "approvals.db")
    try:
        audit = DistributedAuditLog(harness.database)
        bus = EventBus()
        service = RemoteApprovalService(harness.task_store, harness.runtime, audit, bus)

        def approval_task(task_id, level, created_at):
            task = Task(goal="g", user_request="Send the contract")
            task.id = task_id
            task.status = TaskStatus.NEEDS_APPROVAL
            task.permission_level = level
            task.metadata["approval"] = {
                "reason": "Send contract via email", "permission_level": level.value,
                "created_at": created_at.isoformat(),
                "expires_at": (created_at + timedelta(seconds=1800)).isoformat(),
            }
            return task

        l2 = approval_task("approve-l2", PermissionLevel.L2, utc_now())
        await harness.task_store.save(l2)
        pending = await service.pending()
        assert any(view.task_id == "approve-l2" for view in pending)
        view = next(v for v in pending if v.task_id == "approve-l2")
        assert view.evidence is not None

        result = await service.decide("approve-l2", "reject", node_id="m-auth")
        assert result["decision"] == "rejected"

        l3 = approval_task("approve-l3", PermissionLevel.L3, utc_now())
        await harness.task_store.save(l3)
        with pytest.raises(StrongVerificationRequired):
            await service.decide("approve-l3", "approve", node_id="m-auth")
        decision = await service.decide("approve-l3", "approve", node_id="m-auth", strong_verification=True)
        assert decision["decision"] == "approved"
    finally:
        await close_harness(harness)


async def test_expired_approval_requires_reevaluation(database):
    from tests.helpers import build_runtime, close_harness
    from app.schemas.tasks import Task, TaskStatus
    from app.schemas.approvals import PermissionLevel

    harness = await build_runtime(database.path.parent / "expired.db")
    try:
        service = RemoteApprovalService(
            harness.task_store, harness.runtime, DistributedAuditLog(harness.database), None,
            approval_ttl_seconds=60,
        )
        task = Task(goal="g", user_request="Book the flight")
        task.id = "approve-old"
        task.status = TaskStatus.NEEDS_APPROVAL
        task.permission_level = PermissionLevel.L2
        created = utc_now() - timedelta(seconds=120)
        task.metadata["approval"] = {
            "reason": "Book flight", "permission_level": "L2",
            "created_at": created.isoformat(),
            "expires_at": (created + timedelta(seconds=60)).isoformat(),
        }
        await harness.task_store.save(task)
        with pytest.raises(ApprovalExpiredError):
            await service.decide("approve-old", "approve", node_id="m-auth")
    finally:
        await close_harness(harness)


# --- backups -------------------------------------------------------------------------


def configure_backup_paths(tmp_path: Path):
    database_path = tmp_path / "brain.db"
    import sqlite3

    connection = sqlite3.connect(database_path)
    connection.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY, status TEXT)")
    connection.execute("INSERT INTO tasks VALUES ('t1', 'completed')")
    connection.commit()
    connection.close()
    data_root = tmp_path / "data"
    (data_root / "skills").mkdir(parents=True)
    (data_root / "skills" / "demo.md").write_text("skill content", encoding="utf-8")
    (data_root / "secrets").mkdir()
    (data_root / "secrets" / "vault.bin").write_text("SECRET", encoding="utf-8")
    return database_path, data_root


async def test_backup_validate_and_restore(tmp_path):
    database_path, data_root = configure_backup_paths(tmp_path)
    snapshot = SnapshotService(database_path, roots=[data_root])
    manager = BackupManager.__new__(BackupManager)
    manager.snapshot = snapshot
    manager.backup_root = tmp_path / "backups"
    manager.retention = 5
    manager.schedule = "manual"
    from app.runtime.event_bus import EventBus

    manager.event_bus = EventBus()
    manager.database = None
    # record() needs a database; patch it out for the pure-filesystem path
    manager._record = lambda manifest: _noop()
    manifest = snapshot.create(manager.backup_root, BackupKind.MANUAL)
    assert "vyom-brain.db" in manifest.parts
    assert any(part.startswith("data/skills") for part in manifest.parts)
    assert not any("secrets" in part for part in manifest.parts)  # secrets excluded

    backup_dir = manager.backup_root / sorted(p.name for p in manager.backup_root.iterdir())[0]
    from app.backup import BackupValidator

    validator = BackupValidator()
    validated = validator.validate(backup_dir)
    assert validated.backup_id == manifest.backup_id

    restore = RestoreService(database_path)
    with pytest.raises(Exception):
        await restore.restore(backup_dir, confirm=False)  # never silent
    result = await restore.restore(backup_dir, confirm=True)
    assert result["restored"] == manifest.backup_id


async def _noop():
    return None


async def test_corrupt_backup_rejected(tmp_path):
    database_path, data_root = configure_backup_paths(tmp_path)
    snapshot = SnapshotService(database_path, roots=[data_root])
    backup_root = tmp_path / "backups"
    manifest = snapshot.create(backup_root, BackupKind.MANUAL)
    backup_dir = backup_root / sorted(p.name for p in backup_root.iterdir())[0]
    # Corrupt the database part
    (backup_dir / "vyom-brain.db").write_bytes(b"not a database anymore")
    from app.backup import BackupValidator

    with pytest.raises(InvalidBackupError):
        BackupValidator().validate(backup_dir)


async def test_backup_retention_prunes_but_keeps_recent(tmp_path):
    database_path, data_root = configure_backup_paths(tmp_path)
    snapshot = SnapshotService(database_path, roots=[data_root])
    backup_root = tmp_path / "backups"
    for index in range(4):
        manifest = snapshot.create(backup_root, BackupKind.MANUAL)
    manager = BackupManager.__new__(BackupManager)
    manager.backup_root = backup_root
    manager.retention = 2
    manager._apply_retention()
    remaining = [item for item in backup_root.iterdir() if item.is_dir()]
    assert len(remaining) <= 2


# --- supervisor ------------------------------------------------------------------------


async def test_supervisor_tick_assesses_health_and_expires_leases(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    audit = DistributedAuditLog(database)
    leases = LeaseManager(database, default_ttl_seconds=-1)  # immediately expired
    await leases.acquire("task-x", "node-a")
    coordinator = DistributedCoordinator(registry, leases, audit)
    health = HealthAggregator()

    async def healthy():
        return HealthState.HEALTHY

    health.register("brain", healthy)
    supervisor = Supervisor(coordinator, health, leases, ReliabilityMetrics(), automation_store=None)
    result = await supervisor.tick()
    assert result["health"]["overall"] == "healthy"
    assert len(result["expired_leases"]) == 1
    await supervisor.stop()


async def test_supervisor_start_stop_lifecycle(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    coordinator = DistributedCoordinator(registry, LeaseManager(database), DistributedAuditLog(database))
    health = HealthAggregator()
    supervisor = Supervisor(coordinator, health, LeaseManager(database), ReliabilityMetrics(), poll_seconds=0.05)
    supervisor.start()
    import asyncio

    await asyncio.sleep(0.15)
    await supervisor.stop()
    assert supervisor._task is None
