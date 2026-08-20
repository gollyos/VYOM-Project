from __future__ import annotations

from pathlib import Path

import yaml

from .registry import SkillRegistry
from .schemas import SkillSpec


class SkillVersioning:
    def __init__(self, registry: SkillRegistry):
        self.registry = registry

    def rollback(self, skill_id: str, version: str) -> SkillSpec:
        path = self.registry.root / skill_id / ".versions" / f"{version}.yaml"
        if not path.exists():
            raise KeyError(f"Skill version not found: {skill_id}@{version}")
        prior = SkillSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        current = self.registry.get(skill_id)
        if current:
            current_path = self.registry.root / skill_id / ".versions" / f"{current.version}.yaml"
            current_path.write_text(yaml.safe_dump(current.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
        return self.registry.save(prior)
