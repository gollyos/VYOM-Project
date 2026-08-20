from __future__ import annotations

from dataclasses import dataclass, field

from app.memory.schemas import MemoryQuery, MemoryType

from .namespaces import CognitiveNamespace, NamespacedHit, infer_namespace

# Phase 15 core order: before asking the user or searching externally,
# exhaust internal knowledge in this exact order.
RESOLUTION_ORDER = ("memory", "experience", "knowledge", "skill", "tool", "external_research")


@dataclass
class ResolutionResult:
    query: str
    namespace: CognitiveNamespace
    resolved: bool
    source: str | None = None          # first stage that answered
    hits: list[dict] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)


class ResolutionChain:
    """One deterministic resolver over the EXISTING stores:
    1. memory — namespaced structured memory (preferences/facts)
    2. experience — Phase 14 operational outcomes
    3. knowledge — semantic/procedural/lesson memory
    4. skill — existing Skill Registry
    5. tool — existing Tool Registry / capability backends
    6. external_research — only now (marked, never auto-run here)
    """

    def __init__(self, memory=None, experience_store=None, skill_registry=None,
                 tool_registry=None, capability_registry=None, brain_graph=None):
        self.memory = memory
        self.experience_store = experience_store
        self.skill_registry = skill_registry
        self.tool_registry = tool_registry
        self.capability_registry = capability_registry
        self.brain_graph = brain_graph

    async def resolve(self, query: str, *, namespace: CognitiveNamespace | None = None,
                      domain: str = "", text: str = "") -> ResolutionResult:
        namespace = namespace or infer_namespace(domain=domain, text=text or query)
        result = ResolutionResult(query=query, namespace=namespace, resolved=False)

        # 1) Memory (namespaced facts/preferences)
        if self.memory is not None:
            hits = await self.memory.search(MemoryQuery(text=query, limit=3))
            from .namespaces import NamespaceMemoryRouter

            namespaced = [h for h in hits
                          if NamespaceMemoryRouter.tag_for(namespace) in (h.memory.tags or [])]
            # REMEMBER BROADLY, RETRIEVE NARROWLY. Identity/business facts
            # (name, website, client) are rarely namespace-tagged at write
            # time, so `namespaced` is almost always empty for them and
            # this used to fall back to ALL raw similarity hits regardless
            # of relevance - which is how "Page scroll down karo" and "Is
            # page pe kya hai?" (namespace: system) ended up carrying the
            # user's name and business identity as retrieval context, and
            # how it then leaked into an unrelated calculator response.
            # The fallback pool is still broad for genuinely non-identity
            # namespaces, but identity-type memory only surfaces there
            # when the query is ITSELF about people/personal/agency.
            if namespaced:
                pool = namespaced
            elif namespace in (CognitiveNamespace.PEOPLE, CognitiveNamespace.PERSONAL,
                               CognitiveNamespace.AGENCY):
                pool = hits
            else:
                pool = [h for h in hits if h.memory.type not in (MemoryType.PERSON, MemoryType.CLIENT)]
            for hit in pool[:2]:
                item = {"source": "memory", "id": hit.memory.id, "title": hit.memory.title,
                        "summary": hit.memory.summary, "confidence": hit.memory.confidence}
                if self.brain_graph is not None:
                    item["connections"] = await self.brain_graph.linked_context(
                        f"memory:{hit.memory.id}", limit=6,
                    )
                result.hits.append(item)
            if result.hits:
                result.resolved, result.source = True, "memory"
                result.trace.append(f"memory: {len(result.hits)} hit(s) in namespace '{namespace.value}'")
                return result
        result.trace.append("memory: no hits")

        # 2) Experience (Phase 14 outcomes)
        if self.experience_store is not None:
            experiences = await self.experience_store.retrieve_similar(query, domain=namespace.value if namespace.value in ("coding", "research", "finance") else None)
            if experiences:
                top, score = experiences[0]
                result.resolved, result.source = True, "experience"
                result.hits.append({"source": "experience", "goal": top.goal,
                                    "success": top.success, "verification": top.verification_score,
                                    "similarity": score})
                result.trace.append(f"experience: similar prior outcome (score {score})")
                return result
        result.trace.append("experience: no similar outcomes")

        # 3) Knowledge (semantic/procedural/lesson memory, any namespace)
        if self.memory is not None:
            knowledge = await self.memory.search(MemoryQuery(
                text=query, limit=3,
                types={MemoryType.SEMANTIC, MemoryType.PROCEDURAL, MemoryType.LESSON},
            ))
            if knowledge:
                result.resolved, result.source = True, "knowledge"
                result.hits.extend({"source": "knowledge", "title": hit.memory.title,
                                    "summary": hit.memory.summary} for hit in knowledge[:2])
                result.trace.append(f"knowledge: {len(knowledge)} hit(s)")
                return result
        result.trace.append("knowledge: no hits")

        # 4) Existing skills
        if self.skill_registry is not None:
            for skill in self.skill_registry.list():
                tokens = {t for t in f"{skill.id} {skill.name} {skill.description}".lower().split() if len(t) > 3}
                query_tokens = {t for t in query.lower().split() if len(t) > 3}
                if tokens & query_tokens:
                    result.resolved, result.source = True, "skill"
                    result.hits.append({"source": "skill", "id": skill.id, "name": skill.name})
                    result.trace.append(f"skill: {skill.id} matches")
                    return result
        result.trace.append("skill: no match")

        # 5) Existing tools / capability backends
        if self.tool_registry is not None:
            for tool in self.tool_registry.list():
                tool_tags = [str(tag) for tag in getattr(tool.metadata, "tags", []) or []]
                if tool.metadata.name.lower() in query.lower() or any(
                    tag.lower() in query.lower() for tag in tool_tags
                ):
                    result.resolved, result.source = True, "tool"
                    result.hits.append({"source": "tool", "name": tool.metadata.name})
                    result.trace.append(f"tool: {tool.metadata.name} matches")
                    return result
        if self.capability_registry is not None:
            found = self.capability_registry.search(query, limit=2)
            if found:
                result.resolved, result.source = True, "tool"
                result.hits.extend({"source": "capability", "id": record.capability_id} for record in found)
                result.trace.append(f"capability: {found[0].capability_id}")
                return result
        result.trace.append("tool: no match")

        # 6) External research — required next step, never auto-run here
        result.source = "external_research"
        result.trace.append("external_research: required next step (user consent path)")
        return result
