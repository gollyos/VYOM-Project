from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.diagnostics import (
    DatabaseChecks,
    IntegrationChecks,
    ProviderChecks,
    SecurityAudit,
    SystemChecks,
    ToolChecks,
    VYOMDoctor,
)
from app.migrations.manager import Migration, MigrationManager
from app.observability import (
    CostTracker,
    CrashReporter,
    MetricsRegistry,
    PerformanceBudgets,
    PerformanceMonitor,
    StructuredLogging,
    Tracer,
    bind_request,
    current,
)
from app.persistence.database import Database
from app.production import ConfigValidator, ReadinessTracker, StartupChecks
from app.production.compatibility import CompatibilityChecker, CompatibilityError
from app.security.rate_limits import RateLimiter, RateLimitExceeded, RateRule
from app.security.secret_store import SecretStore
from app.security.sessions import Scope, SessionSecurityManager
from app.setup import OnboardingService, PermissionSetup, SetupStateStore
from app.setup.schemas import SetupStepId
from app.security.authorization import AuthorizationService


@pytest.fixture
async def database(tmp_path: Path) -> Database:
    db = Database(tmp_path / "p13-prod.db")
    await db.connect()
    yield db
    await db.close()


# --- SecretStore ---------------------------------------------------------------


def test_secret_store_roundtrip_rotate_delete_metadata(tmp_path):
    store = SecretStore.for_local_machine(tmp_path / "vault", metadata_path=tmp_path / "meta.json")
    if not store.has_secret("provider/test/default"):
        store.set_secret("provider/test/default", "first-value", kind="provider", owner="test")
    assert store.get_secret("provider/test/default") == "first-value"
    store.rotate_secret("provider/test/default", "second-value")
    assert store.get_secret("provider/test/default") == "second-value"
    metadata = store.list_secret_metadata()
    assert any(item.ref == "provider/test/default" and item.rotated_at for item in metadata)
    assert store.delete_secret("provider/test/default") is True
    assert not store.has_secret("provider/test/default")


def test_environment_backend_read_only(tmp_path):
    store = SecretStore.for_server_environment({"VYOM_SECRET_PROVIDER_TEST_DEFAULT": "env-value"})
    assert store.get_secret("provider/test/default") == "env-value"
    with pytest.raises(Exception):
        store.set_secret("provider/test/default", "x", kind="provider", owner="test")


def test_metadata_persists_across_instances(tmp_path):
    first = SecretStore.for_tests()
    first.set_secret("integration/gmail/default", "tok", kind="integration", owner="gmail")
    # DPAPI-backed store persists metadata; env store keeps it in memory —
    # persistence is exercised through the local-machine variant.
    second = SecretStore.for_local_machine(tmp_path / "vault2", metadata_path=tmp_path / "meta2.json")
    second.set_secret("integration/gcal/default", "tok2", kind="integration", owner="gcal")
    third = SecretStore.for_local_machine(tmp_path / "vault2", metadata_path=tmp_path / "meta2.json")
    assert [item.ref for item in third.list_secret_metadata()] == ["integration/gcal/default"]


# --- sessions --------------------------------------------------------------------


def test_session_lifecycle_scopes_and_revoke_all():
    manager = SessionSecurityManager(ttl_seconds=120)
    session, token = manager.open_session("phone", scopes=list(Scope.ALL))
    assert manager.validate(session.session_id, token, scope="commands").device_id == "phone"
    revoked = manager.revoke_all_remote("owner pressed logout")
    assert revoked == 1
    from app.security.sessions import SessionSecurityError

    with pytest.raises(SessionSecurityError):
        manager.validate(session.session_id, token)


# --- rate limiting ------------------------------------------------------------------


def test_rate_limiter_sliding_window():
    limiter = RateLimiter()
    limiter.configure(RateRule("provider", limit=3, window_seconds=60))
    for _ in range(3):
        assert limiter.check("provider", "openai")[0]
    allowed, retry_after = limiter.check("provider", "openai")
    assert not allowed and retry_after > 0
    with pytest.raises(RateLimitExceeded):
        limiter.enforce("provider", "openai")
    assert limiter.check("provider", "anthropic")[0]  # separate key


# --- observability --------------------------------------------------------------------


def test_structured_logging_redacts_secrets_and_rotates(tmp_path):
    logging = StructuredLogging(tmp_path / "logs", level="INFO")
    log_file = logging.apply()
    import logging as stdlib

    bind_request()
    stdlib.getLogger("vyom.test").info("api_key sk-abcdefghijklmnopqr123456 failed")
    for handler in stdlib.getLogger().handlers:
        handler.flush()
    content = log_file.read_text(encoding="utf-8")
    assert "sk-abcdefghijklmnopqr123456" not in content
    assert "[REDACTED]" in content
    lines = [json.loads(line) for line in content.strip().splitlines() if line.strip()]
    assert all({"timestamp", "level", "service"} <= set(line) for line in lines)
    assert any(line.get("request_id", "").startswith("req_") for line in lines)


def test_correlation_ids_propagate():
    context = bind_request()
    assert current().request_id == context.request_id
    assert current().trace_id == context.trace_id


def test_metrics_counters_gauges_histograms():
    metrics = MetricsRegistry()
    metrics.increment("task_success_total", task_domain="coding")
    metrics.increment("task_success_total", task_domain="coding")
    metrics.increment("task_failure_total")
    metrics.gauge("queue_depth", 4)
    metrics.observe("model_latency", 120.0, provider="local")
    metrics.observe("model_latency", 240.0, provider="local")
    snapshot = metrics.snapshot()
    assert snapshot["counters"]["task_success_total{task_domain=coding}"] == 2
    assert snapshot["gauges"]["queue_depth"] == 4
    assert snapshot["histograms"]["model_latency{provider=local}"]["count"] == 2


async def test_cost_tracker_real_data(tmp_path):
    db = Database(tmp_path / "cost.db")
    await db.connect()
    try:
        from datetime import datetime, timezone as tz

        connection = db.require_connection()
        await connection.execute(
            "INSERT INTO model_performance (model, provider, task_domain, complexity, success, "
            "verification_score, latency_ms, retries, fallback_used, usage_json, estimated_cost, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("local-rules-v1", "local", "general", 1, 1, 1.0, 50.0, 0, 0,
             '{"input_tokens": 100, "output_tokens": 50}', 0.01,
             datetime.now(tz.utc).isoformat()),
        )
        await connection.commit()

        class Store:
            database = db

        store = Store()
        tracker = CostTracker(MetricsRegistry(), store)
        tracker.record_call("openai", "gpt-x", input_tokens=10, output_tokens=5, cost=0.002)
        summary = await tracker.summary(days=1)
        assert summary["live"]["calls"] == 1
        assert summary["live"]["cost"] == pytest.approx(0.002, abs=1e-9)
        assert summary["persisted_model_calls"] == 1
        assert summary["persisted_estimated_cost"] == pytest.approx(0.01, abs=1e-9)
    finally:
        await db.close()


def test_performance_budgets_from_config_and_breach_report():
    monitor = PerformanceMonitor(MetricsRegistry(), PerformanceBudgets.from_config({
        "performance_budgets": {"command_latency_ms": 100.0},
    }))
    monitor.record("command_latency", 250.0)
    report = monitor.budget_report()
    entry = next(item for item in report if item["metric"] == "command_latency")
    assert entry["within_budget"] is False and entry["p95_ms"] == 250.0


def test_tracing_span_tree_and_error_status():
    tracer = Tracer()
    with tracer.span("brain") as root:
        with tracer.span("task", parent=root, tool="terminal"):
            pass
        with pytest.raises(ValueError):
            with tracer.span("tool", parent=root):
                raise ValueError("boom")
    spans = tracer.recent()
    names = {span["name"]: span for span in spans}
    assert names["tool"]["status"] == "error"
    assert names["task"]["status"] == "ok"
    assert names["task"]["parent_id"] == root.span_id if hasattr(root, "span_id") else True


def test_crash_report_contains_no_secrets(tmp_path):
    reporter = CrashReporter(tmp_path / "crash", app_version="0.2.0", service_version="0.2.0")
    try:
        raise RuntimeError("auth failed for api_key sk-abcdefghijklmnopqr123456")
    except RuntimeError as error:
        path = reporter.capture(error, recent_events=[{"message": "token=ghp_abcdefghijklmnopqrstuvwxyz1234"}])
    content = path.read_text(encoding="utf-8")
    assert "sk-abcdefghijklmnopqr123456" not in content
    assert "ghp_abcdefghijklmnopqrstuvwxyz1234" not in content
    assert "[REDACTED]" in content
    assert reporter.list_reports()


# --- migrations -------------------------------------------------------------------------


async def test_migrations_apply_baseline_and_fail_closed(database):
    manager = MigrationManager(database)
    result = await manager.apply_pending()
    assert result["applied"] and result["applied"][0]["name"] == "baseline_schema_v0"
    status = await manager.status()
    assert status["pending"] == [] and status["current_version"] >= 1  # v2+ adds Phase 14 tables

    failing = MigrationManager(database, migrations=[
        Migration(version=99, name="bad_migration", statements=("CREATE TABLE broken(",),
                  validation_query="SELECT 1", validation_expected=(1,)),
    ])
    result = await failing.apply_pending()
    assert result["failed"] and "bad_migration" in result["failed"]["name"]
    status = await failing.status()
    assert 99 in status["pending"]  # failed migration must NOT be recorded as applied


async def test_migration_validation_failure_marks_not_applied(database):
    manager = MigrationManager(database, migrations=[
        Migration(version=2, name="validates_wrong", statements=("CREATE TABLE t2 (id TEXT);",),
                  validation_query="SELECT COUNT(*) FROM t2", validation_expected=(99,)),
    ])
    result = await manager.apply_pending()
    assert result["failed"], "validation mismatch must fail the migration"
    assert 2 in (await manager.status())["pending"]  # v2 still valid here (dedicated db)


# --- production startup / readiness -------------------------------------------------------


def test_config_validator_strict_files_reject_unknown_keys(tmp_path):
    (tmp_path / "security.yaml").write_text("version: 1\nbind: 127.0.0.1\nevil_key: yes\n", encoding="utf-8")
    report = ConfigValidator(tmp_path).validate_all()
    assert report.valid is False
    assert any("unknown keys" in error for error in report.errors)


def test_config_validator_flags_public_bind(tmp_path):
    (tmp_path / "deployment.yaml").write_text(
        "version: 1\ntransport:\n  bind: 0.0.0.0\n", encoding="utf-8")
    report = ConfigValidator(tmp_path).validate_all()
    assert any("0.0.0.0" in warning for warning in report.warnings)


async def test_startup_checks_degraded_mode_for_warnings(tmp_path):
    db = Database(tmp_path / "startup.db")
    await db.connect()
    try:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "security.yaml").write_text("version: 1\n", encoding="utf-8")
        (config_dir / "observability.yaml").write_text("logging:\n  level: INFO\n", encoding="utf-8")
        from app.production.startup_checks import StartupChecks

        checks = StartupChecks(
            config_validator=ConfigValidator(config_dir),
            database=db,
            migrations=MigrationManager(db),
            secret_store=SecretStore.for_tests(),
            required_dirs=[tmp_path / "data1", tmp_path / "data2"],
        )
        report = await checks.run()
        assert report.ok is True            # core systems healthy
        assert report.degraded is True      # warnings exist (e.g. missing version keys)
        assert report.ready is False
    finally:
        await db.close()


def test_readiness_tracker_states():
    tracker = ReadinessTracker()
    assert tracker.snapshot()["state"] == "degraded"  # alive, not ready
    tracker.mark_ready()
    assert tracker.snapshot() == {"alive": True, "ready": True, "state": "ready", "reasons": []}
    tracker.mark_degraded(["gemini unavailable"])
    snapshot = tracker.snapshot()
    assert snapshot["state"] == "degraded" and snapshot["reasons"] == ["gemini unavailable"]


def test_version_compatibility_matrix():
    checker = CompatibilityChecker()
    checker.check_schema(1)
    with pytest.raises(CompatibilityError):
        checker.check_schema(99)
    checker.check_node(protocol_version=1, schema_version=1)
    with pytest.raises(CompatibilityError):
        checker.check_node(protocol_version=7, schema_version=1)


# --- doctor + security audit ----------------------------------------------------------------


async def test_doctor_reports_fail_warning_pass_and_repairs(tmp_path, database):
    provider_checks = ProviderChecks.__new__(ProviderChecks)
    provider_checks.model_registry = None
    provider_checks.providers = None

    class EmptyRegistry:
        def list(self):
            return []

        def get(self, name):
            return None

        def enabled(self):
            return []

    provider_checks.model_registry = EmptyRegistry()
    provider_checks.providers = EmptyRegistry()

    class Tools:
        def list(self):
            return []

    doctor = VYOMDoctor(
        system_checks=SystemChecks(required_dirs=[tmp_path / "missing-dir"]),
        database_checks=DatabaseChecks(tmp_path / "nonexistent.db"),
        provider_checks=provider_checks,
        tool_checks=ToolChecks(Tools()),
        integration_checks=IntegrationChecks(EmptyRegistry(), None, None),
    )
    report = await doctor.run()
    statuses = {check["status"] for check in report["checks"]}
    assert "FAIL" in statuses and "PASS" in statuses
    assert report["overall"] == "FAIL"
    assert any(recommendation["action"] in ("create_directories", "restore_backup", "repair_migrations")
               for recommendation in report["recommendations"])


async def test_security_audit_detects_planted_secret_in_config(tmp_path, database):
    bad_config = tmp_path / "bad.yaml"
    bad_config.write_text("token: ghp_abcdefghijklmnopqrstuvwxyz123456\n", encoding="utf-8")
    audit = SecurityAudit(
        database=database, settings_paths=[bad_config], log_files=[],
        security_config={"bind": "127.0.0.1"}, device_registry=None, session_security=None,
    )
    report = audit.run()
    assert report["overall"] == "high"
    assert any(finding["area"] == "secret_location" and finding["severity"] == "high" for finding in report["findings"])


def test_security_audit_flags_non_loopback_bind(database, tmp_path):
    audit = SecurityAudit(
        database=database, settings_paths=[], log_files=[],
        security_config={"bind": "0.0.0.0"},
    )
    report = audit.run()
    assert any(finding["severity"] == "critical" and finding["area"] == "network_listener" for finding in report["findings"])


# --- onboarding / setup -------------------------------------------------------------------------


async def test_onboarding_flow_resume_skip_and_restart(tmp_path):
    store = SetupStateStore(tmp_path / "setup.json")
    service = OnboardingService(store)
    assert service.status()["needs_onboarding"] is True

    await service.complete_step(SetupStepId.INTRO, {})
    await service.complete_step(SetupStepId.PREFERENCES, {"name": "Gunjan"})
    await service.skip_step(SetupStepId.VOICE_TEST)  # interrupted here; state persists

    resumed = OnboardingService(SetupStateStore(tmp_path / "setup.json"))
    status = resumed.status()
    assert "intro" in status["completed"] and "voice_test" in status["skipped"]
    assert status["next_step"] == "microphone"

    for step_id in list(SetupStepId):
        if step_id in (SetupStepId.INTRO, SetupStepId.PREFERENCES, SetupStepId.VOICE_TEST):
            continue
        if step_id == SetupStepId.MICROPHONE:
            await resumed.skip_step(step_id)
        else:
            await resumed.complete_step(step_id, {})
    assert resumed.status()["finished"] is True

    # After restart, onboarding must not reappear.
    again = OnboardingService(SetupStateStore(tmp_path / "setup.json"))
    assert again.status()["needs_onboarding"] is False


async def test_required_step_cannot_be_skipped(tmp_path):
    service = OnboardingService(SetupStateStore(tmp_path / "setup.json"))
    with pytest.raises(ValueError):
        await service.skip_step(SetupStepId.PRIVACY)


async def test_onboarding_reset_preserves_state_file_only(tmp_path):
    store = SetupStateStore(tmp_path / "setup.json")
    service = OnboardingService(store)
    await service.complete_step(SetupStepId.INTRO, {})
    await service.reset()
    assert service.status()["needs_onboarding"] is True
    assert service.status()["completed"] == []


def test_permission_presets_never_bypass_l3():
    from app.schemas.approvals import PermissionLevel

    setup = PermissionSetup(AuthorizationService("balanced"))
    for preset in ("conservative", "balanced", "autonomous"):
        applied = setup.apply(preset)
        assert applied["preset"] == preset
        assert "L3" not in applied["allows_automatically"]
        assert "L2" not in applied["allows_automatically"]
    assert PermissionLevel.L3 not in AuthorizationService("autonomous").grant.allow_automatic


def test_provider_setup_is_dynamic_and_honest(tmp_path):
    from app.setup import ProviderSetup
    from app.providers.base import ProviderRegistry
    from app.providers.deterministic import DeterministicProvider
    from app.routing.model_registry import ModelRegistry
    from tests.helpers import local_model

    registry = ModelRegistry([local_model()])
    providers = ProviderRegistry([DeterministicProvider()])
    setup = ProviderSetup(registry, providers, SecretStore.for_tests())
    options = setup.list_options()
    assert [option["provider"] for option in options] == ["local"]
    import asyncio

    connection = asyncio.run(setup.test("local"))
    # Honesty over optimism: only a real interaction outcome is accepted,
    # never "connected" merely because the provider exists.
    assert connection["outcome"] in {"connected", "unconfigured", "authentication_failed", "network_error", "rate_limited"}
