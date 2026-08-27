from __future__ import annotations

from pathlib import Path

import yaml

from app.core.config import expand_environment
from app.schemas.routing import ModelDefinition


class ModelRegistry:
    def __init__(self, models: list[ModelDefinition], role_overrides: dict[str, str] | None = None):
        self.models = models
        self.role_overrides = role_overrides or {}

    @classmethod
    def from_yaml(cls, path: Path) -> "ModelRegistry":
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        expanded = expand_environment(raw)
        models = [ModelDefinition.model_validate(item) for item in expanded.get("models", [])]
        roles = expanded.get("roles") or expanded.get("role_overrides") or {}
        return cls(models, role_overrides=roles)

    def enabled(self) -> list[ModelDefinition]:
        return [model for model in self.models if model.enabled and model.model_id.strip()]

    def get(self, key_or_model_id: str) -> ModelDefinition | None:
        return next(
            (model for model in self.models if model.key == key_or_model_id or model.model_id == key_or_model_id),
            None,
        )

    def get_for_role(self, role: str) -> ModelDefinition | None:
        model_key_or_id = self.role_overrides.get(role)
        if not model_key_or_id:
            return None
        return self.get(model_key_or_id)

    def set_role_override(self, role: str, model_id: str) -> None:
        self.role_overrides[role] = model_id


