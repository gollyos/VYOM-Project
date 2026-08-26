"""3D Memory Visualization API — returns memory graph as nodes/edges for rendering.

This endpoint powers the holographic 3D knowledge graph display.
Each memory is a node, relationships are edges. Colors indicate
trust grade, size indicates importance, pulsing indicates recent access.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/memory-viz", tags=["memory-viz"])


class MemoryNode(BaseModel):
    """A node in the 3D memory graph."""
    id: str
    label: str
    type: str  # person | semantic | preference | episodic | decision
    trust_grade: str = "C"  # A | B | C | D
    importance: float = 0.5  # 0-1
    confidence: float = 0.5
    last_accessed: str = ""
    x: float = 0.0  # 3D position
    y: float = 0.0
    z: float = 0.0
    color: str = "#79aaa8"  # default color
    size: float = 1.0


class MemoryEdge(BaseModel):
    """An edge (relationship) between two memory nodes."""
    source: str
    target: str
    relationship: str = "related_to"
    weight: float = 0.5


class MemoryGraph(BaseModel):
    """Complete 3D memory graph."""
    nodes: list[MemoryNode]
    edges: list[MemoryEdge]
    stats: dict
    layout: str = "force-directed"


# Trust grade colors
TRUST_COLORS = {
    "A": "#2ecc71",  # Green — high trust
    "B": "#3498db",  # Blue — good trust
    "C": "#f39c12",  # Orange — moderate trust
    "D": "#e74c3c",  # Red — low trust
}

# Memory type colors
TYPE_COLORS = {
    "person": "#9b59b6",
    "semantic": "#3498db",
    "preference": "#e67e22",
    "episodic": "#1abc9c",
    "decision": "#e74c3c",
    "client": "#2ecc71",
}


@router.get("/graph")
async def get_memory_graph(request: Request, limit: int = 200) -> dict:
    """Get the full memory graph for 3D visualization."""
    memory_manager = getattr(request.app.state, "memory_manager", None)
    if memory_manager is None:
        return {"nodes": [], "edges": [], "stats": {"total": 0}}

    from app.memory.schemas import MemoryQuery
    results = await memory_manager.search(MemoryQuery(text="", limit=limit))

    nodes = []
    edges = []
    node_ids = set()

    for hit in results:
        mem = hit.memory
        node_id = mem.id

        if node_id in node_ids:
            continue
        node_ids.add(node_id)

        # Determine color from trust
        trust_grade = getattr(mem, "trust_grade", "C")
        color = TRUST_COLORS.get(trust_grade, TRUST_COLORS["C"])

        # Determine type color
        mem_type = mem.type.value if hasattr(mem.type, 'value') else str(mem.type)
        type_color = TYPE_COLORS.get(mem_type, "#79aaa8")

        nodes.append(MemoryNode(
            id=node_id,
            label=mem.title[:50] if mem.title else node_id[:20],
            type=mem_type,
            trust_grade=trust_grade,
            importance=mem.importance if hasattr(mem, 'importance') else 0.5,
            confidence=mem.confidence,
            last_accessed=mem.updated_at.isoformat() if hasattr(mem, 'updated_at') and mem.updated_at else "",
            color=type_color,
            size=max(0.5, mem.confidence),
        ))

    # Add edges from relationships
    if memory_manager:
        try:
            for node_id in list(node_ids)[:50]:  # limit to avoid overload
                rels = await memory_manager.store.relationships(node_id)
                for rel in rels:
                    target = rel.target_id if rel.source_id == node_id else rel.source_id
                    if target in node_ids:
                        edges.append(MemoryEdge(
                            source=node_id,
                            target=target,
                            relationship=rel.relation.value if hasattr(rel.relation, 'value') else "related_to",
                        ))
        except Exception:
            pass

    return {
        "nodes": [n.model_dump() for n in nodes],
        "edges": [e.model_dump() for e in edges],
        "stats": {
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "types": {},
            "trust_distribution": {"A": 0, "B": 0, "C": 0, "D": 0},
        },
        "layout": "force-directed",
    }


@router.get("/stats")
async def get_memory_stats(request: Request) -> dict:
    """Get memory statistics for the dashboard."""
    memory_manager = getattr(request.app.state, "memory_manager", None)
    if memory_manager is None:
        return {"total": 0}

    from app.memory.schemas import MemoryQuery
    results = await memory_manager.search(MemoryQuery(text="", limit=500))

    type_counts = {}
    trust_counts = {"A": 0, "B": 0, "C": 0, "D": 0}

    for hit in results:
        mem = hit.memory
        mem_type = mem.type.value if hasattr(mem.type, 'value') else str(mem.type)
        type_counts[mem_type] = type_counts.get(mem_type, 0) + 1

        trust = getattr(mem, "trust_grade", "C")
        trust_counts[trust] = trust_counts.get(trust, 0) + 1

    return {
        "total": len(results),
        "types": type_counts,
        "trust_distribution": trust_counts,
    }
