from __future__ import annotations

from pathlib import Path

import yaml

from .schemas import SkillSpec


class SkillLoader:
    def load(self, path: Path) -> SkillSpec:
        return SkillSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
