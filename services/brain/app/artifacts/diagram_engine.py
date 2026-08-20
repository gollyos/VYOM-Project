from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DiagramType(str, Enum):
    WORKFLOW = "workflow"
    ARCHITECTURE = "architecture"
    DEPENDENCY = "dependency"
    CAUSAL = "causal"
    TIMELINE = "timeline"
    ORGANIZATION = "organization"
    AGENT_WORKFLOW = "agent_workflow"
    RESEARCH_MAP = "research_map"


@dataclass
class DiagramNode:
    id: str
    label: str


@dataclass
class DiagramEdge:
    source: str
    target: str
    label: str = ""


@dataclass
class DiagramSpec:
    diagram_type: DiagramType
    nodes: list[DiagramNode] = field(default_factory=list)
    edges: list[DiagramEdge] = field(default_factory=list)
    title: str = ""


class DiagramEngine:
    """Diagram content comes from structured node/edge data, never from
    random positioning. Output is real, renderable Mermaid text."""

    def render_mermaid(self, spec: DiagramSpec) -> str:
        if not spec.nodes:
            raise ValueError("Diagram requires at least one node")
        vertical_types = {DiagramType.WORKFLOW, DiagramType.ORGANIZATION, DiagramType.AGENT_WORKFLOW, DiagramType.TIMELINE}
        direction = "TD" if spec.diagram_type in vertical_types else "LR"
        lines = [f"flowchart {direction}"]
        for node in spec.nodes:
            safe_label = node.label.replace('"', "'")
            lines.append(f'    {node.id}["{safe_label}"]')
        for edge in spec.edges:
            arrow = f"-->|{edge.label}|" if edge.label else "-->"
            lines.append(f"    {edge.source} {arrow} {edge.target}")
        return "\n".join(lines)

    @staticmethod
    def validate(spec: DiagramSpec, rendered_text: str) -> list[str]:
        errors: list[str] = []
        node_ids = {node.id for node in spec.nodes}
        for node in spec.nodes:
            if node.id not in rendered_text:
                errors.append(f"Missing node in rendered diagram: {node.id}")
        for edge in spec.edges:
            if edge.source not in node_ids or edge.target not in node_ids:
                errors.append(f"Edge references unknown node: {edge.source}->{edge.target}")
        return errors
