from __future__ import annotations


class IntegrationSetup:
    """Dynamic integration setup over the Integration Registry. Scopes
    are shown before any connection; nothing authenticates silently."""

    def __init__(self, integration_registry):
        self.integration_registry = integration_registry

    def list_options(self) -> list[dict]:
        options = []
        for record in self.integration_registry.list():
            options.append({
                "id": record.id,
                "provider": record.provider,
                "category": record.category,
                "status": record.status.value,
                "scopes_requested": list(getattr(record, "scopes", []) or []),
                "connectable": hasattr(self.integration_registry, "start_oauth") or record.provider in ("gmail", "google-calendar", "google-contacts"),
            })
        return options

    async def begin_connection(self, integration_id: str) -> dict:
        record = self.integration_registry.get(integration_id)
        return {
            "integration": record.id,
            "provider": record.provider,
            "scopes_requested": list(getattr(record, "scopes", []) or []),
            "authorization_url_pending": True,  # real OAuth transport stays disabled-by-default per docs/INTEGRATION_ARCHITECTURE
        }

    async def verify(self, integration_id: str) -> dict:
        record = self.integration_registry.get(integration_id)
        healthy = await self.integration_registry.health_check(integration_id)
        return {"integration": record.id, "status": record.status.value, "healthy": healthy}
