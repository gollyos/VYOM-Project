from __future__ import annotations

from ..security.authorization import AuthorizationService


class PermissionSetup:
    """Autonomy setup: three understandable presets on top of the
    existing L0–L3 architecture. A preset never bypasses L3 (or any
    approval) — it only selects which levels may run automatically."""

    def __init__(self, authorization: AuthorizationService):
        self.authorization = authorization

    def describe_options(self) -> list[dict]:
        return AuthorizationService.available_presets()

    def apply(self, preset: str) -> dict:
        service = AuthorizationService(preset)  # validates the preset name
        self.authorization.preset = service.preset
        self.authorization.grant = service.grant
        return service.describe()
