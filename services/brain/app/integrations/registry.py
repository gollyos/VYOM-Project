from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.persistence.database import Database

from .provider import IntegrationProvider
from .schemas import IntegrationRecord, IntegrationStatus, OAuthStart
from .secrets import SecretVault


class IntegrationRegistry:
    def __init__(self, database: Database, vault: SecretVault) -> None:
        self.database = database
        self.vault = vault
        self.records: dict[str, IntegrationRecord] = {}
        self.providers: dict[str, IntegrationProvider] = {}
        self._oauth_states: dict[str, str] = {}

    @classmethod
    async def from_yaml(cls, path: Path, database: Database, vault: SecretVault) -> "IntegrationRegistry":
        registry = cls(database, vault)
        document = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
        for item in document.get("integrations", []):
            record = IntegrationRecord.model_validate(item)
            registry.records[record.id] = record
        await registry._load_state()
        return registry

    def register_provider(self, integration_id: str, provider: IntegrationProvider) -> None:
        if integration_id not in self.records:
            raise KeyError(integration_id)
        self.providers[integration_id] = provider

    async def _load_state(self) -> None:
        connection = self.database.require_connection()
        rows = await (await connection.execute("SELECT id, state_json FROM integrations")).fetchall()
        for row in rows:
            if row["id"] in self.records:
                saved = IntegrationRecord.model_validate_json(row["state_json"])
                configured = self.records[row["id"]]
                saved.enabled = configured.enabled
                saved.capabilities = configured.capabilities
                self.records[row["id"]] = saved

    async def _save(self, record: IntegrationRecord) -> None:
        record.updated_at = datetime.now(timezone.utc)
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO integrations(id, provider, category, status, state_json, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET status=excluded.status,
               state_json=excluded.state_json, updated_at=excluded.updated_at""",
            (record.id, record.provider, record.category, record.status.value,
             record.model_dump_json(), record.updated_at.isoformat()),
        )
        await connection.commit()

    def list(self) -> list[IntegrationRecord]:
        return sorted(self.records.values(), key=lambda item: (item.category, item.name))

    def get(self, integration_id: str) -> IntegrationRecord:
        if integration_id not in self.records:
            raise KeyError(integration_id)
        return self.records[integration_id]

    def is_connected(self, integration_id: str) -> bool:
        return self.get(integration_id).status == IntegrationStatus.CONNECTED

    async def begin_oauth(self, integration_id: str) -> OAuthStart:
        record = self.get(integration_id)
        provider = self.providers.get(integration_id)
        if not record.enabled or provider is None:
            raise RuntimeError(f"{record.name} is not configured")
        state = secrets.token_urlsafe(32)
        self._oauth_states[integration_id] = state
        record.status = IntegrationStatus.CONNECTING
        await self._save(record)
        return OAuthStart(authorization_url=await provider.begin_oauth(state), state=state)

    async def complete_oauth(self, integration_id: str, code: str, state: str) -> IntegrationRecord:
        record = self.get(integration_id)
        expected = self._oauth_states.pop(integration_id, None)
        if expected is None or not secrets.compare_digest(expected, state):
            raise ValueError("Invalid or expired OAuth state")
        provider = self.providers.get(integration_id)
        if provider is None:
            raise RuntimeError(f"{record.name} provider is unavailable")
        token_bundle = await provider.complete_oauth(code)
        self.vault.set(f"oauth:{integration_id}", json.dumps(token_bundle).encode("utf-8"))
        record.status = IntegrationStatus.CONNECTED
        record.last_error = None
        await self._save(record)
        return record

    async def refresh_health(self, integration_id: str) -> IntegrationRecord:
        record = self.get(integration_id)
        provider = self.providers.get(integration_id)
        record.last_health_check = datetime.now(timezone.utc)
        if provider is None or not record.enabled:
            record.status = IntegrationStatus.DISCONNECTED
            record.last_error = "Provider is not configured"
        else:
            healthy, error = await provider.health()
            record.status = IntegrationStatus.CONNECTED if healthy else IntegrationStatus.DEGRADED
            record.last_error = error
        await self._save(record)
        return record

    async def disconnect(self, integration_id: str) -> IntegrationRecord:
        record = self.get(integration_id)
        provider = self.providers.get(integration_id)
        if provider is not None:
            await provider.disconnect()
        self.vault.delete(f"oauth:{integration_id}")
        record.status = IntegrationStatus.DISCONNECTED
        record.account_label = None
        record.last_error = None
        await self._save(record)
        return record
