from __future__ import annotations

from dataclasses import dataclass

from app.schemas.approvals import PermissionLevel


class AuthorizationError(Exception):
    pass


@dataclass(frozen=True)
class ScopeGrant:
    """What a caller may do. Presets never bypass the L0–L3 engine:
    they only adjust which automatic tiers are allowed without an
    approval prompt; L2/L3 always route through the Permission Engine."""

    name: str
    allow_automatic: tuple[PermissionLevel, ...]
    description: str


AUTONOMY_PRESETS: dict[str, ScopeGrant] = {
    "conservative": ScopeGrant(
        name="conservative",
        allow_automatic=(PermissionLevel.L0,),
        description="Only reading and analysis run automatically; every action asks first.",
    ),
    "balanced": ScopeGrant(
        name="balanced",
        allow_automatic=(PermissionLevel.L0, PermissionLevel.L1),
        description="Reads and safe local actions run automatically; external actions ask first.",
    ),
    "autonomous": ScopeGrant(
        name="autonomous",
        allow_automatic=(PermissionLevel.L0, PermissionLevel.L1),
        description="Same engine rules as Balanced, with more proactive background work; "
                    "L2/L3 still always require explicit approval.",
    ),
}


class AuthorizationService:
    """Maps high-level autonomy presets onto the existing permission
    architecture. A preset can never grant L2/L3 without approval."""

    def __init__(self, preset: str = "balanced"):
        if preset not in AUTONOMY_PRESETS:
            raise AuthorizationError(f"Unknown autonomy preset {preset!r}")
        self.preset = preset
        self.grant = AUTONOMY_PRESETS[preset]

    def allowed_automatically(self, level: PermissionLevel) -> bool:
        return level in self.grant.allow_automatic

    def describe(self) -> dict[str, str]:
        return {"preset": self.preset, "allows_automatically": [l.value for l in self.grant.allow_automatic], "description": self.grant.description}

    @staticmethod
    def available_presets() -> list[dict[str, str]]:
        return [
            {"name": grant.name, "description": grant.description,
             "allows_automatically": [level.value for level in grant.allow_automatic]}
            for grant in AUTONOMY_PRESETS.values()
        ]
