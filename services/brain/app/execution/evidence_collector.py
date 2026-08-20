from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.tools.result import EvidenceItem


class EvidenceCollector:
    def __init__(self, audit_path: Path):
        self.audit_path = audit_path
        self._lock = asyncio.Lock()
        self._by_task: dict[str, list[EvidenceItem]] = {}

    async def record(self, task_id: str, evidence: EvidenceItem) -> None:
        self._by_task.setdefault(task_id, []).append(evidence)
        record = {"task_id": task_id, **evidence.model_dump(mode="json")}
        async with self._lock:
            await asyncio.to_thread(self._append, record)

    def _append(self, record: dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, separators=(",", ":")) + "\n")

    def bundle(self, task_id: str) -> list[EvidenceItem]:
        return list(self._by_task.get(task_id, []))
