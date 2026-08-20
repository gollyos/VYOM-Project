from __future__ import annotations

from .schemas import StrategySpec, StrategyStatus, utc_now


def _bump(version: str) -> str:
    parts = version.split(".")
    try:
        parts[-1] = str(int(parts[-1]) + 1)
    except ValueError:
        return f"{version}.1"
    return ".".join(parts)


def new_version(spec: StrategySpec, *, reason: str, **overrides) -> StrategySpec:
    """Creates a new `StrategySpec` version rather than mutating `spec` in
    place (rule 61/23). An active paper-testing strategy is never silently
    modified — a rule change always produces `momentum-v1.0` ->
    `momentum-v1.1` with the reason recorded in the changelog."""
    data = spec.model_dump()
    data.update(overrides)
    data["id"] = f"strategy_{spec.name}_{_bump(spec.version)}".replace(" ", "-")
    data["version"] = _bump(spec.version)
    data["status"] = StrategyStatus.DRAFT
    data["changelog"] = [*spec.changelog, f"{data['version']}: {reason}"]
    data["created_at"] = utc_now()
    data["updated_at"] = utc_now()
    return StrategySpec.model_validate(data)
