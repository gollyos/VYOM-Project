from __future__ import annotations

from ..security.secret_store import SecretStore
from .connection_test import ConnectionTest


class ProviderSetup:
    """Dynamic provider setup built from the Model Registry — no
    per-provider hardcoded UI. select -> enter credentials securely ->
    store in SecretStore -> real health test -> report models."""

    def __init__(self, model_registry, providers, secret_store: SecretStore):
        self.model_registry = model_registry
        self.providers = providers
        self.secret_store = secret_store

    def list_options(self) -> list[dict]:
        options: dict[str, dict] = {}
        for model in self.model_registry.enabled():
            provider = self.providers.get(model.provider)
            if provider is None:
                continue
            entry = options.setdefault(model.provider, {
                "provider": model.provider,
                "credential_hint": getattr(model, "env_key", None) or f"VYOM_SECRET_PROVIDER_{model.provider.upper()}",
                "models": [],
                "configured": bool(provider.configured),
            })
            entry["models"].append({"model_id": model.model_id, "capabilities": sorted(model.capabilities)})
        return sorted(options.values(), key=lambda item: item["provider"])

    def store_credential(self, provider_name: str, api_key: str) -> dict:
        ref = SecretStore.build_ref("provider", provider_name, "default")
        self.secret_store.set_secret(ref, api_key, kind="provider", owner=provider_name)
        # The value is consumed here and never persisted anywhere else.
        del api_key
        return {"provider": provider_name, "secret_ref": ref, "stored": True}

    async def connect(self, provider_name: str, api_key: str) -> dict:
        stored = self.store_credential(provider_name, api_key)
        test = await ConnectionTest.provider(self.providers, provider_name)
        return {**stored, "connection": test}

    async def test(self, provider_name: str) -> dict:
        return await ConnectionTest.provider(self.providers, provider_name)
