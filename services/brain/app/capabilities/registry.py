from __future__ import annotations

import re

from app.tools.registry import ToolRegistry

from .schemas import CapabilityRecord, CapabilitySource, CapabilityStatus, verified_now


class CapabilityRegistry:
    def __init__(self):
        self._records: dict[str, CapabilityRecord] = {}

    def register(self, record: CapabilityRecord) -> CapabilityRecord:
        self._records[record.capability_id] = record
        return record

    def get(self, capability_id: str) -> CapabilityRecord | None:
        return self._records.get(capability_id)

    def list(self, *, status: CapabilityStatus | None = None) -> list[CapabilityRecord]:
        values = list(self._records.values())
        if status:
            values = [item for item in values if item.status == status]
        return sorted(values, key=lambda item: item.capability_id)

    def search(self, query: str, limit: int = 10) -> list[CapabilityRecord]:
        # Word-boundary token matching: splitting on underscores too means
        # "build" matches the identifier "coding.build_check" without a
        # short common word like "our" coincidentally matching inside an
        # unrelated word like "sources" (a plain substring check would).
        tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
        ranked: list[tuple[float, CapabilityRecord]] = []
        for record in self._records.values():
            haystack = f"{record.capability_id} {record.name} {record.description} {' '.join(record.tags)}".lower()
            haystack_tokens = set(re.findall(r"[a-z0-9]+", haystack))
            score = len(tokens & haystack_tokens) + record.reliability
            if score > record.reliability or not tokens:
                ranked.append((score, record))
        return [item for _, item in sorted(ranked, key=lambda pair: pair[0], reverse=True)[:limit]]

    def supports(self, required: list[str]) -> bool:
        return all(
            (record := self._records.get(capability)) is not None
            and record.status == CapabilityStatus.AVAILABLE
            for capability in required
        )

    @classmethod
    async def from_tools(cls, tools: ToolRegistry) -> "CapabilityRegistry":
        registry = cls()
        for tool in tools.list():
            metadata = tool.metadata
            health = await tool.health()
            registry.register(CapabilityRecord(
                capability_id=f"{metadata.name}.execute",
                name=metadata.name.replace("_", " ").title(),
                description=metadata.description,
                source=CapabilitySource.BUILTIN_TOOL,
                source_id=metadata.name,
                status=CapabilityStatus.AVAILABLE if health.get("healthy") else CapabilityStatus.UNAVAILABLE,
                required_permissions=metadata.required_permissions,
                inputs=metadata.input_schema,
                outputs=metadata.output_schema,
                reliability=0.9 if health.get("healthy") else 0,
                last_verified=verified_now() if health.get("healthy") else None,
                tags=[metadata.category, metadata.risk_level],
            ))
        aliases = {
            "filesystem.read": "filesystem.execute",
            "filesystem.write": "filesystem.execute",
            "terminal.execute": "terminal.execute",
            "git.diff": "git.execute",
            "browser.read": "browser.execute",
            "browser.verify": "browser.execute",
            "result.verify": "screenshot.execute",
            "coding.build_check": "terminal.execute",
            "coding.verify": "terminal.execute",
            "memory.search": "filesystem.execute",
            "task.plan": "filesystem.execute",
            "task.delegate": "filesystem.execute",
        }
        for alias, target in aliases.items():
            base = registry.get(target)
            if base:
                registry.register(base.model_copy(update={"capability_id": alias, "name": alias.replace(".", " ").title()}))
        return registry
