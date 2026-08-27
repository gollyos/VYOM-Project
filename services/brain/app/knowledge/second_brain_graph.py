"""
VYOM Integrated Second Brain & Interactive Neural Graph Engine
==============================================================
Inspired by:
- Hermes Agent Memory Graph (Visualizing skills, learned memory nodes & active states)
- Graphify & Obsidian Vault Auto-Linking (Bi-directional linking, exam syllabus indexing)
- Warmwind OS Computer-Use Action Queue
- Life-to-Business Super Intelligence (UPSC/Exam prep to Client/Trading pipelines)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

GRAPH_STORAGE_PATH = Path("services/brain/data/second_brain_graph.json")


@dataclass
class GraphNode:
    id: str
    label: str
    node_type: str  # 'MEMORY', 'SKILL', 'EXAM_TOPIC', 'CLIENT_ACCOUNT', 'TRADING_ASSET', 'TOOL'
    category: str
    description: str
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class GraphEdge:
    source: str
    target: str
    relation: str  # 'USES_TOOL', 'BELONGS_TO_NICHE', 'SYLLABUS_PREREQUISITE', 'EXECUTES_FOR', 'DERIVED_FROM'
    weight: float = 1.0


class SecondBrainGraphEngine:
    """Manages the full-system bi-directional knowledge, memory, and skill graph."""

    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or GRAPH_STORAGE_PATH
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[GraphEdge] = []
        self._load_or_bootstrap()

    def _load_or_bootstrap(self) -> None:
        if self.storage_path.exists():
            try:
                raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
                for n in raw.get("nodes", []):
                    node = GraphNode(**n)
                    self.nodes[node.id] = node
                for e in raw.get("edges", []):
                    self.edges.append(GraphEdge(**e))
                return
            except Exception:
                pass
        self._bootstrap_full_system_graph()

    def _bootstrap_full_system_graph(self) -> None:
        # 1. Master Brain & Corporate Nodes
        self.add_node(GraphNode("node_vyom_ceo", "VYOM Master CEO", "SKILL", "Core", "Central Orchestration Authority"))
        self.add_node(GraphNode("node_hermes_react", "Hermes Autonomous ReAct Loop", "SKILL", "Reasoning", "Scratchpad tool execution & error reflection"))
        self.add_node(GraphNode("node_grok_intelligence", "Grok Live Intelligence", "SKILL", "Research", "Real-time web stream & market grounding"))
        self.add_node(GraphNode("node_openclaw_scraper", "OpenClaw Browser & Screen Bot", "SKILL", "Automation", "Playwright crawler & coordinate clicker"))
        self.add_node(GraphNode("node_prime_director", "Prime Video Director", "SKILL", "Media", "Multi-modal video pacing & 0-3s retention hooks"))

        # 2. Client & Social Media Nodes
        self.add_node(GraphNode("acc_gunjan_ai", "@gunjan.ai_automation", "CLIENT_ACCOUNT", "Instagram", "Niche: AI Agents & Automation", {"upload_time": "19:00 IST"}))
        self.add_node(GraphNode("acc_gunjan_fit", "@gunjan.fitmatrix", "CLIENT_ACCOUNT", "Instagram", "Niche: Fitness & Calisthenics", {"upload_time": "07:30 IST"}))
        self.add_node(GraphNode("acc_gunjan_fin", "@gunjan.alphatrader", "CLIENT_ACCOUNT", "Instagram", "Niche: Finance & Stock Market", {"upload_time": "08:45 IST"}))
        self.add_node(GraphNode("acc_client_acme", "Client Acme Health", "CLIENT_ACCOUNT", "Client Deliverables", "Niche: Organic Wellness", {"state": "Active"}))

        # 3. Exam & Second Brain Syllabus Nodes
        self.add_node(GraphNode("exam_upsc_gs1", "UPSC GS-1: History & Geography", "EXAM_TOPIC", "Education", "Core syllabus module with PYQ mapping"))
        self.add_node(GraphNode("exam_upsc_gs2", "UPSC GS-2: Polity & Governance", "EXAM_TOPIC", "Education", "Constitution, acts and current bills"))
        self.add_node(GraphNode("exam_upsc_gs3", "UPSC GS-3: Economy, Tech & Environment", "EXAM_TOPIC", "Education", "Economy models, AI technology, climate policies"))
        self.add_node(GraphNode("exam_cs_dsa", "Computer Science: DSA & Systems", "EXAM_TOPIC", "Career", "Algorithms, operating systems & system design"))

        # 4. Trading & Financial Assets
        self.add_node(GraphNode("asset_aapl", "AAPL (Apple Inc.)", "TRADING_ASSET", "Equity", "Tech stock tracking in Paper Portfolio"))
        self.add_node(GraphNode("asset_btc", "BTC (Bitcoin)", "TRADING_ASSET", "Crypto", "Live crypto spot market feed"))

        # Edges (Relationships)
        self.add_edge("node_vyom_ceo", "node_hermes_react", "EXECUTES_FOR")
        self.add_edge("node_vyom_ceo", "node_grok_intelligence", "EXECUTES_FOR")
        self.add_edge("node_vyom_ceo", "node_openclaw_scraper", "EXECUTES_FOR")
        self.add_edge("node_prime_director", "acc_gunjan_ai", "BELONGS_TO_NICHE")
        self.add_edge("node_prime_director", "acc_gunjan_fit", "BELONGS_TO_NICHE")
        self.add_edge("node_grok_intelligence", "asset_aapl", "USES_TOOL")
        self.add_edge("node_grok_intelligence", "exam_upsc_gs3", "SYLLABUS_PREREQUISITE")
        self.add_edge("node_hermes_react", "exam_cs_dsa", "USES_TOOL")
        self._save()

    def _save(self) -> None:
        try:
            data = {
                "nodes": [asdict(n) for n in self.nodes.values()],
                "edges": [asdict(e) for e in self.edges],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self.storage_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            pass

    def add_node(self, node: GraphNode) -> GraphNode:
        self.nodes[node.id] = node
        self._save()
        return node

    def add_edge(self, source_id: str, target_id: str, relation: str, weight: float = 1.0) -> None:
        self.edges.append(GraphEdge(source=source_id, target=target_id, relation=relation, weight=weight))
        self._save()

    def get_graph_data(self) -> dict[str, Any]:
        """Returns ready-to-render graph data for React Three Fiber / 3D Canvas / D3."""
        return {
            "total_nodes": len(self.nodes),
            "total_edges": len(self.edges),
            "nodes": [
                {
                    "id": n.id,
                    "label": n.label,
                    "type": n.node_type,
                    "category": n.category,
                    "description": n.description,
                    "properties": n.properties,
                }
                for n in self.nodes.values()
            ],
            "links": [
                {
                    "source": e.source,
                    "target": e.target,
                    "relation": e.relation,
                    "weight": e.weight,
                }
                for e in self.edges
            ],
        }


_default_second_brain: SecondBrainGraphEngine | None = None

def get_second_brain_graph() -> SecondBrainGraphEngine:
    global _default_second_brain
    if _default_second_brain is None:
        _default_second_brain = SecondBrainGraphEngine()
    return _default_second_brain
