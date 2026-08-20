from __future__ import annotations

from dataclasses import dataclass, field

from app.devices.schemas import utc_now

from .registry import CapabilityRegistry
from .schemas import (
    CapabilityBackend,
    CapabilityRecord,
    CapabilitySource,
    CapabilityStatus,
    ExternalCapabilityMeta,
    ExternalCapabilityStatus,
)

APPROVED_LICENSES = {
    "mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "mpl-2.0", "unlicense",
}
# Licenses requiring explicit review before any approval.
REVIEW_LICENSES = {"gpl-3.0", "agpl-3.0", "lgpl-3.0", "unknown", "proprietary", ""}


class IntakeRejected(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass
class ExternalCandidate:
    """Metadata gathered by RESEARCH/inspection — never by executing an
    arbitrary repository. VYOM never pip/npm-installs or clones an
    external project because a model suggested it."""

    capability_id: str
    name: str
    description: str
    repository: str
    version: str
    license: str
    kind: str                       # tool | mcp | integration | library
    permissions: list[str] = field(default_factory=list)
    network_access: bool = False
    filesystem_access: bool = False
    secret_access: bool = False
    dependencies: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class ExternalCapabilityIntake:
    """Compact intake engine over the EXISTING Capability Registry:
    inspect → license check → security review → permission mapping →
    sandbox → benchmark → approve → register → monitor → disable.
    Integration points: Permission Engine levels on the record, the
    Tool/MCP/Integration/Skill registries through normal registration,
    the SecretStore for any credentials, and the audit/evidence stream
    via the existing security event log."""

    def __init__(self, registry: CapabilityRegistry, *, trust_source: dict[str, str] | None = None):
        self.registry = registry
        self.trust_source = trust_source or {}

    # -- review ------------------------------------------------------------

    def license_check(self, candidate: ExternalCandidate) -> None:
        license_id = (candidate.license or "").strip().lower()
        if license_id in REVIEW_LICENSES:
            raise IntakeRejected(
                f"License '{candidate.license or 'unknown'}' requires explicit human review before approval"
            )
        if license_id not in APPROVED_LICENSES:
            raise IntakeRejected(f"License '{candidate.license}' is not on the approved list")

    def security_review(self, candidate: ExternalCandidate) -> list[str]:
        notes: list[str] = []
        if candidate.secret_access:
            notes.append("requests secret access — credentials route exclusively through the SecretStore")
        if candidate.filesystem_access:
            notes.append("requests filesystem access — restricted to registered project roots via Path Policy")
        if candidate.network_access:
            notes.append("requests network access — outbound only, no listeners")
        risky = [dependency for dependency in candidate.dependencies
                 if any(marker in dependency.lower() for marker in ("eval", "exec", "shell", "root", "sudo"))]
        if risky:
            notes.append(f"flagged dependencies: {risky}")
        return notes

    def sandbox(self, candidate: ExternalCandidate, runner=None) -> SandboxResult:
        """Sandbox checks are DRY-RUN by default: the intake layer never
        executes external code itself. A caller may supply a sandbox
        runner (existing skill-sandbox/test harness) for live checks."""
        if runner is None:
            return SandboxResult(
                passed=True,
                checks={"dry_run": True, "no_automatic_installation": True},
                notes=["dry-run sandbox: external code was not executed by intake"],
            )
        return runner(candidate)

    # -- lifecycle ------------------------------------------------------------

    def discover(self, candidate: ExternalCandidate) -> CapabilityRecord:
        """Registers the candidate as DISCOVERED — never active. It is
        observable in the registry but cannot be selected yet."""
        record = CapabilityRecord(
            capability_id=candidate.capability_id,
            name=candidate.name,
            description=candidate.description,
            source=CapabilitySource.EXTERNAL,
            source_id=candidate.repository,
            status=CapabilityStatus.RESTRICTED,
            tags=["external", candidate.kind],
            external=ExternalCapabilityMeta(
                repository=candidate.repository,
                version=candidate.version,          # version pinning
                license=candidate.license,
                trust_level="untrusted",
                intake_status=ExternalCapabilityStatus.DISCOVERED,
                network_access=candidate.network_access,
                filesystem_access=candidate.filesystem_access,
                secret_access=candidate.secret_access,
                review_notes=[],
            ),
        )
        self.registry.register(record)
        return record

    def review(self, capability_id: str, candidate: ExternalCandidate, *, runner=None) -> CapabilityRecord:
        record = self.registry.get(capability_id)
        if record is None or record.external is None:
            raise KeyError(capability_id)
        record.external.intake_status = ExternalCapabilityStatus.REVIEWING
        try:
            self.license_check(candidate)
            notes = self.security_review(candidate)
        except IntakeRejected as rejection:
            record.external.intake_status = ExternalCapabilityStatus.REJECTED
            record.external.review_notes.append(f"rejected: {rejection.reason}")
            self.registry.register(record)
            raise
        record.external.intake_status = ExternalCapabilityStatus.SANDBOXED
        sandbox = self.sandbox(candidate, runner=runner)
        record.external.review_notes.extend(notes + sandbox.notes)
        if not sandbox.passed:
            record.external.intake_status = ExternalCapabilityStatus.REJECTED
            self.registry.register(record)
            raise IntakeRejected(f"sandbox failed: {sandbox.checks}")
        record.external.intake_status = ExternalCapabilityStatus.TESTING
        self.registry.register(record)
        return record

    def benchmark(self, capability_id: str, results: dict) -> CapabilityRecord:
        """Records measured benchmark results (task type, success,
        latency, cost, quality, failures, fallbacks) — stored on the
        record; Phase 14 learns from these numbers."""
        record = self.registry.get(capability_id)
        if record is None or record.external is None:
            raise KeyError(capability_id)
        record.external.benchmark = results
        record.external.intake_status = ExternalCapabilityStatus.APPROVED
        record.last_verified = utc_now()
        self.registry.register(record)
        return record

    def approve(self, capability_id: str, *, backends: list[CapabilityBackend] | None = None,
                trusted: bool = False) -> CapabilityRecord:
        """Approval makes the capability selectable. Trusted status is a
        separate explicit step (default stays restricted)."""
        record = self.registry.get(capability_id)
        if record is None or record.external is None:
            raise KeyError(capability_id)
        if record.external.intake_status not in (ExternalCapabilityStatus.APPROVED, ExternalCapabilityStatus.TESTING):
            raise IntakeRejected(
                f"cannot approve from state {record.external.intake_status.value}; complete review+benchmark first"
            )
        if not record.external.benchmark:
            raise IntakeRejected("cannot approve without measured benchmark results")
        record.external.intake_status = ExternalCapabilityStatus.ACTIVE
        record.external.installed_at = utc_now()
        record.external.trust_level = "trusted" if trusted else "restricted"
        record.status = CapabilityStatus.AVAILABLE
        record.reliability = float(record.external.benchmark.get("success_rate", 0.5))
        if backends:
            record.backends = backends
        self.registry.register(record)
        return record

    # -- monitoring / rollback --------------------------------------------------

    def mark_health(self, capability_id: str, health: str) -> CapabilityRecord | None:
        record = self.registry.get(capability_id)
        if record is None or record.external is None:
            return None
        if health == "healthy":
            record.external.intake_status = ExternalCapabilityStatus.ACTIVE
            record.status = CapabilityStatus.AVAILABLE
        elif health == "degraded":
            record.external.intake_status = ExternalCapabilityStatus.DEGRADED
            record.status = CapabilityStatus.DEGRADED
        else:
            record.external.intake_status = ExternalCapabilityStatus.DISABLED
            record.status = CapabilityStatus.UNAVAILABLE
        self.registry.register(record)
        return record

    def disable(self, capability_id: str) -> CapabilityRecord | None:
        """Disabling never breaks VYOM Core: the registry stops offering
        the backend and selection falls back to remaining backends."""
        record = self.registry.get(capability_id)
        if record is None or record.external is None:
            return None
        record.external.intake_status = ExternalCapabilityStatus.DISABLED
        record.status = CapabilityStatus.UNAVAILABLE
        self.registry.register(record)
        return record


class CapabilityBackendRouter:
    """Deterministic backend selection over the EXISTING registry:
    capability match + health + permissions + latency + cost +
    reliability, in that priority. No AI router; Phase 14 learns
    outcomes elsewhere."""

    @staticmethod
    def order_backends(record: CapabilityRecord) -> list[CapabilityBackend]:
        def rank(backend: CapabilityBackend) -> tuple:
            health_rank = {"healthy": 0, "unknown": 1, "degraded": 2, "offline": 3}.get(backend.health, 3)
            return (0 if backend.preferred else 1, health_rank, -backend.reliability,
                    backend.latency_ms or 10_000, backend.cost)

        return sorted(record.backends, key=rank)

    def select(self, registry: CapabilityRegistry, capability_id: str) -> tuple[CapabilityBackend | None, list[str]]:
        record = registry.get(capability_id)
        if record is None:
            return None, [f"capability {capability_id} not registered"]
        if record.external is not None and record.external.intake_status != ExternalCapabilityStatus.ACTIVE:
            return None, [f"external capability {capability_id} is {record.external.intake_status.value}"]
        ordered = self.order_backends(record)
        if not ordered:
            return None, [f"capability {capability_id} has no backends"]
        rejected = [
            f"{b.backend_id} skipped ({b.health})" for b in ordered if b.health in ("offline", "degraded")
        ]
        usable = [b for b in ordered if b.health not in ("offline", "degraded")]
        chosen = usable[0] if usable else None
        if chosen is None:
            rejected.append("no healthy backend available")
        return chosen, rejected
