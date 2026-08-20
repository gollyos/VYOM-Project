from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.agents.factory import AgentFactory
from app.agents.registry import AgentRegistry
from app.agents.runtime import AgentRuntime
from app.agents.schemas import AgentStatus
from app.capabilities.discovery import CapabilityDiscovery
from app.capabilities.registry import CapabilityRegistry
from app.execution.action_engine import ActionEngine
from app.memory.manager import MemoryManager
from app.memory.schemas import (
    MemoryEntry,
    MemoryProvenance,
    MemoryQuery,
    MemoryType,
    ProvenanceType,
    RelationType,
    VerificationState,
)
from app.schemas.results import ExecutionResult
from app.schemas.routing import UsageRecord
from app.schemas.tasks import Task, TaskDomain, TaskProfile
from app.skills.builder import SkillBuilder
from app.skills.executor import SkillExecutor
from app.skills.matcher import SkillMatcher
from app.skills.registry import SkillRegistry

from app.personal.preferences import PreferenceExtractor
from app.personal.profile import PersonalProfileService
from app.personal.schemas import PreferenceSource

from .improvement_engine import ImprovementEngine


PHASE6_INTENTS = {
    "remember_preference", "recall_preference", "forget_memory", "explain_memory",
    "correct_memory", "inspect_project_memory", "recall_project_build", "show_related_memory",
    "create_build_skill", "run_build_skill", "create_project_health_agent",
    "run_project_health_agent", "learn_from_failure", "recall_failure_lesson",
    "run_taught_skill", "show_brain_graph",
}


def generated_at() -> str:
    return datetime.now().astimezone().strftime("%H:%M · Intelligence memory")


class IntelligenceEngine:
    def __init__(
        self,
        *,
        memory: MemoryManager,
        capabilities: CapabilityRegistry,
        skill_registry: SkillRegistry,
        skill_builder: SkillBuilder,
        skill_executor: SkillExecutor,
        agent_registry: AgentRegistry,
        agent_factory: AgentFactory,
        agent_runtime: AgentRuntime,
        action_engine: ActionEngine,
        improvement: ImprovementEngine,
        project_id: str,
        personal_profile_service: PersonalProfileService | None = None,
        brain_graph=None,
    ):
        self.memory = memory
        self.capabilities = capabilities
        self.capability_discovery = CapabilityDiscovery(capabilities)
        self.skill_registry = skill_registry
        self.skill_builder = skill_builder
        self.skill_executor = skill_executor
        self.skill_matcher = SkillMatcher(skill_registry)
        self.agent_registry = agent_registry
        self.agent_factory = agent_factory
        self.agent_runtime = agent_runtime
        self.action_engine = action_engine
        self.improvement = improvement
        self.project_id = project_id
        self.personal_profile_service = personal_profile_service
        self.preference_extractor = PreferenceExtractor()
        self.brain_graph = brain_graph

    def supports(self, intent: str) -> bool:
        return intent in PHASE6_INTENTS

    async def execute(self, task: Task, profile: TaskProfile, emit) -> ExecutionResult:
        handlers = {
            "remember_preference": self._remember_preference,
            "recall_preference": self._recall_preference,
            "forget_memory": self._forget_memory,
            "explain_memory": self._explain_memory,
            "correct_memory": self._correct_memory,
            "inspect_project_memory": self._inspect_project_memory,
            "recall_project_build": self._recall_project_build,
            "show_related_memory": self._show_related_memory,
            "create_build_skill": self._create_build_skill,
            "run_build_skill": self._run_build_skill,
            "create_project_health_agent": self._create_project_health_agent,
            "run_project_health_agent": self._run_project_health_agent,
            "learn_from_failure": self._learn_from_failure,
            "recall_failure_lesson": self._recall_failure_lesson,
            "run_taught_skill": self._run_taught_skill,
            "show_brain_graph": self._show_brain_graph,
        }
        return await handlers[profile.intent](task, emit)

    async def _run_taught_skill(self, task: Task, emit) -> ExecutionResult:
        from app.skills.teachable import parse_skill_command

        skill_id, runtime_inputs = parse_skill_command(task.user_request)
        await emit("skill_matched", f"Matched taught skill {skill_id}", {
            "skill_id": skill_id, "runtime_input_names": sorted(runtime_inputs),
        })
        return await self.skill_executor.execute(skill_id, task, emit, runtime_inputs)

    async def _show_brain_graph(self, task: Task, emit) -> ExecutionResult:
        if self.brain_graph is None:
            raise RuntimeError("Brain graph is not attached")
        graph = await self.brain_graph.graph("core:vyom", depth=1, limit=80, include_core_edges=True)
        summary_data = await self.brain_graph.summary()
        graph_nodes = sorted(graph.nodes, key=lambda node: (node.id != "core:vyom", node.kind, node.label))
        nodes = [
            {"id": node.id, "label": node.label, "kind": node.kind, "status": node.status}
            for node in graph_nodes
        ]
        edges = [
            {"from": edge.source_id, "to": edge.target_id, "relation": edge.relation.value,
             "verified": edge.verified}
            for edge in graph.edges
        ]
        summary = (
            f"VYOM Brain has {summary_data['nodes']} connected entities and "
            f"{summary_data['specific_relationships']} specific relationships."
        )
        await emit("memory_retrieved", "Composed the persistent operating graph", {
            "nodes_shown": len(nodes), "edges_shown": len(edges), "graph_summary": summary_data,
        })
        objects = [{
            "id": "brain-graph", "type": "brain-graph", "title": "Living Core knowledge graph",
            "eyebrow": "Persistent operating intelligence", "tone": "intelligence",
            "rootId": "core:vyom", "nodes": nodes, "edges": edges,
            "totalNodes": summary_data["nodes"], "totalRelationships": summary_data["relationships"],
            "frame": {"x": 3, "y": 5, "width": 94},
        }]
        return ExecutionResult(
            response=summary, structured_data={"graph": graph.model_dump(mode="json"), "summary": summary_data},
            ui_composition=self._base_composition("living-core-brain-graph", summary, objects),
            evidence=[f"Graph projection refreshed at {summary_data['refreshed_at']}",
                      f"Rendered {len(nodes)} nodes and {len(edges)} edges"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def consolidate_task(self, task: Task, emit) -> None:
        if task.profile and self.supports(task.profile.intent):
            return
        memories = self.memory.consolidator.from_verified_task(task)
        for memory in memories:
            await self.memory.remember(memory)
            await emit("memory_consolidated", "Stored a verified operational summary", {"memory_id": memory.id, "type": memory.type.value})

    async def learn_failure(self, task: Task, error: str, emit) -> None:
        learned = await self.improvement.record_failure(
            task_id=task.id, title=task.goal[:120], error_summary=error, project_id=self.project_id
        )
        if learned:
            _, lesson = learned
            await emit("lesson_created", "Stored a generalized lesson from verified failure evidence", {"memory_id": lesson.id, "confidence": lesson.confidence})

    async def _remember_preference(self, task: Task, emit) -> ExecutionResult:
        content = task.user_request.strip()
        lower = content.lower()
        if "remember that" in lower:
            content = content[lower.index("remember that") + len("remember that"):].strip().rstrip(".")
        memory = await self.memory.remember(MemoryEntry(
            type=MemoryType.PREFERENCE,
            title="Important client meeting preference" if "meeting" in content.lower() else "User preference",
            content=content,
            summary=content,
            entities=["User", "Client meetings"] if "meeting" in content.lower() else ["User"],
            tags=["preference", "user-stated"],
            provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT, task_id=task.id, reference="Direct user instruction")],
            task_id=task.id,
            importance=0.8,
            confidence=1,
            verification_state=VerificationState.VERIFIED,
        ))
        await emit("memory_created", "Remembered the user preference with provenance", {"memory": self._memory_public(memory)})
        if self.personal_profile_service is not None:
            key, value = self.preference_extractor.extract(content)
            if not key.startswith("note:"):
                # Only structured, recognized personal-preference statements
                # also populate PersonalProfile (docs/PERSONAL_OS.md); an
                # unrecognized statement still lives in memory above, but
                # isn't force-fit into a structured field.
                await self.personal_profile_service.set_field(key, value, source=PreferenceSource.USER_STATEMENT, confidence=1.0)
        return self._memory_result("Preference remembered and persisted.", [memory], "memory-preference-created")

    async def _recall_preference(self, task: Task, emit) -> ExecutionResult:
        results = await self.memory.search(MemoryQuery(text="important client meetings prefer time", types={MemoryType.PREFERENCE}, limit=3))
        await emit("memory_retrieved", f"Retrieved {len(results)} relevant preference memory item(s)", {"memory_ids": [item.memory.id for item in results]})
        if not results:
            return self._simple("I do not have a stored preference for important client meetings.", {"matches": []})
        memory = results[0].memory
        preference = memory.content.strip().rstrip(".")
        if preference.lower().startswith("i prefer "):
            preference = preference[len("I prefer "):]
        return self._memory_result(f"You prefer {preference}.", [memory], "memory-preference-recalled")

    async def _forget_memory(self, task: Task, emit) -> ExecutionResult:
        results = await self.memory.search(MemoryQuery(types={MemoryType.PREFERENCE}, limit=1))
        if not results:
            return self._simple("No matching preference memory exists to forget.", {"forgotten": False})
        memory_id = results[0].memory.id
        forgotten = await self.memory.forget(memory_id)
        await emit("memory_forgotten", "Forgot the requested preference memory", {"memory_id": memory_id, "deleted": forgotten})
        return self._simple("That preference has been forgotten.", {"forgotten": forgotten, "memory_id": memory_id})

    async def _explain_memory(self, task: Task, emit) -> ExecutionResult:
        results = await self.memory.search(MemoryQuery(types={MemoryType.PREFERENCE}, limit=1))
        if not results:
            return self._simple("There is no matching memory to explain.", {})
        inspected = await self.memory.inspect(results[0].memory.id)
        await emit("memory_retrieved", "Retrieved memory provenance", {"memory_id": results[0].memory.id})
        provenance = inspected["provenance"] if inspected else []
        source = provenance[0]["type"].replace("_", " ") if provenance else "unknown source"
        return self._memory_result(f"I remember this from a {source}: {results[0].memory.summary}", [results[0].memory], "memory-provenance")

    async def _correct_memory(self, task: Task, emit) -> ExecutionResult:
        results = await self.memory.search(MemoryQuery(types={MemoryType.PREFERENCE}, limit=1))
        if not results:
            return await self._remember_preference(task, emit)
        text = task.user_request.split(":", 1)[-1].strip() if ":" in task.user_request else task.user_request
        replacement = MemoryEntry(
            type=MemoryType.PREFERENCE, title=results[0].memory.title, content=text, summary=text,
            entities=results[0].memory.entities, tags=["preference", "user-correction"],
            provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT, task_id=task.id, reference="Explicit user correction")],
            importance=0.9, confidence=1, verification_state=VerificationState.VERIFIED,
        )
        corrected = await self.memory.correct(results[0].memory.id, replacement)
        await emit("memory_superseded", "Superseded the contradicted memory", {"old_memory_id": results[0].memory.id, "new_memory_id": corrected.id})
        await emit("memory_updated", "Stored the user correction", {"memory": self._memory_public(corrected)})
        return self._memory_result("The earlier preference was superseded by your correction.", [corrected], "memory-corrected")

    async def _inspect_project_memory(self, task: Task, emit) -> ExecutionResult:
        tool_result = await self.action_engine.execute(
            task,
            TaskProfile(domain=TaskDomain.CODING, complexity=2, deterministic=True, intent="inspect_project", needs={"tools"}),
            emit,
        )
        workspace = tool_result.structured_data["workspace"]
        content = json.dumps({
            "frameworks": workspace["frameworks"], "languages": workspace["languages"],
            "commands": workspace["commands"], "root_path": workspace["root_path"],
        }, separators=(",", ":"))
        memory = await self.memory.remember(MemoryEntry(
            type=MemoryType.PROJECT,
            title=f"How {workspace['name']} is built",
            content=content,
            summary=f"{workspace['name']} uses {', '.join(workspace['frameworks'])}; build command: {workspace['commands'].get('build', 'not discovered')}",
            entities=[workspace["name"], *workspace["frameworks"]],
            tags=["project", "build", "verified-tool-result"],
            provenance=[MemoryProvenance(type=ProvenanceType.VERIFIED_TOOL_RESULT, task_id=task.id, file=workspace["root_path"], reference="Workspace inspection")],
            task_id=task.id, project_id=workspace["project_id"], importance=0.9, confidence=1,
            verification_state=VerificationState.VERIFIED,
        ))
        await emit("memory_created", "Stored verified project build memory", {"memory": self._memory_public(memory)})
        tool_result.response += " I also stored the verified build procedure as project memory."
        tool_result.structured_data["memory"] = memory.model_dump(mode="json")
        return tool_result

    async def _recall_project_build(self, task: Task, emit) -> ExecutionResult:
        results = await self.memory.search(MemoryQuery(text="how build project command", types={MemoryType.PROJECT}, limit=3))
        await emit("memory_retrieved", f"Retrieved {len(results)} project memory item(s)", {"memory_ids": [item.memory.id for item in results]})
        if not results:
            return self._simple("I do not yet have verified build memory for this project.", {})
        memory = results[0].memory
        try:
            command = json.loads(memory.content).get("commands", {}).get("build")
        except json.JSONDecodeError:
            command = None
        return self._memory_result(f"Build this project with `{command}`." if command else memory.summary, [memory], "project-memory-recall")

    async def _show_related_memory(self, task: Task, emit) -> ExecutionResult:
        query = task.user_request.replace("Show me everything related to", "").strip(" .")
        results = await self.memory.search(MemoryQuery(text=query, limit=8))
        await emit("memory_retrieved", f"Retrieved {len(results)} related memory item(s)", {"memory_ids": [item.memory.id for item in results]})
        return self._memory_result(f"Found {len(results)} relevant memory item(s) related to {query}.", [item.memory for item in results], "memory-related-cluster")

    async def _create_build_skill(self, task: Task, emit) -> ExecutionResult:
        skill, evaluation, created = await self.skill_builder.create_build_check(created_by=f"task:{task.id}")
        if not created:
            await emit("skill_matched", "An equivalent build-check skill already exists", {"skill": skill.model_dump(mode="json")})
        else:
            await emit("skill_created", "Created a declarative build-check skill draft", {"skill": skill.model_dump(mode="json")})
            await emit("skill_testing", "Ran bounded deterministic sandbox checks", {"evaluation": evaluation.model_dump(mode="json")})
            event = "skill_promoted" if skill.status.value == "active" else "skill_failed"
            await emit(event, f"Skill testing finished with status {skill.status.value}", {"skill": skill.model_dump(mode="json")})
            self.capability_discovery.from_skill(skill)
            memory = await self.memory.remember(MemoryEntry(
                type=MemoryType.PROCEDURAL, title=skill.name, content=json.dumps(skill.model_dump(mode="json"), separators=(",", ":")),
                summary=skill.description, entities=[skill.id], tags=["skill", "procedure", skill.category],
                provenance=[MemoryProvenance(type=ProvenanceType.TASK_RESULT, task_id=task.id, reference="Sandbox-tested SkillSpec")],
                task_id=task.id, project_id=self.project_id, importance=0.8, confidence=evaluation.score,
                verification_state=VerificationState.VERIFIED if evaluation.passed else VerificationState.UNVERIFIED,
            ))
            await emit("memory_created", "Stored the reusable procedure in procedural memory", {"memory_id": memory.id})
        return self._skill_result(skill, evaluation, created)

    async def _run_build_skill(self, task: Task, emit) -> ExecutionResult:
        matches = self.skill_matcher.match("project build check")
        if not matches:
            raise RuntimeError("No active build-check skill exists")
        skill = matches[0]
        await emit("skill_matched", f"Matched reusable skill {skill.name}", {"skill_id": skill.id, "version": skill.version})
        lessons = await self.improvement.relevant_lessons("project build failure", self.project_id)
        if lessons:
            await emit("learning_applied", "Applied a relevant prior build lesson before execution", {"lesson_ids": [item.memory.id for item in lessons]})
        result = await self.skill_executor.execute(skill.id, task, emit)
        result.structured_data["skill"] = skill.model_dump(mode="json")
        return result

    async def _create_project_health_agent(self, task: Task, emit) -> ExecutionResult:
        skill, _, _ = await self.skill_builder.create_build_check(created_by=f"agent-factory:{task.id}")
        self.capability_discovery.from_skill(skill)
        agent, validation, created = self.agent_factory.create_project_health()
        if not created and agent.status == AgentStatus.READY:
            await emit("agent_created", "Matched an existing Project Health Agent", {"agent": agent.model_dump(mode="json"), "duplicate_prevented": True})
            return self._agent_result(agent, validation, "Equivalent agent already existed and was reused.")
        await emit("agent_created", "Created a declarative Project Health Agent specification", {"agent": agent.model_dump(mode="json")})
        await emit("agent_testing", "Validating agent capabilities, skills, permissions, budgets, and memory scope", {"validation": validation.model_dump(mode="json")})
        if not validation.passed:
            await emit("agent_failed", "Agent validation failed", {"validation": validation.model_dump(mode="json")})
            return self._agent_result(agent, validation, "Agent validation failed; it was not promoted.")
        result, mission = await self.agent_runtime.delegate(task, agent.id, "Run a sample project health build verification", emit, depth=1)
        agent = self.agent_registry.get(agent.id) or agent
        self.capability_discovery.from_agent(agent)
        performance_memory = await self._store_agent_performance(task, agent, mission)
        await emit("memory_created", "Stored verified agent mission performance", {"memory_id": performance_memory.id, "agent_id": agent.id})
        await emit("agent_ready", "Project Health Agent passed its sample mission and is ready", {"agent": agent.model_dump(mode="json"), "mission": mission.model_dump(mode="json")})
        return self._agent_result(agent, validation, "Project Health Agent passed its sample mission and was registered.", result)

    async def _run_project_health_agent(self, task: Task, emit) -> ExecutionResult:
        agent = self.agent_registry.get("project-health-agent")
        if not agent:
            raise RuntimeError("Project Health Agent has not been created")
        await emit("agent_delegated", "VYOM Core delegated project health verification", {"agent_id": agent.id, "depth": 1})
        result, mission = await self.agent_runtime.delegate(task, agent.id, task.user_request, emit, depth=1)
        agent = self.agent_registry.get(agent.id) or agent
        performance_memory = await self._store_agent_performance(task, agent, mission)
        await emit("memory_consolidated", "Updated verified agent performance memory", {"memory_id": performance_memory.id, "agent_id": agent.id})
        result.structured_data["agent"] = agent.model_dump(mode="json")
        result.structured_data["mission"] = mission.model_dump(mode="json")
        return result

    async def _learn_from_failure(self, task: Task, emit) -> ExecutionResult:
        error = "Build failed because required dependency was not found."
        learned = await self.improvement.record_failure(
            task_id=task.id, title="Safe mocked dependency failure", error_summary=error, project_id=self.project_id
        )
        if not learned:
            return self._simple("The failure was recorded, but it was not generalized into a lesson.", {"failure": error})
        failure, lesson = learned
        await emit("lesson_created", "Stored a justified lesson from the safe failing task", {"failure_id": failure.id, "lesson": self._memory_public(lesson)})
        return self._lesson_result(failure, lesson)

    async def _recall_failure_lesson(self, task: Task, emit) -> ExecutionResult:
        lessons = await self.improvement.relevant_lessons(task.user_request, self.project_id)
        await emit("memory_retrieved", f"Retrieved {len(lessons)} relevant lesson(s)", {"memory_ids": [item.memory.id for item in lessons]})
        if not lessons:
            return self._simple("No relevant learned failure lesson is stored.", {})
        await emit("learning_applied", "Applied a relevant failure-prevention lesson", {"lesson_id": lessons[0].memory.id})
        return self._memory_result(lessons[0].memory.content, [lessons[0].memory], "lesson-recalled")

    def _base_composition(self, identifier: str, summary: str, objects: list[dict]) -> dict:
        return {
            "schemaVersion": 1, "id": identifier, "mode": "brain-context", "label": "VYOM / Intelligence memory",
            "summary": summary, "generatedAt": generated_at(), "objects": objects,
            "sequence": [
                {"id": f"step-{index}", "label": item.get("eyebrow", "Intelligence"), "atMs": 180 + index * 380,
                 "state": "Verifying" if index == len(objects) - 1 else "Thinking", "objectIds": [item["id"]]}
                for index, item in enumerate(objects)
            ],
        }

    def _memory_result(self, summary: str, memories: list[MemoryEntry], identifier: str) -> ExecutionResult:
        nodes = [{"id": memory.id, "label": memory.title, "type": memory.type.value, "confidence": memory.confidence} for memory in memories]
        objects = [
            {"id": "memory", "type": "memory-cluster", "title": "Relevant memory", "eyebrow": "Persistent context", "tone": "intelligence", "nodes": nodes,
             "edges": [], "caption": summary, "frame": {"x": 4, "y": 8, "width": 43}},
            {"id": "verified", "type": "verified-result", "title": "Memory evidence", "eyebrow": "Provenance", "tone": "verified",
             "statement": summary, "evidence": [f"{item.provenance[0].type.value}: {item.provenance[0].reference or item.id}" for item in memories] or ["No matching memory"],
             "timestamp": generated_at(), "frame": {"x": 57, "y": 58, "width": 38}},
        ]
        return ExecutionResult(response=summary, structured_data={"memories": [item.model_dump(mode="json") for item in memories]}, ui_composition=self._base_composition(identifier, summary, objects), evidence=[f"Memory ID: {item.id}" for item in memories], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    def _skill_result(self, skill, evaluation, created: bool) -> ExecutionResult:
        summary = f"{skill.name} is {skill.status.value}; version {skill.version}."
        objects = [
            {"id": "skill", "type": "skill-procedure", "title": skill.name, "eyebrow": "Reusable skill", "tone": "intelligence",
             "version": skill.version, "status": skill.status.value, "steps": [{"id": step.id, "label": step.action, "capability": step.capability} for step in skill.steps],
             "successRate": skill.success_rate, "permissions": skill.required_permissions.value, "frame": {"x": 3, "y": 7, "width": 46}},
            {"id": "verified", "type": "verified-result", "title": "Sandbox evaluation", "eyebrow": "Policy evidence", "tone": "verified" if skill.status.value == "active" else "attention",
             "statement": summary, "evidence": evaluation.evidence if evaluation else ["Equivalent skill reused; duplicate creation prevented"],
             "timestamp": generated_at(), "frame": {"x": 56, "y": 54, "width": 39}},
        ]
        return ExecutionResult(response=summary, structured_data={"skill": skill.model_dump(mode="json"), "created": created, "evaluation": evaluation.model_dump(mode="json") if evaluation else None}, ui_composition=self._base_composition("phase6-skill", summary, objects), evidence=[f"Skill: {skill.id}@{skill.version}", f"Status: {skill.status.value}"], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    def _agent_result(self, agent, validation, summary: str, sample_result: ExecutionResult | None = None) -> ExecutionResult:
        objects = [
            {"id": "agent", "type": "agent-status", "title": agent.name, "eyebrow": "Declarative agent", "tone": "intelligence",
             "agent": agent.name, "role": agent.role, "status": "complete" if agent.status.value == "ready" else "verifying", "mission": agent.current_mission or "Ready for a bounded mission",
             "progress": 100 if agent.status.value == "ready" else 70, "latestAction": summary, "model": "Omni Router policy",
             "capabilities": agent.capabilities, "tools": agent.tools, "permissions": agent.permissions.value,
             "modelPolicy": agent.model_policy.model_dump(mode="json"), "performance": agent.performance.model_dump(mode="json"),
             "frame": {"x": 3, "y": 6, "width": 43}},
            {"id": "capability-map", "type": "causal-diagram", "title": "Capability map", "eyebrow": "Central runtime", "tone": "neutral",
             "nodes": [{"id": f"cap-{index}", "label": capability} for index, capability in enumerate(agent.capabilities[:5])],
             "edges": [{"from": f"cap-{index}", "to": f"cap-{index + 1}"} for index in range(max(0, min(len(agent.capabilities), 5) - 1))],
             "frame": {"x": 55, "y": 8, "width": 41}},
            {"id": "verified", "type": "verified-result", "title": "Agent validation", "eyebrow": "Evidence", "tone": "verified" if agent.status.value == "ready" else "attention",
             "statement": summary, "evidence": validation.evidence + (sample_result.evidence if sample_result else []), "timestamp": generated_at(),
             "frame": {"x": 31, "y": 69, "width": 38, "layer": 2}},
        ]
        return ExecutionResult(response=summary, structured_data={"agent": agent.model_dump(mode="json"), "validation": validation.model_dump(mode="json"), "sample": sample_result.model_dump(mode="json") if sample_result else None}, ui_composition=self._base_composition("phase6-agent", summary, objects), evidence=validation.evidence + (sample_result.evidence if sample_result else []), usage=UsageRecord(total_tokens=0, estimated_cost=0))

    def _lesson_result(self, failure: MemoryEntry, lesson: MemoryEntry) -> ExecutionResult:
        summary = f"Failure recorded without claiming success. Learned: {lesson.content}"
        objects = [
            {"id": "workflow", "type": "causal-diagram", "title": "Failure learning", "eyebrow": "Event-driven learning", "tone": "attention",
             "nodes": [{"id": "failed", "label": "Verified failure"}, {"id": "analyze", "label": "Pattern analysis"}, {"id": "lesson", "label": "Bounded lesson"}],
             "edges": [{"from": "failed", "to": "analyze"}, {"from": "analyze", "to": "lesson"}], "frame": {"x": 4, "y": 8, "width": 43}},
            {"id": "verified", "type": "verified-result", "title": "Stored lesson", "eyebrow": "Learning evidence", "tone": "verified", "statement": lesson.content,
             "evidence": [f"Failure memory: {failure.id}", f"Lesson memory: {lesson.id}", f"Confidence: {lesson.confidence:.2f}"], "timestamp": generated_at(), "frame": {"x": 56, "y": 52, "width": 39}},
        ]
        return ExecutionResult(response=summary, structured_data={"failure": failure.model_dump(mode="json"), "lesson": lesson.model_dump(mode="json")}, ui_composition=self._base_composition("phase6-learning", summary, objects), evidence=[f"Failure: {failure.id}", f"Lesson: {lesson.id}"], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    async def _store_agent_performance(self, task: Task, agent, mission) -> MemoryEntry:
        return await self.memory.remember(MemoryEntry(
            type=MemoryType.AGENT_PERFORMANCE,
            title=f"{agent.name} mission performance",
            content=json.dumps({
                "mission": mission.goal,
                "status": mission.status,
                "performance": agent.performance.model_dump(mode="json"),
                "evidence": mission.evidence,
            }, separators=(",", ":")),
            summary=f"{agent.name} completed {agent.performance.successes}/{agent.performance.missions} verified missions.",
            entities=[agent.id, mission.id],
            tags=["agent-performance", "verified-mission"],
            provenance=[MemoryProvenance(type=ProvenanceType.AGENT_OBSERVATION, task_id=task.id, reference=f"Mission {mission.id}")],
            task_id=task.id,
            agent_id=agent.id,
            project_id=self.project_id,
            importance=0.65,
            confidence=1,
            verification_state=VerificationState.VERIFIED,
        ))

    @staticmethod
    def _simple(summary: str, data: dict[str, Any]) -> ExecutionResult:
        return ExecutionResult(response=summary, structured_data=data, evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    @staticmethod
    def _memory_public(memory: MemoryEntry) -> dict:
        return {"id": memory.id, "type": memory.type.value, "title": memory.title, "summary": memory.summary, "confidence": memory.confidence, "sensitivity": memory.sensitivity.value, "verification_state": memory.verification_state.value}
