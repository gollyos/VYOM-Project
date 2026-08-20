from __future__ import annotations

from .registry import CapabilityRegistry
from .schemas import CapabilityRecord, CapabilitySource, CapabilityStatus


class CapabilityDiscovery:
    def __init__(self, registry: CapabilityRegistry):
        self.registry = registry

    def from_skill(self, skill) -> CapabilityRecord:
        return self.registry.register(CapabilityRecord(
            capability_id=f"skill.{skill.id}",
            name=skill.name,
            description=skill.description,
            source=CapabilitySource.SKILL,
            source_id=skill.id,
            status=CapabilityStatus.AVAILABLE if skill.status.value in {"approved", "active"} else CapabilityStatus.RESTRICTED,
            required_permissions=[skill.required_permissions],
            reliability=skill.success_rate,
            tags=[skill.category, *skill.required_capabilities],
        ))

    def from_agent(self, agent) -> CapabilityRecord:
        return self.registry.register(CapabilityRecord(
            capability_id=f"agent.{agent.id}",
            name=agent.name,
            description=agent.description,
            source=CapabilitySource.AGENT,
            source_id=agent.id,
            status=CapabilityStatus.AVAILABLE if agent.status.value == "ready" else CapabilityStatus.RESTRICTED,
            required_permissions=[agent.permissions],
            reliability=agent.performance.success_rate,
            tags=[agent.role, *agent.capabilities],
        ))

    def from_model(self, model, *, available: bool) -> CapabilityRecord:
        return self.registry.register(CapabilityRecord(
            capability_id=f"model.{model.provider}.{model.model_id}",
            name=f"{model.provider.title()} {model.model_id}",
            description=f"Model capability profile with {model.quality_tier} quality and {model.cost_tier} cost.",
            source=CapabilitySource.MODEL,
            source_id=model.key,
            status=CapabilityStatus.AVAILABLE if available else CapabilityStatus.UNAVAILABLE,
            reliability=min(1.0, max(0.1, model.priority / 100)),
            tags=sorted(model.capabilities),
            inputs={"privacy_policy": model.privacy_policy, "context_tier": model.context_tier},
            outputs={"streaming": model.supports_streaming, "tools": model.supports_tools, "vision": model.supports_vision},
        ))

    def from_mcp(self, server) -> list[CapabilityRecord]:
        status = CapabilityStatus.AVAILABLE if server.status == "connected" else CapabilityStatus.UNAVAILABLE
        records: list[CapabilityRecord] = []
        for tool in server.tools:
            name = str(tool.get("name", "unknown"))
            records.append(self.registry.register(CapabilityRecord(
                capability_id=f"mcp.{server.server_id}.{name}",
                name=name.replace("_", " ").title(),
                description=str(tool.get("description", f"MCP tool from {server.name}")),
                source=CapabilitySource.MCP_TOOL,
                source_id=server.server_id,
                status=status,
                inputs=dict(tool.get("inputSchema", {})),
                reliability=0.75 if status == CapabilityStatus.AVAILABLE else 0,
                tags=[server.name, server.trust_level],
            )))
        return records

    def from_integration(self, integration) -> list[CapabilityRecord]:
        status_map = {
            "connected": CapabilityStatus.AVAILABLE,
            "degraded": CapabilityStatus.DEGRADED,
            "error": CapabilityStatus.DEGRADED,
        }
        status = status_map.get(integration.status.value, CapabilityStatus.UNAVAILABLE)
        records: list[CapabilityRecord] = []
        for capability in sorted(integration.capabilities):
            permission = "L2" if any(term in capability for term in ("send", "create", "write")) else "L0"
            records.append(self.registry.register(CapabilityRecord(
                capability_id=capability,
                name=capability.replace(".", " ").title(),
                description=f"{integration.name} integration capability",
                source=CapabilitySource.INTEGRATION,
                source_id=integration.id,
                status=status,
                required_permissions=[permission],
                reliability=0.85 if status == CapabilityStatus.AVAILABLE else 0,
                tags=[integration.category, integration.provider, integration.status.value],
            )))
        return records
