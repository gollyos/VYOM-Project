from __future__ import annotations

from .schemas import MemoryRelationship, RelationType
from .store import MemoryStore


class RelationshipManager:
    def __init__(self, store: MemoryStore):
        self.store = store

    async def connect(self, source_id: str, target_id: str, relation: RelationType, confidence: float = 0.8) -> MemoryRelationship:
        if not await self.store.get(source_id, touch=False) or not await self.store.get(target_id, touch=False):
            raise ValueError("Relationships require two existing memories")
        return await self.store.save_relationship(
            MemoryRelationship(source_id=source_id, target_id=target_id, relation=relation, confidence=confidence)
        )

    async def graph(self, memory_id: str, depth: int = 1) -> dict:
        depth = min(max(depth, 1), 3)
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        frontier = {memory_id}
        visited: set[str] = set()
        for _ in range(depth):
            next_frontier: set[str] = set()
            for current in frontier - visited:
                visited.add(current)
                memory = await self.store.get(current, touch=False)
                if memory:
                    nodes[current] = {"id": current, "label": memory.title, "type": memory.type.value}
                for relation in await self.store.relationships(current):
                    edges.append({"from": relation.source_id, "to": relation.target_id, "relation": relation.relation.value})
                    next_frontier.update({relation.source_id, relation.target_id})
            frontier = next_frontier
        for node_id in frontier - visited:
            memory = await self.store.get(node_id, touch=False)
            if memory:
                nodes[node_id] = {"id": node_id, "label": memory.title, "type": memory.type.value}
        unique_edges = {(edge["from"], edge["to"], edge["relation"]): edge for edge in edges}
        return {"nodes": list(nodes.values()), "edges": list(unique_edges.values())}
