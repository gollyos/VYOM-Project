from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .schemas import SkillSpec


class DuplicateSkillError(ValueError):
    pass


def _tokens(value: str) -> set[str]:
    aliases = {"checking": "check", "validator": "check", "validate": "check", "builds": "build", "project": "project"}
    return {aliases.get(token, token) for token in re.findall(r"[a-z0-9]+", value.lower())}


class SkillRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._skills: dict[str, SkillSpec] = {}

    def load(self) -> int:
        self._skills.clear()
        # Flat skills plus grouped imports (data/skills/developer/...,
        # data/skills/marketing/...) — Phase 13.5 external skill imports.
        paths = list(self.root.glob("*/skill.yaml")) + list(self.root.glob("*/*/skill.yaml"))
        for path in paths:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            skill = SkillSpec.model_validate(raw)
            current = self._skills.get(skill.id)
            if current is None or self._version(skill.version) >= self._version(current.version):
                self._skills[skill.id] = skill
        return len(self._skills)

    def list(self) -> list[SkillSpec]:
        return sorted(self._skills.values(), key=lambda item: item.name.lower())

    def get(self, skill_id: str) -> SkillSpec | None:
        return self._skills.get(skill_id)

    def find_equivalent(self, name: str, description: str = "") -> SkillSpec | None:
        requested = _tokens(f"{name} {description}")
        for skill in self._skills.values():
            existing = _tokens(f"{skill.id} {skill.name} {skill.description}")
            overlap = len(requested & existing) / max(len(requested | existing), 1)
            if skill.id == name or overlap >= 0.45 or {"build", "check"}.issubset(requested & existing):
                return skill
        return None

    def register(self, skill: SkillSpec, *, instructions: str, changelog: str, allow_update: bool = False) -> SkillSpec:
        equivalent = self.find_equivalent(skill.name, skill.description)
        if equivalent and equivalent.id != skill.id:
            raise DuplicateSkillError(f"Equivalent skill already exists: {equivalent.id}")
        current = self._skills.get(skill.id)
        if current and not allow_update:
            raise DuplicateSkillError(f"Skill already exists: {skill.id}")
        if current and self._version(skill.version) <= self._version(current.version):
            raise ValueError("A skill update must increase the semantic version")
        directory = self.root / skill.id
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "tests").mkdir(exist_ok=True)
        versions = directory / ".versions"
        versions.mkdir(exist_ok=True)
        if current:
            (versions / f"{current.version}.yaml").write_text(
                yaml.safe_dump(current.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
            )
        skill.updated_at = datetime.now(timezone.utc)
        (directory / "skill.yaml").write_text(yaml.safe_dump(skill.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
        (directory / "instructions.md").write_text(instructions.strip() + "\n", encoding="utf-8")
        (directory / "CHANGELOG.md").write_text(changelog.strip() + "\n", encoding="utf-8")
        (directory / "tests" / "manifest.yaml").write_text(
            yaml.safe_dump({"checks": skill.verification.checks}, sort_keys=False), encoding="utf-8"
        )
        self._skills[skill.id] = skill
        return skill

    def save(self, skill: SkillSpec) -> SkillSpec:
        directory = self.root / skill.id
        if not directory.exists():
            raise KeyError(skill.id)
        skill.updated_at = datetime.now(timezone.utc)
        (directory / "skill.yaml").write_text(yaml.safe_dump(skill.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
        self._skills[skill.id] = skill
        return skill

    @staticmethod
    def _version(version: str) -> tuple[int, int, int]:
        return tuple(int(part) for part in version.split("."))
