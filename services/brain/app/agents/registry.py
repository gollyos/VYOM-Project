from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .schemas import AgentSpec, AgentStatus


class AgentRegistry:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._agents: dict[str, AgentSpec] = {}

    def load(self) -> int:
        self._agents.clear()
        for path in self.root.glob("*/agent.yaml"):
            agent = AgentSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
            self._agents[agent.id] = agent
        return len(self._agents)

    def seed(self, config_path: Path) -> int:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        for seed in raw.get("seeds", []):
            if seed["id"] in self._agents:
                continue
            agent = AgentSpec(
                id=seed["id"], name=seed["name"], role=seed["role"],
                description=seed["role"], goals=[f"Perform {seed['role']} responsibilities safely"],
                capabilities=seed.get("capabilities", ["result.verify"]),
                memory_scope=["task"], permissions="L1", status=AgentStatus.READY,
                verification_policy=["require evidence", "respect central permission engine"],
            )
            self.register(agent)
        return len(self._agents)

    def list(self) -> list[AgentSpec]:
        return sorted(self._agents.values(), key=lambda item: item.name.lower())

    def get(self, agent_id: str) -> AgentSpec | None:
        return self._agents.get(agent_id)

    def find_equivalent(self, name: str, role: str = "") -> AgentSpec | None:
        tokens = set(re.findall(r"[a-z0-9]+", f"{name} {role}".lower()))
        for agent in self._agents.values():
            existing = set(re.findall(r"[a-z0-9]+", f"{agent.id} {agent.name} {agent.role}".lower()))
            if agent.id == name or len(tokens & existing) / max(len(tokens | existing), 1) >= 0.5:
                return agent
        return None

    def register(self, agent: AgentSpec) -> AgentSpec:
        directory = self.root / agent.id
        directory.mkdir(parents=True, exist_ok=True)
        agent.updated_at = datetime.now(timezone.utc)
        (directory / "agent.yaml").write_text(yaml.safe_dump(agent.model_dump(mode="json"), sort_keys=False), encoding="utf-8")
        changelog = directory / "CHANGELOG.md"
        if not changelog.exists():
            changelog.write_text(f"# {agent.name} Changelog\n\n## {agent.version}\n- Declarative agent registered.\n", encoding="utf-8")
        self._agents[agent.id] = agent
        return agent

    def save(self, agent: AgentSpec) -> AgentSpec:
        if agent.id not in self._agents:
            raise KeyError(agent.id)
        return self.register(agent)
