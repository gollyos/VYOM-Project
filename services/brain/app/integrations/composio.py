from __future__ import annotations

from typing import Any

from app.security.secret_store import SecretStore

# Composio adapter (Phase 13.5) — composiohq/composio, an OPTIONAL
# integration transport. Composio is NOT VYOM's architecture: every
# Composio action is exposed as a normal VYOM capability behind the
# Permission Engine, approvals, SecretStore, audit, budgets, and
# verification. Direct integrations remain preferred where they work
# (Gmail stays native; Composio does not take over). Disabled by
# default; credentials live only in the SecretStore.


class ComposioError(Exception):
    pass


class ComposioTransport:
    """Pluggable transport. Production would speak to a locally running
    Composio OpenAPI service the user configured; tests inject a
    controlled fake. VYOM never signs up for or authenticates to
    Composio on its own."""

    async def execute_action(self, action: str, arguments: dict[str, Any], api_key: str) -> dict[str, Any]:
        raise NotImplementedError("no Composio transport configured")


class MockComposioTransport(ComposioTransport):
    """Deterministic test/demo transport — never used in production."""

    def __init__(self, results: dict[str, dict] | None = None, fail_actions: set[str] | None = None):
        self.results = results or {}
        self.fail_actions = fail_actions or set()
        self.calls: list[dict] = []

    async def execute_action(self, action: str, arguments: dict[str, Any], api_key: str) -> dict[str, Any]:
        self.calls.append({"action": action, "arguments": arguments})
        if action in self.fail_actions:
            raise ComposioError(f"composio action '{action}' failed (mock)")
        return self.results.get(action, {"ok": True, "action": action})


class ComposioAdapter:
    """Optional integration provider adapter. Flow: VYOM Brain →
    Capability Registry → Permission Engine → Composio Adapter →
    External Tool → Evidence → Verification. Composio can never bypass
    any VYOM boundary — it is a transport, and VYOM stays the
    authority."""

    SECRET_REF = "integration/composio/default"
    CAPABILITY_PREFIX = "composio"

    def __init__(self, transport: ComposioTransport | None, secret_store: SecretStore | None = None):
        self.transport = transport
        self.secret_store = secret_store

    @property
    def configured(self) -> bool:
        if self.transport is None:
            return False
        return self.secret_store is not None and self.secret_store.has_secret(self.SECRET_REF)

    def _api_key(self) -> str:
        if self.secret_store is None:
            raise ComposioError("Composio credentials require the SecretStore")
        return self.secret_store.get_secret(self.SECRET_REF)

    def list_actions(self) -> list[dict[str, str]]:
        """Capability metadata for registration into the EXISTING
        Capability Registry — each Composio action becomes a normal
        VYOM capability with a permission level."""
        return [
            {"capability_id": f"{self.CAPABILITY_PREFIX}.send_message", "action": "messaging.send",
             "description": "Send a message through a connected communication tool", "permission": "L2"},
            {"capability_id": f"{self.CAPABILITY_PREFIX}.calendar_event", "action": "calendar.create-event",
             "description": "Create a calendar event through a connected calendar tool", "permission": "L2"},
            {"capability_id": f"{self.CAPABILITY_PREFIX}.crm_upsert", "action": "crm.upsert-contact",
             "description": "Create/update a CRM contact through a connected CRM tool", "permission": "L1"},
        ]

    async def execute(self, capability_id: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Executes AFTER the Permission Engine approved the capability.
        Records transport evidence for the verifier; failures raise so
        the caller can fall back to direct/MCP/browser backends."""
        if not self.configured:
            raise ComposioError("Composio is not configured (optional capability)")
        action = capability_id.removeprefix(f"{self.CAPABILITY_PREFIX}.")
        action_map = {item["capability_id"]: item["action"] for item in self.list_actions()}
        if capability_id not in action_map:
            raise ComposioError(f"unknown Composio capability {capability_id}")
        result = await self.transport.execute_action(action_map[capability_id], arguments, self._api_key())
        return {
            "provider": "composio",
            "capability": capability_id,
            "result": result,
            "evidence": {"transport": "composio", "action": action_map[capability_id]},
        }


class DirectVsComposioPolicy:
    """Rule 20: prefer reliable native/direct integrations; Composio is
    a fallback (or coverage extender), never a replacement that takes
    over working integrations."""

    PREFERRED_NATIVE = {"gmail", "google-calendar", "google-contacts"}

    @classmethod
    def preferred_backend(cls, integration_id: str, composio_available: bool,
                          native_healthy: bool | None = None) -> tuple[str, str]:
        if integration_id in cls.PREFERRED_NATIVE:
            return "native", "reliable direct integration exists — Composio does not take over"
        if composio_available and (native_healthy is False or native_healthy is None):
            return "composio", "no reliable direct integration; Composio covers this capability"
        return "native-or-mcp", "direct/MCP path preferred where healthy; Composio remains fallback"
