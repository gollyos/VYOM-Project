from __future__ import annotations

from pathlib import Path

import pytest

from app.adaptive import Experience, ExperienceStore
from app.artifacts.export_manager import ArtifactStore
from app.artifacts.schemas import ArtifactRecord, ArtifactSpec, ArtifactStatus, ArtifactType
from app.brain_graph import BrainGraphService, BrainRelation, ConnectRequest
from app.goals.schemas import Goal, GoalStatus, Milestone
from app.goals.store import GoalStore, MilestoneStore
from app.memory.embeddings import LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.resolution import ResolutionChain
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import (
    MemoryEntry,
    MemoryProvenance,
    MemoryType,
    ProvenanceType,
    Sensitivity,
    VerificationState,
)
from app.memory.store import MemoryStore
from app.persistence.database import Database
from app.persistence.task_store import TaskStore
from app.schemas.results import ExecutionResult, VerificationResult
from app.schemas.tasks import Task, TaskStatus


@pytest.fixture
async def database(tmp_path: Path):
    value = Database(tmp_path / "brain-graph.db")
    await value.connect()
    yield value
    await value.close()


async def _memory_manager(database: Database) -> MemoryManager:
    store = MemoryStore(database)
    return MemoryManager(store, MemoryRetriever(store, LocalHashEmbeddingProvider()))


@pytest.mark.asyncio
async def test_graph_connects_memory_task_artifact_goal_milestone_and_experience(database: Database):
    task = Task(
        id="task_graph_demo",
        goal="Build the connected VYOM Brain",
        user_request="Connect every durable branch to VYOM Brain",
        status=TaskStatus.COMPLETED,
        assigned_model="local-rules-v1",
        result=ExecutionResult(response="Graph implemented", evidence=["brain graph test evidence"]),
        verification=VerificationResult(passed=True, score=1, summary="Verified", evidence=["pytest passed"]),
    )
    await TaskStore(database).save(task)

    manager = await _memory_manager(database)
    memory = await manager.remember(MemoryEntry(
        id="mem_graph_demo",
        type=MemoryType.PROJECT,
        title="Unified Brain direction",
        content="Tasks, evidence and reusable experience stay connected.",
        summary="VYOM keeps one connected operating graph.",
        task_id=task.id,
        verification_state=VerificationState.VERIFIED,
        provenance=[MemoryProvenance(type=ProvenanceType.TASK_RESULT, task_id=task.id)],
    ))

    artifact = ArtifactRecord(
        id="artifact_graph_demo",
        spec=ArtifactSpec(
            id="artifact_spec_graph_demo",
            type=ArtifactType.MARKDOWN,
            title="Brain Graph Report",
            task_id=task.id,
        ),
        status=ArtifactStatus.VALIDATED,
        verified=True,
    )
    await ArtifactStore(database).save(artifact)

    goal = await GoalStore(database).save(Goal(
        id="goal_graph_demo", title="One persistent VYOM Brain", status=GoalStatus.ACTIVE,
    ))
    milestone = await MilestoneStore(database).save(Milestone(
        id="milestone_graph_demo", goal_id=goal.id, title="Connect durable stores", target="Traversable context",
    ))

    experience = Experience(
        experience_id="exp_graph_demo",
        task_id=task.id,
        goal=task.goal,
        success=True,
        verification_score=1,
        result_summary="Unified graph projection passed",
        tools_used=["pytest"],
    )
    await ExperienceStore(database).record(experience)

    service = BrainGraphService(database)
    counts = await service.refresh()
    assert counts["nodes"] >= 10

    context = await service.linked_context(f"memory:{memory.id}")
    assert {item["id"] for item in context} == {f"task:{task.id}"}

    task_graph = await service.graph(f"task:{task.id}", depth=1, include_core_edges=False)
    node_ids = {node.id for node in task_graph.nodes}
    assert f"memory:{memory.id}" in node_ids
    assert f"artifact:{artifact.id}" in node_ids
    assert f"experience:{experience.experience_id}" in node_ids
    assert any(node.kind == "evidence" for node in task_graph.nodes)

    goal_graph = await service.graph(f"goal:{goal.id}", depth=1, include_core_edges=False)
    assert f"milestone:{milestone.id}" in {node.id for node in goal_graph.nodes}
    assert any(edge.relation == BrainRelation.HAS_MILESTONE for edge in goal_graph.edges)


@pytest.mark.asyncio
async def test_explicit_relationship_survives_projection_refresh(database: Database):
    await GoalStore(database).save(Goal(id="goal_one", title="Primary goal"))
    await GoalStore(database).save(Goal(id="goal_two", title="Supporting goal"))
    service = BrainGraphService(database)
    await service.refresh()
    edge = await service.connect(ConnectRequest(
        source_id="goal:goal_one",
        target_id="goal:goal_two",
        relation=BrainRelation.DEPENDS_ON,
        provenance="Explicit user relationship",
        verified=True,
    ))
    await service.refresh()
    graph = await service.graph("goal:goal_one", depth=1, include_core_edges=False)
    assert any(item.id == edge.id and item.origin == "explicit" for item in graph.edges)
    assert await service.remove_explicit(edge.id)


@pytest.mark.asyncio
async def test_highly_sensitive_memory_never_enters_brain_graph(database: Database):
    manager = await _memory_manager(database)
    memory = await manager.remember(MemoryEntry(
        id="mem_private_graph",
        type=MemoryType.PERSON,
        title="Private medical context",
        content="Private user-provided context",
        summary="Highly sensitive",
        sensitivity=Sensitivity.HIGHLY_SENSITIVE,
        provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT)],
    ))
    service = BrainGraphService(database)
    await service.refresh()
    graph = await service.graph()
    assert f"memory:{memory.id}" not in {node.id for node in graph.nodes}


@pytest.mark.asyncio
async def test_missing_endpoint_is_rejected(database: Database):
    service = BrainGraphService(database)
    await service.refresh()
    with pytest.raises(KeyError):
        await service.connect(ConnectRequest(
            source_id="core:vyom",
            target_id="task:missing",
            provenance="Must fail closed",
        ))


@pytest.mark.asyncio
async def test_cognitive_resolution_receives_linked_brain_context(database: Database):
    task = Task(
        id="task_resolution_graph",
        goal="Connect cognitive retrieval",
        user_request="Connect cognitive retrieval",
    )
    await TaskStore(database).save(task)
    manager = await _memory_manager(database)
    memory = await manager.remember(MemoryEntry(
        id="mem_resolution_graph",
        type=MemoryType.PROJECT,
        title="Cognitive graph retrieval",
        content="Cognitive graph retrieval connects memory to its originating task.",
        summary="Graph context should accompany the retrieved memory.",
        task_id=task.id,
        provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT)],
    ))
    service = BrainGraphService(database)
    await service.refresh()
    chain = ResolutionChain(memory=manager, brain_graph=service)
    result = await chain.resolve("cognitive graph retrieval")
    assert result.resolved and result.source == "memory"
    assert result.hits[0]["id"] == memory.id
    assert result.hits[0]["connections"][0]["id"] == f"task:{task.id}"
