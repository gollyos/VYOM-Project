from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Iterable

import aiosqlite

from app.persistence.database import Database
from app.security.redaction import redact_text

from .schemas import BrainEdge, BrainGraph, BrainNode, BrainRelation, ConnectRequest


CORE_ID = "core:vyom"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(kind: str, native_id: str) -> str:
    return f"{kind}:{native_id}"


def _edge_id(source_id: str, target_id: str, relation: BrainRelation, origin: str) -> str:
    digest = hashlib.sha256(f"{source_id}|{target_id}|{relation.value}|{origin}".encode()).hexdigest()[:24]
    return f"brainrel_{digest}"


def _text(value: Any, limit: int) -> str:
    if value is None:
        return ""
    return redact_text(" ".join(str(value).split()))[:limit]


class BrainGraphService:
    """One traversable relationship layer over VYOM's authoritative stores.

    Nodes are a rebuildable projection, not a second source of truth. Explicit
    user/runtime relationships persist separately and survive projection
    refreshes. Only operational summaries are indexed; secrets, raw content,
    hidden reasoning and highly-sensitive memories never enter this graph.
    """

    JSON_SOURCES = (
        ("tasks", "task_json"),
        ("memories", "memory_json"),
        ("crm_records", "record_json"),
        ("artifacts", "manifest_json"),
        ("commitments", "commitment_json"),
        ("goals", "goal_json"),
        ("milestones", "milestone_json"),
        ("habits", "habit_json"),
        ("automations", "automation_json"),
        ("automation_runs", "run_json"),
        ("experiences", "experience_json"),
        ("adaptive_strategies", "strategy_json"),
        ("nodes", "node_json"),
    )

    def __init__(self, database: Database, *, skill_registry=None, agent_registry=None,
                 capability_registry=None):
        self.database = database
        self.skill_registry = skill_registry
        self.agent_registry = agent_registry
        self.capability_registry = capability_registry
        self._refresh_lock = asyncio.Lock()
        self._refresh_task: asyncio.Task | None = None
        self._last_refresh_monotonic = 0.0
        self.refreshed_at = _now()

    def start_refresh(self) -> asyncio.Task:
        if self._refresh_task is None or self._refresh_task.done():
            self._refresh_task = asyncio.create_task(self.refresh(), name="vyom-brain-graph-refresh")
        return self._refresh_task

    async def ensure_fresh(self, max_age_seconds: float = 60.0) -> None:
        """Keep graph projection current without adding command latency.

        Refresh is deliberately background work. Cognitive retrieval reads the
        last consistent projection while a new one is built; it must never pay
        a multi-second all-store rebuild on the user's command path.
        """
        if self._last_refresh_monotonic == 0:
            # First boot has no last-consistent projection to serve. Await
            # the one startup build once; all later refreshes stay off the
            # command path and continue serving the previous projection.
            await self.start_refresh()
            return
        if time.monotonic() - self._last_refresh_monotonic > max_age_seconds:
            self.start_refresh()

    async def close(self) -> None:
        if self._refresh_task is not None and not self._refresh_task.done():
            await asyncio.gather(self._refresh_task, return_exceptions=True)

    async def refresh(self) -> dict[str, int]:
        async with self._refresh_lock:
            nodes: dict[str, BrainNode] = {
                CORE_ID: BrainNode(
                    id=CORE_ID,
                    native_id="vyom",
                    kind="core",
                    label="VYOM Intelligence Core",
                    summary="Persistent goals, memory, world state, capabilities, permissions, experience, decisions and evidence.",
                    status="active",
                    source_store="brain",
                    updated_at=_now(),
                )
            }
            candidate_edges: list[BrainEdge] = []

            for table, json_column in self.JSON_SOURCES:
                for payload in await self._read_json_rows(table, json_column):
                    self._project_payload(table, payload, nodes, candidate_edges)

            await self._project_memory_relationships(nodes, candidate_edges)

            self._project_registries(nodes, candidate_edges)

            # Every durable item belongs to the one VYOM Brain. Specific
            # semantic edges remain separate and are what retrieval uses.
            for node_id in list(nodes):
                if node_id != CORE_ID:
                    candidate_edges.append(self._edge(
                        node_id, CORE_ID, BrainRelation.KNOWN_BY,
                        provenance=f"derived from {nodes[node_id].source_store}",
                    ))

            edges = {
                edge.id: edge for edge in candidate_edges
                if edge.source_id in nodes and edge.target_id in nodes
            }
            # A dedicated WAL writer means readers on the main Brain
            # connection keep seeing the last committed projection until this
            # complete replacement commits atomically. They never observe the
            # temporary delete/reinsert gap.
            async with aiosqlite.connect(self.database.path) as connection:
                await connection.execute("PRAGMA journal_mode=WAL")
                await connection.execute("BEGIN IMMEDIATE")
                await connection.execute("DELETE FROM brain_relationships WHERE origin = 'projection'")
                await connection.execute("DELETE FROM brain_nodes WHERE origin = 'projection'")
                await connection.executemany(
                    """INSERT INTO brain_nodes(entity_id, entity_type, native_id, label, status,
                       source_store, node_json, updated_at, origin)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'projection')""",
                    [
                        (node.id, node.kind, node.native_id, node.label, node.status,
                         node.source_store, node.model_dump_json(),
                         (node.updated_at or _now()).isoformat())
                        for node in nodes.values()
                    ],
                )
                await connection.executemany(
                    """INSERT INTO brain_relationships(id, source_id, target_id, relation, confidence,
                       verified, origin, provenance, edge_json, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET confidence=excluded.confidence,
                       verified=excluded.verified, provenance=excluded.provenance,
                       edge_json=excluded.edge_json""",
                    [
                        (edge.id, edge.source_id, edge.target_id, edge.relation.value, edge.confidence,
                         int(edge.verified), edge.origin, edge.provenance, edge.model_dump_json(),
                         edge.created_at.isoformat())
                        for edge in edges.values()
                    ],
                )
                await connection.commit()
            self.refreshed_at = _now()
            self._last_refresh_monotonic = time.monotonic()
            return {"nodes": len(nodes), "edges": len(edges)}

    async def connect(self, request: ConnectRequest) -> BrainEdge:
        await self.ensure_fresh()
        available = await self._existing_node_ids({request.source_id, request.target_id})
        if len(available) < 2 and self._refresh_task is not None and not self._refresh_task.done():
            await asyncio.shield(self._refresh_task)
            available = await self._existing_node_ids({request.source_id, request.target_id})
        missing = sorted({request.source_id, request.target_id} - available)
        if missing:
            raise KeyError(", ".join(missing))
        edge = BrainEdge(
            id=_edge_id(request.source_id, request.target_id, request.relation, "explicit"),
            source_id=request.source_id,
            target_id=request.target_id,
            relation=request.relation,
            confidence=request.confidence,
            verified=request.verified,
            origin="explicit",
            provenance=request.provenance,
            metadata=request.metadata,
        )
        await self._save_edge(edge, commit=True)
        return edge

    async def remove_explicit(self, edge_id: str) -> bool:
        connection = self.database.require_connection()
        cursor = await connection.execute(
            "DELETE FROM brain_relationships WHERE id = ? AND origin = 'explicit'", (edge_id,)
        )
        await connection.commit()
        return cursor.rowcount > 0

    async def graph(self, root_id: str | None = None, *, depth: int = 2,
                    limit: int = 300, include_core_edges: bool = True) -> BrainGraph:
        await self.ensure_fresh()
        depth = min(max(depth, 0), 4)
        limit = min(max(limit, 1), 2_000)
        nodes = await self._load_nodes()
        if root_id and root_id not in nodes:
            raise KeyError(root_id)
        edges = await self._load_edges(include_core_edges=include_core_edges)

        if root_id is None:
            selected_ids = set(list(nodes)[:limit])
        else:
            adjacency: dict[str, list[BrainEdge]] = {}
            for edge in edges:
                adjacency.setdefault(edge.source_id, []).append(edge)
                adjacency.setdefault(edge.target_id, []).append(edge)
            selected_ids = {root_id}
            queue = deque([(root_id, 0)])
            while queue and len(selected_ids) < limit:
                current, current_depth = queue.popleft()
                if current_depth >= depth:
                    continue
                for edge in adjacency.get(current, []):
                    other = edge.target_id if edge.source_id == current else edge.source_id
                    if other not in selected_ids:
                        selected_ids.add(other)
                        queue.append((other, current_depth + 1))
                        if len(selected_ids) >= limit:
                            break

        selected_edges = [
            edge for edge in edges
            if edge.source_id in selected_ids and edge.target_id in selected_ids
        ]
        return BrainGraph(
            root_id=root_id,
            depth=depth,
            nodes=[nodes[node_id] for node_id in selected_ids if node_id in nodes],
            edges=selected_edges,
            truncated=len(selected_ids) >= limit and len(nodes) > len(selected_ids),
            refreshed_at=self.refreshed_at,
        )

    async def linked_context(self, entity_id: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """Compact, specific neighbors for the cognitive resolver.

        Generic KNOWN_BY/Core edges are deliberately excluded: they make the
        graph complete, but do not help a planner understand a task.
        """
        await self.ensure_fresh()
        connection = self.database.require_connection()
        cursor = await connection.execute(
            """SELECT edge_json FROM brain_relationships
               WHERE (source_id = ? OR target_id = ?) AND relation != ?
               ORDER BY verified DESC, confidence DESC, created_at DESC LIMIT ?""",
            (entity_id, entity_id, BrainRelation.KNOWN_BY.value, min(max(limit * 3, 8), 90)),
        )
        edges = [BrainEdge.model_validate_json(row["edge_json"]) for row in await cursor.fetchall()]
        if not edges:
            return []
        other_ids = {
            edge.target_id if edge.source_id == entity_id else edge.source_id
            for edge in edges
        }
        node_map = await self._load_nodes(other_ids)
        context: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for edge in edges:
            other_id = edge.target_id if edge.source_id == entity_id else edge.source_id
            other = node_map.get(other_id)
            key = (other_id, edge.relation.value)
            if other is None or key in seen:
                continue
            seen.add(key)
            context.append({
                "id": other.id,
                "kind": other.kind,
                "label": other.label,
                "relation": edge.relation.value,
                "verified": edge.verified,
            })
        return context[:limit]

    async def summary(self) -> dict[str, Any]:
        await self.ensure_fresh()
        connection = self.database.require_connection()
        node_count = int((await (await connection.execute("SELECT COUNT(*) AS total FROM brain_nodes")).fetchone())["total"])
        edge_count = int((await (await connection.execute("SELECT COUNT(*) AS total FROM brain_relationships")).fetchone())["total"])
        specific_count = int((await (await connection.execute(
            "SELECT COUNT(*) AS total FROM brain_relationships WHERE relation != ?", (BrainRelation.KNOWN_BY.value,)
        )).fetchone())["total"])
        node_rows = await (await connection.execute(
            "SELECT entity_type, COUNT(*) AS total FROM brain_nodes GROUP BY entity_type"
        )).fetchall()
        relation_rows = await (await connection.execute(
            "SELECT relation, COUNT(*) AS total FROM brain_relationships WHERE relation != ? GROUP BY relation",
            (BrainRelation.KNOWN_BY.value,),
        )).fetchall()
        explicit = int((await (await connection.execute(
            "SELECT COUNT(*) AS total FROM brain_relationships WHERE origin = 'explicit'"
        )).fetchone())["total"])
        return {
            "nodes": node_count,
            "relationships": edge_count,
            "specific_relationships": specific_count,
            "node_types": {row["entity_type"]: int(row["total"]) for row in node_rows},
            "relationship_types": {row["relation"]: int(row["total"]) for row in relation_rows},
            "explicit_relationships": explicit,
            "refreshed_at": self.refreshed_at.isoformat(),
        }

    async def _read_json_rows(self, table: str, column: str) -> list[dict[str, Any]]:
        connection = self.database.require_connection()
        cursor = await connection.execute(f"SELECT {column} AS payload FROM {table}")
        rows = await cursor.fetchall()
        values: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                values.append(payload)
        return values

    def _project_payload(self, table: str, data: dict[str, Any], nodes: dict[str, BrainNode],
                         edges: list[BrainEdge]) -> None:
        handlers = {
            "tasks": self._project_task,
            "memories": self._project_memory,
            "crm_records": self._project_crm,
            "artifacts": self._project_artifact,
            "commitments": self._project_commitment,
            "goals": self._project_goal,
            "milestones": self._project_milestone,
            "habits": self._project_habit,
            "automations": self._project_automation,
            "automation_runs": self._project_automation_run,
            "experiences": self._project_experience,
            "adaptive_strategies": self._project_strategy,
            "nodes": self._project_device,
        }
        handlers[table](data, nodes, edges)

    def _add_node(self, nodes: dict[str, BrainNode], *, kind: str, native_id: Any,
                  label: Any, source: str, summary: Any = "", status: Any = None,
                  updated_at: Any = None, metadata: dict[str, Any] | None = None) -> str | None:
        if not native_id:
            return None
        native = str(native_id)
        node_id = _canonical(kind, native)
        parsed_updated = None
        if isinstance(updated_at, str):
            try:
                parsed_updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                parsed_updated = None
        nodes[node_id] = BrainNode(
            id=node_id, native_id=native, kind=kind,
            label=_text(label or native, 240), summary=_text(summary, 500),
            status=_text(status, 80) or None, source_store=source,
            updated_at=parsed_updated, metadata=metadata or {},
        )
        return node_id

    def _edge(self, source_id: str, target_id: str, relation: BrainRelation, *,
              provenance: str, verified: bool = False, confidence: float = 1.0,
              metadata: dict[str, Any] | None = None) -> BrainEdge:
        return BrainEdge(
            id=_edge_id(source_id, target_id, relation, "projection"),
            source_id=source_id, target_id=target_id, relation=relation,
            confidence=confidence, verified=verified, origin="projection",
            provenance=provenance, metadata=metadata or {},
        )

    def _link(self, edges: list[BrainEdge], source: str | None, target: str | None,
              relation: BrainRelation, provenance: str, *, verified: bool = False) -> None:
        if source and target and source != target:
            edges.append(self._edge(source, target, relation, provenance=provenance, verified=verified))

    def _project_task(self, data, nodes, edges):
        task_id = self._add_node(nodes, kind="task", native_id=data.get("id"),
            label=data.get("goal") or data.get("user_request"), source="tasks",
            summary=data.get("user_request"), status=data.get("status"),
            updated_at=data.get("completed_at") or data.get("started_at") or data.get("created_at"),
            metadata={"domain": data.get("domain"), "source": data.get("source")})
        parent = data.get("parent_task_id")
        if parent:
            self._link(edges, task_id, _canonical("task", parent), BrainRelation.BELONGS_TO, "task.parent_task_id")
        routing = data.get("routing") or {}
        model = data.get("assigned_model") or routing.get("model")
        if model:
            self._add_node(nodes, kind="model", native_id=model, label=model, source="tasks")
            self._link(edges, task_id, _canonical("model", model), BrainRelation.USES, "task routing")
        for bucket in ("result", "verification"):
            payload = data.get(bucket) or {}
            for index, item in enumerate(payload.get("evidence") or []):
                evidence_id = f"{data.get('id')}:{bucket}:{index}"
                evidence_node = self._add_node(nodes, kind="evidence", native_id=evidence_id,
                    label=item, source="tasks", summary=item,
                    status="verified" if bucket == "verification" and payload.get("passed") else "recorded")
                self._link(edges, task_id, evidence_node, BrainRelation.SUPPORTED_BY,
                    f"task.{bucket}.evidence", verified=bucket == "verification" and bool(payload.get("passed")))

    def _project_memory(self, data, nodes, edges):
        if data.get("sensitivity") == "highly_sensitive":
            return
        memory_id = self._add_node(nodes, kind="memory", native_id=data.get("id"),
            label=data.get("title"), summary=data.get("summary"), source="memories",
            status=data.get("verification_state"), updated_at=data.get("updated_at"),
            metadata={"memory_type": data.get("type"), "confidence": data.get("confidence")})
        for field, kind, relation in (
            ("task_id", "task", BrainRelation.BELONGS_TO),
            ("project_id", "project", BrainRelation.BELONGS_TO),
            ("client_id", "client", BrainRelation.BELONGS_TO),
            ("agent_id", "agent", BrainRelation.CREATED_BY),
            ("supersedes", "memory", BrainRelation.SUPERSEDES),
        ):
            if data.get(field):
                self._link(edges, memory_id, _canonical(kind, data[field]), relation, f"memory.{field}")

    async def _project_memory_relationships(self, nodes: dict[str, BrainNode], edges: list[BrainEdge]) -> None:
        """Bring the real memory-to-memory RELATED_TO links (see
        app/memory/auto_linker.py + MemoryManager._auto_link) into the
        unified Brain Graph, so the frontend's single native graph view
        shows the cross-linked memory web alongside everything else -
        not a second, disconnected graph. Reads memory_relationships
        directly rather than through MemoryStore because the projection
        runs from a raw connection, matching every other _project_*
        method's pattern in this file."""
        connection = self.database.require_connection()
        cursor = await connection.execute(
            "SELECT source_id, target_id, relation, confidence FROM memory_relationships"
        )
        for row in await cursor.fetchall():
            source_id = _canonical("memory", row["source_id"])
            target_id = _canonical("memory", row["target_id"])
            if source_id not in nodes or target_id not in nodes:
                # Either side may be a highly-sensitive memory, which
                # _project_memory deliberately never adds as a node -
                # its relationships must not leak it back in as an edge.
                continue
            try:
                relation = BrainRelation(row["relation"])
            except ValueError:
                relation = BrainRelation.RELATED_TO
            edges.append(self._edge(
                source_id, target_id, relation,
                provenance="memory_relationships (auto-linked)",
                confidence=float(row["confidence"]),
            ))

    def _project_crm(self, data, nodes, edges):
        kind = str(data.get("record_type") or "crm")
        crm_id = self._add_node(nodes, kind=kind, native_id=data.get("id"), label=data.get("name"),
            summary=data.get("summary") or data.get("qualification_reason"), source="crm_records",
            status=data.get("status") or data.get("state") or data.get("stage"), updated_at=data.get("updated_at"))
        if data.get("client_id"):
            self._link(edges, crm_id, _canonical("client", data["client_id"]), BrainRelation.BELONGS_TO, f"crm.{kind}.client_id")
        if data.get("company_id"):
            self._link(edges, crm_id, _canonical("client", data["company_id"]), BrainRelation.BELONGS_TO, f"crm.{kind}.company_id")
        if data.get("subject_id"):
            target = self._canonical_for_native(data["subject_id"])
            self._link(edges, crm_id, target, BrainRelation.RELATED_TO, f"crm.{kind}.subject_id")

    def _project_artifact(self, data, nodes, edges):
        spec = data.get("spec") or {}
        artifact_id = self._add_node(nodes, kind="artifact", native_id=data.get("id"),
            label=spec.get("title") or data.get("id"), summary=spec.get("purpose"), source="artifacts",
            status=data.get("status"), updated_at=data.get("updated_at"),
            metadata={"artifact_type": spec.get("type"), "version": data.get("version"), "verified": data.get("verified")})
        if spec.get("task_id"):
            self._link(edges, artifact_id, _canonical("task", spec["task_id"]), BrainRelation.CREATED_BY,
                "artifact.spec.task_id", verified=bool(data.get("verified")))

    def _project_commitment(self, data, nodes, edges):
        commitment_id = self._add_node(nodes, kind="commitment", native_id=data.get("id"),
            label=data.get("description"), summary=f"To: {data.get('recipient') or 'self'}", source="commitments",
            status=data.get("status"), updated_at=data.get("updated_at"), metadata={"deadline": data.get("deadline")})
        for reference in data.get("evidence") or []:
            target = self._canonical_for_native(reference)
            self._link(edges, commitment_id, target, BrainRelation.SUPPORTED_BY, "commitment.evidence", verified=True)

    def _project_goal(self, data, nodes, edges):
        goal_id = self._add_node(nodes, kind="goal", native_id=data.get("id"), label=data.get("title"),
            summary=data.get("description"), source="goals", status=data.get("status"),
            updated_at=data.get("updated_at"), metadata={"priority": data.get("priority"), "progress": data.get("progress")})
        for project in data.get("related_projects") or []:
            self._link(edges, goal_id, _canonical("project", project), BrainRelation.RELATED_TO, "goal.related_projects")
        for habit in data.get("related_habits") or []:
            self._link(edges, goal_id, _canonical("habit", habit), BrainRelation.RELATED_TO, "goal.related_habits")
        for blocker in data.get("blocked_by") or []:
            self._link(edges, goal_id, self._canonical_for_native(blocker), BrainRelation.BLOCKED_BY, "goal.blocked_by")

    def _project_milestone(self, data, nodes, edges):
        milestone_id = self._add_node(nodes, kind="milestone", native_id=data.get("id"), label=data.get("title"),
            summary=data.get("target"), source="milestones", status=data.get("status"), updated_at=data.get("updated_at"))
        if data.get("goal_id"):
            self._link(edges, _canonical("goal", data["goal_id"]), milestone_id, BrainRelation.HAS_MILESTONE, "milestone.goal_id")

    def _project_habit(self, data, nodes, edges):
        self._add_node(nodes, kind="habit", native_id=data.get("id"), label=data.get("name"),
            summary=data.get("description"), source="habits", status=data.get("status"), updated_at=data.get("updated_at"))

    def _project_automation(self, data, nodes, edges):
        self._add_node(nodes, kind="automation", native_id=data.get("id"), label=data.get("name"),
            summary=data.get("action"), source="automations", status=data.get("status"), updated_at=data.get("updated_at"),
            metadata={"type": data.get("type"), "next_run_at": data.get("next_run_at"), "timezone": data.get("timezone")})

    def _project_automation_run(self, data, nodes, edges):
        run_id = self._add_node(nodes, kind="automation_run", native_id=data.get("id"),
            label=f"Automation run {data.get('id')}", summary=data.get("error") or "",
            source="automation_runs", status=data.get("status"), updated_at=data.get("completed_at") or data.get("started_at"))
        if data.get("automation_id"):
            self._link(edges, _canonical("automation", data["automation_id"]), run_id, BrainRelation.HAS_RUN, "automation_run.automation_id")
        result = data.get("result") or {}
        if result.get("task_id"):
            self._link(edges, run_id, _canonical("task", result["task_id"]), BrainRelation.PRODUCED, "automation_run.result.task_id")

    def _project_experience(self, data, nodes, edges):
        experience_id = self._add_node(nodes, kind="experience", native_id=data.get("experience_id"),
            label=data.get("goal") or data.get("task_type"), summary=data.get("result_summary") or data.get("failure_reason"),
            source="experiences", status="success" if data.get("success") else "failure", updated_at=data.get("created_at"),
            metadata={"verification_score": data.get("verification_score"), "confidence": data.get("confidence")})
        if data.get("task_id"):
            self._link(edges, experience_id, _canonical("task", data["task_id"]), BrainRelation.LEARNED_FROM, "experience.task_id", verified=bool(data.get("success")))
        if data.get("strategy_used"):
            self._link(edges, experience_id, _canonical("strategy", data["strategy_used"]), BrainRelation.USES, "experience.strategy_used")
        for field, kind in (("skills_used", "skill"), ("tools_used", "tool"), ("agents_used", "agent"), ("models_used", "model")):
            for value in data.get(field) or []:
                self._add_reference_node(nodes, kind, value, field)
                self._link(edges, experience_id, _canonical(kind, value), BrainRelation.USES, f"experience.{field}")
        for lesson in data.get("lesson_refs") or []:
            self._link(edges, experience_id, self._canonical_for_native(lesson), BrainRelation.LEARNED_FROM, "experience.lesson_refs")

    def _project_strategy(self, data, nodes, edges):
        strategy_id = self._add_node(nodes, kind="strategy", native_id=data.get("strategy_id"),
            label=data.get("name"), summary="; ".join(data.get("actions") or [])[:500], source="adaptive_strategies",
            status=data.get("status"), updated_at=data.get("last_used") or data.get("created_at"), metadata={"version": data.get("version")})
        for field, kind in (("skills", "skill"), ("tools", "tool"), ("models", "model")):
            for value in data.get(field) or []:
                self._add_reference_node(nodes, kind, value, field)
                self._link(edges, strategy_id, _canonical(kind, value), BrainRelation.USES, f"strategy.{field}")

    def _project_device(self, data, nodes, edges):
        native_id = data.get("node_id") or data.get("id")
        self._add_node(nodes, kind="device", native_id=native_id,
            label=data.get("name") or native_id, summary=data.get("device_type") or "",
            source="nodes", status=data.get("status") or data.get("trust_level"), updated_at=data.get("updated_at"))

    def _project_registries(self, nodes, edges):
        if self.skill_registry is not None:
            for skill in self.skill_registry.list():
                skill_id = self._add_node(nodes, kind="skill", native_id=skill.id, label=skill.name,
                    summary=skill.description, source="skill_registry", status=skill.status.value,
                    updated_at=skill.updated_at, metadata={"version": skill.version, "success_rate": skill.success_rate})
                for tool in skill.required_tools:
                    self._add_reference_node(nodes, "tool", tool, "skill.required_tools")
                    self._link(edges, skill_id, _canonical("tool", tool), BrainRelation.USES, "skill.required_tools")
                for capability in skill.required_capabilities:
                    self._add_reference_node(nodes, "capability", capability, "skill.required_capabilities")
                    self._link(edges, skill_id, _canonical("capability", capability), BrainRelation.USES, "skill.required_capabilities")
        if self.agent_registry is not None:
            for agent in self.agent_registry.list():
                agent_id = self._add_node(nodes, kind="agent", native_id=agent.id, label=agent.name,
                    summary=agent.description, source="agent_registry", status=agent.status.value,
                    updated_at=agent.updated_at, metadata={"role": agent.role, "version": agent.version})
                for field, kind in ((agent.skills, "skill"), (agent.tools, "tool"), (agent.capabilities, "capability")):
                    for value in field:
                        self._add_reference_node(nodes, kind, value, "agent registry")
                        self._link(edges, agent_id, _canonical(kind, value), BrainRelation.USES, f"agent.{kind}s")
        if self.capability_registry is not None:
            for capability in self.capability_registry.list():
                capability_id = self._add_node(nodes, kind="capability", native_id=capability.capability_id,
                    label=capability.name, summary=capability.description, source="capability_registry",
                    status=capability.status.value, updated_at=capability.last_verified,
                    metadata={"source": capability.source.value, "reliability": capability.reliability})
                source_kind = {
                    "skill": "skill", "agent": "agent", "model": "model",
                    "built_in_tool": "tool", "mcp_tool": "tool", "integration": "integration",
                }.get(capability.source.value)
                if source_kind:
                    self._add_reference_node(nodes, source_kind, capability.source_id, "capability source")
                    self._link(edges, capability_id, _canonical(source_kind, capability.source_id), BrainRelation.IMPLEMENTS, "capability.source_id")

    def _add_reference_node(self, nodes, kind: str, value: Any, source: str) -> None:
        node_id = _canonical(kind, str(value))
        if node_id not in nodes:
            self._add_node(nodes, kind=kind, native_id=value, label=value, source=source)

    @staticmethod
    def _canonical_for_native(value: Any) -> str:
        text = str(value)
        prefixes = {
            "task_": "task", "mem_": "memory", "goal_": "goal",
            "milestone_": "milestone", "artifact_": "artifact",
            "commitment_": "commitment", "automation_": "automation",
            "run_": "automation_run", "exp_": "experience", "crm_": "crm",
        }
        for prefix, kind in prefixes.items():
            if text.startswith(prefix):
                return _canonical(kind, text)
        if ":" in text:
            return text
        return _canonical("reference", text)

    async def _save_edge(self, edge: BrainEdge, *, commit: bool) -> None:
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO brain_relationships(id, source_id, target_id, relation, confidence,
               verified, origin, provenance, edge_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET confidence=excluded.confidence,
               verified=excluded.verified, provenance=excluded.provenance,
               edge_json=excluded.edge_json""",
            (edge.id, edge.source_id, edge.target_id, edge.relation.value, edge.confidence,
             int(edge.verified), edge.origin, edge.provenance, edge.model_dump_json(),
             edge.created_at.isoformat()),
        )
        if commit:
            await connection.commit()

    async def _load_nodes(self, ids: Iterable[str] | None = None) -> dict[str, BrainNode]:
        values = list(ids or [])
        if values:
            placeholders = ",".join("?" for _ in values)
            cursor = await self.database.require_connection().execute(
                f"SELECT node_json FROM brain_nodes WHERE entity_id IN ({placeholders}) ORDER BY entity_id", values,
            )
        else:
            cursor = await self.database.require_connection().execute("SELECT node_json FROM brain_nodes ORDER BY entity_id")
        return {
            node.id: node
            for node in (BrainNode.model_validate_json(row["node_json"]) for row in await cursor.fetchall())
        }

    async def _load_edges(self, *, include_core_edges: bool) -> list[BrainEdge]:
        query = "SELECT edge_json FROM brain_relationships"
        parameters: tuple[Any, ...] = ()
        if not include_core_edges:
            query += " WHERE relation != ?"
            parameters = (BrainRelation.KNOWN_BY.value,)
        query += " ORDER BY created_at, id"
        cursor = await self.database.require_connection().execute(query, parameters)
        return [BrainEdge.model_validate_json(row["edge_json"]) for row in await cursor.fetchall()]

    async def _existing_node_ids(self, ids: Iterable[str]) -> set[str]:
        values = list(ids)
        if not values:
            return set()
        placeholders = ",".join("?" for _ in values)
        cursor = await self.database.require_connection().execute(
            f"SELECT entity_id FROM brain_nodes WHERE entity_id IN ({placeholders})", values
        )
        return {row["entity_id"] for row in await cursor.fetchall()}
