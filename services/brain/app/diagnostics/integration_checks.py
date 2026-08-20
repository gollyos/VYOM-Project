from __future__ import annotations

from .system_checks import CheckResult


class IntegrationChecks:
    def __init__(self, integration_registry, mcp_registry=None, device_registry=None):
        self.integration_registry = integration_registry
        self.mcp_registry = mcp_registry
        self.device_registry = device_registry

    def run_all(self) -> list[CheckResult]:
        results: list[CheckResult] = []
        for integration in self.integration_registry.list():
            status = str(getattr(integration, "status", "disconnected")).lower()
            name = getattr(integration, "provider", getattr(integration, "id", "integration"))
            if status in ("connected", "ok"):
                results.append(CheckResult(f"integration:{name}", "PASS", "Connected"))
            elif status in ("error", "failed"):
                results.append(CheckResult(f"integration:{name}", "FAIL", f"Integration reports {status}"))
            else:
                results.append(CheckResult(f"integration:{name}", "WARNING", f"Disconnected ({status or 'unconfigured'}); optional"))
        if self.mcp_registry is not None:
            servers = list(getattr(self.mcp_registry, "servers", {}).keys())
            if servers:
                results.append(CheckResult("mcp_servers", "WARNING", f"{len(servers)} MCP server(s) configured; trust stays restricted", {"servers": servers}))
            else:
                results.append(CheckResult("mcp_servers", "PASS", "No external MCP servers configured"))
        if self.device_registry is not None:
            nodes = self.device_registry.list()
            trusted = [node for node in nodes if node.trust_level.value == "trusted"]
            revoked = [node for node in nodes if node.trust_level.value == "revoked"]
            results.append(CheckResult(
                "device_nodes", "PASS" if trusted or not nodes else "WARNING",
                f"{len(trusted)} trusted, {len(revoked)} revoked nodes",
            ))
        return results
