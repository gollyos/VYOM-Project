"""brain_graph/graph_engine.py — canonical alias for the Brain Graph subsystem.

The actual implementation lives in ``BrainGraphService`` (service.py).
This module exposes ``GraphEngine`` as the public name so that any code
(tests, runtime executor, audit scripts) can import it without knowing
the internal naming convention.
"""
from __future__ import annotations

from .schemas import BrainEdge, BrainGraph, BrainNode, BrainRelation, ConnectRequest
from .service import BrainGraphService as GraphEngine

__all__ = [
    "GraphEngine",
    "BrainGraphService",
    "BrainEdge",
    "BrainGraph",
    "BrainNode",
    "BrainRelation",
    "ConnectRequest",
]

# Re-export the original name too so both spellings always work
BrainGraphService = GraphEngine
