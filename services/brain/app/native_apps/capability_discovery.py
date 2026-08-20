from __future__ import annotations

from app.capabilities.registry import CapabilityRegistry
from app.capabilities.schemas import CapabilityRecord, CapabilitySource, CapabilityStatus, verified_now

from .registry import NativeAppAdapterRegistry


def register_adapter_capabilities(capability_registry: CapabilityRegistry, adapters: NativeAppAdapterRegistry) -> None:
    """Publishes one capability per (adapter, supported action) so
    Discovery Engine and general capability search can see native-app
    integrations exactly like tools/skills/agents/models/integrations."""
    for adapter in adapters.list():
        for action in adapter.supported_actions:
            capability_registry.register(CapabilityRecord(
                capability_id=f"native_app.{adapter.app_id}.{action}",
                name=f"{adapter.app_id} {action}".replace("_", " ").title(),
                description=f"{adapter.integration_type.value} integration for {adapter.app_id}: {action}",
                source=CapabilitySource.BUILTIN_TOOL,
                source_id=f"native_apps.{adapter.app_id}",
                status=CapabilityStatus.AVAILABLE,
                reliability=0.85 if adapter.integration_type.value in {"native_api", "cli"} else 0.5,
                last_verified=verified_now(),
                tags=["native_app", adapter.app_id, adapter.integration_type.value],
            ))
