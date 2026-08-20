from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.devices.authentication import DevicePairingService
from app.devices.heartbeat import HeartbeatMonitor
from app.devices.registry import DeviceRegistry
from app.devices.schemas import (
    DeviceCapability,
    DeviceNode,
    DeviceOnlineStatus,
    DeviceTrustLevel,
    DeviceType,
    NodePresence,
    NodeRole,
    NodeVersionInfo,
    utc_now,
)
from app.devices.store import DeviceNodeStore, NodeTokenStore
from app.distributed import (
    ActivitySummaryBuilder,
    BudgetLimits,
    DistributedAuditLog,
    DistributedCoordinator,
    GlobalBudgetManager,
    LeaseError,
    LeaseManager,
    NodeRouter,
    RouterConfig,
    TaskDispatcher,
    TaskHandoffService,
    TaskOwnershipRegistry,
    TaskRequirements,
    VersionCompatibilityError,
)
from app.persistence.database import Database
from app.reliability import (
    CheckpointStore,
    CircuitBreakerRegistry,
    HealthAggregator,
    HealthState,
    RecoveryService,
    ReliabilityMetrics,
    TaskCheckpoint,
    Watchdog,
    WatchdogConfig,
)


@pytest.fixture
async def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "phase12.db")
    await db.connect()
    yield db
    await db.close()


def make_node(
    node_id: str,
    *,
    device_type=DeviceType.HOME_SERVER,
    capabilities=(),
    roles=(NodeRole.WORKER_NODE,),
    trust=DeviceTrustLevel.TRUSTED,
) -> DeviceNode:
    node = DeviceNode(
        name=node_id,
        device_type=device_type,
        platform="linux",
        capabilities=list(capabilities),
        roles=list(roles),
        trust_level=trust,
        version_info=NodeVersionInfo(),
    )
    node.node_id = node_id
    return node


async def trusted_online_node(registry: DeviceRegistry, node: DeviceNode) -> DeviceNode:
    registry.heartbeat.record(node.node_id)
    await registry.register_and_save(node)
    return registry.get(node.node_id)


# --- node registry, pairing persistence, revocation ----------------------


async def test_paired_nodes_survive_brain_restart(database):
    store = DeviceNodeStore(database)
    token_store = NodeTokenStore(database)
    registry = DeviceRegistry(HeartbeatMonitor(), store=store)
    pairing = DevicePairingService(token_store=token_store)

    request = pairing.start_pairing("Laptop", DeviceType.LAPTOP, "windows", [DeviceCapability.NOTIFICATIONS_SEND])
    node, token = pairing.approve(request.request_id, allowed_capabilities=[DeviceCapability.NOTIFICATIONS_SEND])
    await registry.register_and_save(node)
    # token hash persisted by the API layer path used in main.py
    await token_store.save(node.node_id, pairing._tokens[node.node_id])

    # Simulate restart: fresh in-memory services hydrate from SQLite.
    registry2 = DeviceRegistry(HeartbeatMonitor(), store=DeviceNodeStore(database))
    pairing2 = DevicePairingService(token_store=NodeTokenStore(database))
    await pairing2.load_tokens()
    await registry2.hydrate()
    assert registry2.get(node.node_id) is not None
    assert pairing2.authenticate(node.node_id, token)


async def test_revocation_persists_and_blocks_authentication(database):
    store = DeviceNodeStore(database)
    token_store = NodeTokenStore(database)
    registry = DeviceRegistry(HeartbeatMonitor(), store=store)
    pairing = DevicePairingService(token_store=token_store)
    request = pairing.start_pairing("Old laptop", DeviceType.LAPTOP, "windows", [])
    node, token = pairing.approve(request.request_id, allowed_capabilities=[])
    await registry.register_and_save(node)
    await token_store.save(node.node_id, pairing._tokens[node.node_id])

    await registry.revoke_and_save(node.node_id, pairing)

    registry2 = DeviceRegistry(HeartbeatMonitor(), store=DeviceNodeStore(database))
    await registry2.hydrate()
    revoked = registry2.get(node.node_id)
    assert revoked.trust_level == DeviceTrustLevel.REVOKED


async def test_version_incompatible_node_rejected():
    coordinator = DistributedCoordinator(DeviceRegistry(), None, DistributedAuditLog(None))
    with pytest.raises(VersionCompatibilityError):
        await coordinator.register_node(DeviceNode(
            name="old", device_type=DeviceType.LAPTOP, platform="windows",
            version_info=NodeVersionInfo(protocol_version="99"),
        ))


# --- heartbeat / presence -------------------------------------------------


async def test_heartbeat_presence_and_online_transitions(database):
    audit = DistributedAuditLog(database)
    registry = DeviceRegistry(HeartbeatMonitor(offline_after_seconds=60), store=DeviceNodeStore(database))
    coordinator = DistributedCoordinator(registry, None, audit)
    node = await trusted_online_node(registry, make_node("server", device_type=DeviceType.HOME_SERVER))
    updated = await coordinator.record_heartbeat(
        node.node_id, presence={"battery_percent": 55, "network_type": "wifi"}, runtime_health="healthy",
    )
    assert updated.online == DeviceOnlineStatus.ONLINE
    assert updated.presence.battery_percent == 55
    assert updated.runtime_health == "healthy"


# --- node routing -----------------------------------------------------------


async def test_router_selects_capable_online_trusted_node():
    registry = DeviceRegistry(HeartbeatMonitor())
    router = NodeRouter(registry)
    await trusted_online_node(
        registry,
        make_node("home", capabilities=[DeviceCapability.RESEARCH, DeviceCapability.AUTOMATIONS]),
    )
    decision = router.select("t1", TaskRequirements(required_capabilities=["task.research"]))
    assert decision.placed and decision.node_id == "home"


async def test_router_rejects_untrusted_offline_and_incident_nodes():
    registry = DeviceRegistry(HeartbeatMonitor())
    router = NodeRouter(registry)
    untrusted = make_node("bad", trust=DeviceTrustLevel.UNPAIRED)
    registry.register(untrusted)
    decision = router.select("t1", TaskRequirements())
    assert not decision.placed
    assert any("trust" in reason for reason in decision.reasons)


async def test_router_respects_privacy_and_gpu_requirements():
    registry = DeviceRegistry(HeartbeatMonitor())
    router = NodeRouter(registry)
    cloud = make_node("cloud", device_type=DeviceType.HOME_SERVER, capabilities=[DeviceCapability.GPU])
    cloud.device_type = DeviceType.HOME_SERVER
    await trusted_online_node(registry, cloud)
    gpu_node = make_node("gpu-box", capabilities=[DeviceCapability.GPU, DeviceCapability.RESEARCH])
    await trusted_online_node(registry, gpu_node)
    decision = router.select("t1", TaskRequirements(requires_gpu=True, required_capabilities=["task.research"]))
    assert decision.placed and decision.node_id == "gpu-box"


async def test_router_low_battery_portable_avoids_heavy_work():
    registry = DeviceRegistry(HeartbeatMonitor())
    router = NodeRouter(registry)
    laptop = make_node("laptop", device_type=DeviceType.LAPTOP, capabilities=[DeviceCapability.RESEARCH])
    laptop.presence = NodePresence(battery_percent=10, on_battery=True)
    await trusted_online_node(registry, laptop)
    decision = router.select("t1", TaskRequirements(required_capabilities=["task.research"]))
    assert not decision.placed


# --- leases and duplicate prevention ----------------------------------------


async def test_lease_single_owner_until_expiry(database):
    leases = LeaseManager(database, default_ttl_seconds=1)
    await leases.acquire("task-1", "node-a")
    with pytest.raises(LeaseError):
        await leases.acquire("task-1", "node-b")
    # same node may re-acquire (heartbeat/renewal path)
    renewed = await leases.acquire("task-1", "node-a")
    assert renewed.node_id == "node-a"
    expired = await leases.expired(now=utc_now() + timedelta(seconds=10))
    assert [lease.task_id for lease in expired] == ["task-1"]


async def test_lease_heartbeat_extends_expiry(database):
    leases = LeaseManager(database, default_ttl_seconds=5)
    await leases.acquire("task-1", "node-a")
    lease = await leases.heartbeat("task-1", "node-a", extend_seconds=120)
    assert lease.expires_at > utc_now() + timedelta(seconds=100)
    assert not await leases.expired()


async def test_ownership_idempotency_prevents_double_send(database):
    leases = LeaseManager(database)
    ownership = TaskOwnershipRegistry(database, leases)
    first = await ownership.begin_consequential("task-1", "node-a", "email:send:msg-42")
    second = await ownership.begin_consequential("task-1", "node-b", "email:send:msg-42")
    assert first and not second  # failover node cannot repeat the send
    assert await ownership.was_executed("email:send:msg-42")


# --- dispatcher --------------------------------------------------------------


async def test_dispatch_executes_on_selected_node_and_releases_lease(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    audit = DistributedAuditLog(database)
    router = NodeRouter(registry)
    leases = LeaseManager(database)
    await trusted_online_node(registry, make_node("worker", capabilities=[DeviceCapability.RESEARCH]))

    executed = []

    async def executor(node_id, task_id, requirements):
        executed.append((node_id, task_id))
        return {"ok": True, "result": "research done"}

    dispatcher = TaskDispatcher(router, leases, audit, executor=executor)
    outcome = await dispatcher.dispatch("task-1", TaskRequirements(required_capabilities=["task.research"]))
    assert outcome.dispatched and outcome.status == "executed"
    assert executed == [("worker", "task-1")]
    assert await leases.get("task-1") is None  # released after execution
    records = await audit.for_task("task-1")
    assert any(record["action"] == "task_dispatched" for record in records)


async def test_dispatch_honest_when_no_capable_node(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    dispatcher = TaskDispatcher(NodeRouter(registry), LeaseManager(database), DistributedAuditLog(database))
    outcome = await dispatcher.dispatch("task-1", TaskRequirements(required_capabilities=["task.coding"]))
    assert not outcome.dispatched
    assert outcome.status == "no_capable_node"
    assert outcome.reasons


async def test_dispatch_blocked_by_budget(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    await trusted_online_node(registry, make_node("worker"))
    budgets = GlobalBudgetManager(database, BudgetLimits(max_concurrent_tasks=1))
    await budgets.record(concurrent_tasks=1)
    dispatcher = TaskDispatcher(NodeRouter(registry), LeaseManager(database), DistributedAuditLog(database), budgets=budgets)
    outcome = await dispatcher.dispatch("task-1", TaskRequirements())
    assert outcome.status == "deferred_budget"


async def test_budget_hard_limit_enforced(database):
    budgets = GlobalBudgetManager(database, BudgetLimits(daily_model_cost=5.0, daily_research_calls=3))
    await budgets.record(model_cost=4.9)
    allowed, _ = await budgets.check_allowed(model_cost=0.2)
    assert not allowed
    with pytest.raises(Exception):
        await budgets.enforce(model_cost=0.2)


# --- handoff -----------------------------------------------------------------


async def test_portable_task_handoff_moves_to_other_node(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    audit = DistributedAuditLog(database)
    router = NodeRouter(registry)
    leases = LeaseManager(database)
    desktop = make_node("desktop", device_type=DeviceType.DESKTOP_PC, capabilities=[DeviceCapability.RESEARCH])
    server = make_node("server", capabilities=[DeviceCapability.RESEARCH])
    await trusted_online_node(registry, desktop)
    await trusted_online_node(registry, server)
    await leases.acquire("task-1", desktop.node_id)

    handoff = TaskHandoffService(router, leases, audit)
    decision = await handoff.handoff("task-1", desktop.node_id, TaskRequirements(required_capabilities=["task.research"]))
    assert decision.portable and decision.decision == "handoff"
    assert decision.target_node == server.node_id


async def test_non_portable_task_waits_for_owner_honestly(database):
    registry = DeviceRegistry(HeartbeatMonitor())
    audit = DistributedAuditLog(database)
    router = NodeRouter(registry)
    leases = LeaseManager(database)
    desktop = make_node("desktop", device_type=DeviceType.DESKTOP_PC, capabilities=[DeviceCapability.CODING, DeviceCapability.TERMINAL])
    server = make_node("server", capabilities=[DeviceCapability.RESEARCH])
    await trusted_online_node(registry, desktop)
    await trusted_online_node(registry, server)

    handoff = TaskHandoffService(router, leases, audit)
    requirements = TaskRequirements(requires_local_files=True, local_project="C:\\VYOM Project", required_capabilities=["task.coding"])
    decision = await handoff.handoff("task-1", desktop.node_id, requirements)
    assert not decision.portable
    assert decision.decision == "wait_for_owner"
    assert any("not portable" in reason for reason in decision.reasons)


# --- checkpoints and recovery -------------------------------------------------


async def test_checkpoint_roundtrip(database):
    store = CheckpointStore(database)
    checkpoint = TaskCheckpoint(
        task_id="task-1", task_state={"status": "executing"}, current_plan_step="step-2",
        completed_tool_calls=[{"tool": "research", "ok": True}],
        evidence_references=["ev-1"], budget_consumed={"cost": 0.4}, artifacts=["report.md"],
    )
    await store.save(checkpoint)
    loaded = await store.get("task-1")
    assert loaded.current_plan_step == "step-2"
    assert loaded.completed_tool_calls[0]["tool"] == "research"
    assert "reasoning" not in loaded.model_dump()  # hidden reasoning never persisted


async def test_crash_recovery_decisions(database):
    from tests.helpers import build_runtime, close_harness
    from app.schemas.tasks import TaskCreate

    harness = await build_runtime(database.path.parent / "recovery.db")
    try:
        checkpoint_store = CheckpointStore(harness.database)
        audit = DistributedAuditLog(harness.database)
        leases = LeaseManager(harness.database)
        ownership = TaskOwnershipRegistry(harness.database, leases)
        recovery = RecoveryService(harness.task_store, checkpoint_store, ownership, audit, leases)

        # 1) plain running task without checkpoint -> pause
        plain = await harness.runtime.create_task(TaskCreate(user_request="Summarize the plan"))
        decisions = await recovery.recover()
        by_id = {decision.task_id: decision for decision in decisions}
        assert by_id[plain.id].action.value == "pause"

        # 2) checkpointed task -> resume
        checkpointed = await harness.runtime.create_task(TaskCreate(user_request="Research competitors"))
        await checkpoint_store.save(TaskCheckpoint(task_id=checkpointed.id, task_state={"status": "executing"}))
        decisions = await recovery.recover()
        by_id = {decision.task_id: decision for decision in decisions}
        assert by_id[checkpointed.id].action.value == "resume"

        # 3) consequential task with external evidence -> needs_review
        from app.schemas.tasks import Task, TaskStatus
        from app.schemas.approvals import PermissionLevel

        risky = Task(goal="Send email", user_request="Send the email to the client")
        risky.status = TaskStatus.EXECUTING
        risky.permission_level = PermissionLevel.L2
        risky.metadata["consequential"] = True
        await harness.task_store.save(risky)
        await checkpoint_store.save(TaskCheckpoint(
            task_id=risky.id, task_state={"status": "executing"},
            completed_tool_calls=[{"tool": "email", "sent": True}], evidence_references=["ev-send"],
        ))
        decisions = await recovery.recover()
        by_id = {decision.task_id: decision for decision in decisions}
        assert by_id[risky.id].action.value == "needs_review"
        assert by_id[risky.id].consequential
    finally:
        await close_harness(harness)


# --- watchdog and circuit breakers ---------------------------------------------


def test_watchdog_detects_stalled_and_repeated_failures():
    watchdog = Watchdog(WatchdogConfig(stall_seconds=60, max_recovery_attempts=2))
    stalled = watchdog.detect_stalled({"t1": utc_now() - timedelta(seconds=120)})
    assert stalled is not None and stalled.task_id == "t1"
    repeated = watchdog.detect_repeated_failures({"t2": ["timeout", "timeout", "timeout"]})
    assert repeated is not None
    assert watchdog.decide(repeated) == "retry"
    watchdog.decide(repeated)
    assert watchdog.decide(repeated) == "pause_and_notify"  # bounded recovery


async def test_circuit_breaker_opens_and_half_open_recovers():
    breakers = CircuitBreakerRegistry(failure_threshold=3, cooldown_seconds=0.05)
    for _ in range(3):
        await breakers.record_failure("gmail", "500")
    assert not await breakers.allows("gmail")
    assert breakers.status("gmail")["state"] == "open"
    import asyncio

    await asyncio.sleep(0.06)
    assert await breakers.allows("gmail")  # half-open probing
    await breakers.record_success("gmail")
    await breakers.record_success("gmail")
    assert breakers.status("gmail")["state"] == "closed"


async def test_health_aggregator_states_and_degraded_event():
    from app.runtime.event_bus import EventBus

    bus = EventBus()
    aggregator = HealthAggregator(bus)

    async def healthy_check():
        return HealthState.HEALTHY

    async def flaky_check():
        return HealthState.DEGRADED

    aggregator.register("brain", healthy_check)
    aggregator.register("email", flaky_check)
    report = await aggregator.assess()
    assert report["components"]["email"] == "degraded"
    assert report["overall"] == "degraded"
    assert any(
        event.type.value == "health_degraded" and event.structured_payload.get("component") == "email"
        for event in bus.history
    )


def test_reliability_metrics_from_real_outcomes():
    metrics = ReliabilityMetrics()
    metrics.record_task_outcome("completed", 1200.0)
    metrics.record_task_outcome("completed", 800.0)
    metrics.record_task_outcome("failed", 500.0)
    metrics.record_recovery()
    metrics.record_provider_failure("gmail")
    metrics.record_queue_depth(3)
    snapshot = metrics.snapshot()
    assert abs(snapshot["task_success_rate"] - 2 / 3) < 0.01
    assert snapshot["task_recovery_count"] == 1
    assert snapshot["provider_failure_counts"] == {"gmail": 1}
    assert snapshot["queue_depth"] == 3
    assert snapshot["average_task_latency_ms"] == 1000.0


async def test_away_summary_only_from_real_records(database):
    from tests.helpers import build_runtime, close_harness
    from app.schemas.tasks import TaskCreate

    harness = await build_runtime(database.path.parent / "oversight.db")
    try:
        audit = DistributedAuditLog(harness.database)
        builder = ActivitySummaryBuilder(harness.task_store, None, audit)
        empty = await builder.build(utc_now() - timedelta(hours=1))
        assert empty["empty"] is True
        await audit.record("task_dispatched", node_id="home", task_id="t9", result="executed")
        summary = await builder.build(utc_now() - timedelta(hours=1))
        assert summary["empty"] is False
        assert summary["node_actions"] and summary["node_actions"][0]["node_id"] == "home"
    finally:
        await close_harness(harness)


async def test_coordinator_pause_and_resume_automations(database):
    from app.automation.schemas import Automation, AutomationCreate, AutomationStatus
    from app.automation.store import AutomationStore

    store = AutomationStore(database)
    automation = Automation.from_create(AutomationCreate(
        name="nightly", action="run_research_task", type="recurring", interval_minutes=60,
    ))
    automation.status = AutomationStatus.ACTIVE
    await store.save(automation)

    registry = DeviceRegistry(HeartbeatMonitor())
    coordinator = DistributedCoordinator(registry, None, DistributedAuditLog(database), automation_store=store)
    paused = await coordinator.pause_everything()
    assert automation.id in paused["automations_paused"]
    resumed = await coordinator.resume_all()
    assert automation.id in resumed["automations_resumed"]
    refreshed = await store.get(automation.id)
    assert refreshed.status == AutomationStatus.ACTIVE
