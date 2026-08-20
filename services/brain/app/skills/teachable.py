from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.schemas.approvals import PermissionLevel

from .registry import SkillRegistry
from .schemas import (
    SkillBudget, SkillFailurePolicy, SkillInputSlot, SkillInputType, SkillSpec,
    SkillStatus, SkillStep, SkillVerification,
)


_PLACEHOLDER = re.compile(r"^\{\{([a-z][a-z0-9_]{0,63})\}\}$")
_EMBEDDED_PLACEHOLDER = re.compile(r"\{\{([a-z][a-z0-9_]{0,63})\}\}")


class TeachableSkillCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str
    description: str
    category: str = "user-taught"
    input_slots: list[SkillInputSlot] = Field(default_factory=list)
    steps: list[SkillStep] = Field(min_length=1, max_length=50)
    verification_checks: list[str] = Field(default_factory=lambda: ["all_steps_succeeded"], min_length=1)
    required_permissions: PermissionLevel = PermissionLevel.L1
    budget: SkillBudget = Field(default_factory=SkillBudget)

    @model_validator(mode="after")
    def validate_teachable_skill(self):
        if any(step.tool is None for step in self.steps):
            raise ValueError("Every taught step must name a registered tool")
        slots = {slot.name for slot in self.input_slots}
        referenced: set[str] = set()

        def walk(value: Any) -> None:
            if isinstance(value, str):
                referenced.update(_EMBEDDED_PLACEHOLDER.findall(value))
            elif isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)

        for step in self.steps:
            walk(step.inputs)
        unknown = referenced - slots
        if unknown:
            raise ValueError(f"Unknown input placeholders: {', '.join(sorted(unknown))}")
        return self


def _coerce(slot: SkillInputSlot, value: Any) -> Any:
    try:
        if slot.type == SkillInputType.STRING:
            resolved = str(value)
        elif slot.type == SkillInputType.INTEGER:
            if isinstance(value, bool):
                raise ValueError
            resolved = int(value)
        elif slot.type == SkillInputType.NUMBER:
            if isinstance(value, bool):
                raise ValueError
            resolved = float(value)
        elif slot.type == SkillInputType.BOOLEAN:
            if isinstance(value, bool):
                resolved = value
            elif str(value).strip().lower() in {"true", "1", "yes", "on"}:
                resolved = True
            elif str(value).strip().lower() in {"false", "0", "no", "off"}:
                resolved = False
            else:
                raise ValueError
        elif slot.type == SkillInputType.PATH:
            resolved = str(Path(str(value)))
        elif slot.type == SkillInputType.URL:
            resolved = str(value).strip()
            if not resolved.startswith(("http://", "https://")):
                raise ValueError
        else:
            resolved = value
    except (TypeError, ValueError) as error:
        raise ValueError(f"Input {slot.name!r} must be {slot.type.value}") from error
    if slot.choices and resolved not in slot.choices:
        raise ValueError(f"Input {slot.name!r} must be one of {slot.choices}")
    return resolved


def resolve_runtime_inputs(skill: SkillSpec, supplied: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
    known = {slot.name for slot in skill.input_slots}
    unknown = set(supplied) - known
    if unknown:
        raise ValueError(f"Unknown skill inputs: {', '.join(sorted(unknown))}")
    resolved: dict[str, Any] = {}
    sensitive: set[str] = set()
    for slot in skill.input_slots:
        value = supplied.get(slot.name, slot.default)
        if value is None and slot.required:
            raise ValueError(f"Missing required skill input: {slot.name}")
        if value is not None:
            resolved[slot.name] = _coerce(slot, value)
        if slot.sensitive:
            sensitive.add(slot.name)
    return resolved, sensitive


def resolve_templates(value: Any, inputs: dict[str, Any]) -> Any:
    if isinstance(value, str):
        exact = _PLACEHOLDER.fullmatch(value)
        if exact:
            return inputs[exact.group(1)]
        return _EMBEDDED_PLACEHOLDER.sub(lambda match: str(inputs[match.group(1)]), value)
    if isinstance(value, dict):
        return {key: resolve_templates(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_templates(item, inputs) for item in value]
    return value


class TeachableSkillService:
    def __init__(self, registry: SkillRegistry, tool_registry):
        self.registry = registry
        self.tool_registry = tool_registry

    def create(self, payload: TeachableSkillCreate, *, created_by: str = "local-user") -> SkillSpec:
        for step in payload.steps:
            try:
                self.tool_registry.get(step.tool or "")
            except KeyError as error:
                raise ValueError(f"Unknown tool in step {step.id}: {step.tool}") from error
        skill = SkillSpec(
            id=payload.id, name=payload.name, version="1.0.0", description=payload.description,
            category=payload.category, input_slots=payload.input_slots,
            inputs={slot.name: {"type": slot.type.value, "required": slot.required} for slot in payload.input_slots},
            outputs={"step_results": "verified tool outputs"},
            required_capabilities=sorted({step.capability for step in payload.steps}),
            required_tools=sorted({step.tool for step in payload.steps if step.tool}),
            required_permissions=payload.required_permissions, steps=payload.steps,
            verification=SkillVerification(checks=payload.verification_checks),
            failure_policy=SkillFailurePolicy(), budget=payload.budget,
            created_by=created_by, status=SkillStatus.TESTING,
        )
        return self.registry.register(
            skill,
            instructions=(
                "User-taught declarative macro. Runtime values are supplied through typed input slots; "
                "every step executes through VYOM's permission, tool-verification, and evidence boundary."
            ),
            changelog="1.0.0 - Recorded as testing; activation requires explicit approval.",
        )

    def activate(self, skill_id: str) -> SkillSpec:
        skill = self.registry.get(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        if skill.status not in {SkillStatus.TESTING, SkillStatus.APPROVED}:
            raise ValueError(f"Skill cannot be activated from {skill.status.value}")
        skill.status = SkillStatus.ACTIVE
        return self.registry.save(skill)


def parse_skill_command(request: str) -> tuple[str, dict[str, Any]]:
    match = re.search(r"\brun\s+skill\s+([a-z0-9][a-z0-9-]{2,63})(?:\s+with\s+(.+))?$", request.strip(), re.I)
    if not match:
        raise ValueError("Use: run skill <skill-id> with {\"input\": \"value\"}")
    raw = match.group(2)
    if not raw:
        return match.group(1).lower(), {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("Skill inputs after 'with' must be a JSON object") from error
    if not isinstance(data, dict):
        raise ValueError("Skill runtime inputs must be a JSON object")
    return match.group(1).lower(), data
