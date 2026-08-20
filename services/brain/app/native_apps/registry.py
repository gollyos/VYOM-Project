from __future__ import annotations

from .schemas import AppAdapter


class NativeAppAdapterRegistry:
    """Extensible native app adapter system. Only 1-2 real adapters exist
    yet (VS Code, Windows Terminal) plus a generic visual-fallback
    adapter; more can be added without changing this registry."""

    def __init__(self):
        self._adapters: dict[str, AppAdapter] = {}

    def register(self, adapter: AppAdapter) -> AppAdapter:
        self._adapters[adapter.app_id] = adapter
        return adapter

    def get(self, app_id: str) -> AppAdapter | None:
        return self._adapters.get(app_id)

    def list(self) -> list[AppAdapter]:
        return list(self._adapters.values())
