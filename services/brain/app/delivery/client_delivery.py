from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from app.persistence.database import Database

from .package_builder import DeliveryApprovalStatus, DeliveryPackage
from .quality_gate import QualityGate, QualityGateReport
from .verifier import DeliveryVerificationReport, DeliveryVerifier


class DeliveryProvider(ABC):
    @abstractmethod
    async def health(self) -> tuple[bool, str | None]: ...

    @abstractmethod
    async def send(self, package: DeliveryPackage) -> dict[str, Any]: ...


class DisconnectedDeliveryProvider(DeliveryProvider):
    """Honest default: no live client-delivery transport is configured."""

    async def health(self) -> tuple[bool, str | None]:
        return False, "No client delivery provider is configured"

    async def send(self, package: DeliveryPackage) -> dict[str, Any]:
        raise RuntimeError("No client delivery provider is configured")


class MockDeliveryProvider(DeliveryProvider):
    """Deterministic fixture provider for demos/tests."""

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    async def send(self, package: DeliveryPackage) -> dict[str, Any]:
        return {
            "message_id": f"FIXTURE-{package.id[-8:].upper()}",
            "provider_confirmation": "test-fixture-delivered",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


class DuplicateDeliveryError(Exception):
    pass


class DeliveryStore:
    def __init__(self, database: Database):
        self.database = database

    async def save(self, package: DeliveryPackage) -> DeliveryPackage:
        package.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO delivery_packages(id, client, project, version, dedupe_key, package_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(dedupe_key) DO UPDATE SET
               id=excluded.id, package_json=excluded.package_json, updated_at=excluded.updated_at""",
            (
                package.id, package.client, package.project, package.version, package.dedupe_key,
                package.model_dump_json(), package.created_at.isoformat(), package.updated_at.isoformat(),
            ),
        )
        await connection.commit()
        return package

    async def get(self, package_id: str) -> DeliveryPackage:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT package_json FROM delivery_packages WHERE id = ?", (package_id,))).fetchone()
        if row is None:
            raise KeyError(package_id)
        return DeliveryPackage.model_validate_json(row["package_json"])

    async def find_by_dedupe_key(self, dedupe_key: str) -> DeliveryPackage | None:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT package_json FROM delivery_packages WHERE dedupe_key = ?", (dedupe_key,))).fetchone()
        return DeliveryPackage.model_validate_json(row["package_json"]) if row else None

    async def list(self, client: str | None = None) -> list[DeliveryPackage]:
        connection = self.database.require_connection()
        if client:
            rows = await (await connection.execute(
                "SELECT package_json FROM delivery_packages WHERE client = ? ORDER BY updated_at DESC", (client,)
            )).fetchall()
        else:
            rows = await (await connection.execute("SELECT package_json FROM delivery_packages ORDER BY updated_at DESC")).fetchall()
        return [DeliveryPackage.model_validate_json(row["package_json"]) for row in rows]


class ClientDeliveryService:
    """VYOM may automatically prepare a delivery package; the actual
    external send/upload defaults to L2 and requires approval unless
    explicitly pre-authorized. A duplicate send for the same package/version
    is rejected, never silently repeated after crash recovery."""

    def __init__(
        self,
        store: DeliveryStore,
        provider: DeliveryProvider | None = None,
        quality_gate: QualityGate | None = None,
        verifier: DeliveryVerifier | None = None,
    ):
        self.store = store
        self.provider = provider or DisconnectedDeliveryProvider()
        self.quality_gate = quality_gate or QualityGate()
        self.verifier = verifier or DeliveryVerifier()

    async def prepare(self, package: DeliveryPackage, *, quality_report: QualityGateReport) -> DeliveryPackage:
        existing = await self.store.find_by_dedupe_key(package.dedupe_key)
        if existing and existing.approval_status == DeliveryApprovalStatus.SENT:
            raise DuplicateDeliveryError(f"An equivalent package was already sent: {existing.id}")
        package.quality_status = "passed" if quality_report.passed else "failed"
        package.approval_status = (
            DeliveryApprovalStatus.QUALITY_CHECKED if quality_report.passed else DeliveryApprovalStatus.DRAFT
        )
        await self.store.save(package)
        return package

    async def send(self, package: DeliveryPackage) -> DeliveryVerificationReport:
        if package.quality_status != "passed":
            raise RuntimeError("Delivery quality gate has not passed; cannot send")

        existing = await self.store.find_by_dedupe_key(package.dedupe_key)
        if existing and existing.approval_status == DeliveryApprovalStatus.SENT:
            raise DuplicateDeliveryError(f"An equivalent package was already sent: {existing.id}")

        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Delivery provider unavailable")

        provider_response = await self.provider.send(package)
        report = self.verifier.verify(package, provider_response)
        if not report.verified:
            package.approval_status = DeliveryApprovalStatus.FAILED
        await self.store.save(package)
        return report
