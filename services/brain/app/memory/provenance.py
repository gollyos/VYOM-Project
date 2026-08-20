from __future__ import annotations

from .schemas import MemoryEntry


def explain_provenance(memory: MemoryEntry) -> list[dict]:
    return [item.model_dump(mode="json") for item in memory.provenance]
