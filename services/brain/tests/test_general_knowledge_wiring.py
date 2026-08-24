"""General-knowledge questions must use the knowledge-base-first-then-research
flow (KnowledgeService.ask_or_research) in the actual task execution path.

Regression: 'what is X' / 'who is X' / 'find out about X and remember it'
previously fell through the general planner's memory_search tool to the OLD
raw memory search, which knows nothing in the world and answered 'no stored
memory', so the task failed. The memory_search tool body (TaskRuntime.
_answer_memory_query) now asks the knowledge base FIRST and, when a world
subject is unknown or stale, runs the real research pipeline (which records
the facts into the same base) instead of falling to raw memory. Internal
memory questions ('what do you remember about my client') must NOT trigger a
live research call.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.knowledge.schemas import KnowledgeFact, KnowledgeRecallResult
from app.runtime.planner import GeneralPlanner
from app.runtime.task_runtime import TaskRuntime


# -- fakes -----------------------------------------------------------------


def _make_runtime(*, knowledge_service=None, phase8_engine=None, memory_retriever=None) -> TaskRuntime:
    runtime = TaskRuntime(
        task_store=None, performance_store=None, event_bus=None,
        model_registry=None, providers=None, model_router=None,
        provider_health=None, classifier=None, planner=None,
        executor=None, verifier=None, permission_engine=None,
        usage_tracker=None, action_engine=None,
    )
    runtime.knowledge_service = knowledge_service
    runtime.phase8_engine = phase8_engine
    runtime.memory_retriever = memory_retriever
    return runtime


class _FakeResearchTask:
    def __init__(self):
        self.runs: list[tuple[str, object]] = []

    async def run(self, subject, *, depth=None, **kwargs):
        from app.research.schemas import ResearchDepth

        self.runs.append((subject, depth))
        assert depth == ResearchDepth.STANDARD
        return SimpleNamespace(sources=["fake"], claims=["c"])


class _FakePhase8:
    def __init__(self, research_task):
        self.research_task = research_task


class _FakeMemoryRetriever:
    def __init__(self):
        self.searched: list[str] = []

    async def search(self, query, limit=8):
        # The runtime passes a MemoryQuery object; record its text.
        self.searched.append(getattr(query, "text", query))
        return []


class _FakeKnowledgeService:
    """Mirrors KnowledgeService: recall() returns known facts; ask_or_research()
    recalls first and, when unknown/stale, runs the supplied research_fn then
    re-recalls (facts now recorded)."""

    def __init__(self, facts=None):
        self.facts = facts if facts is not None else []
        self.recall_calls = 0
        self.ask_or_research_calls = 0
        self.research_fn_invocations = 0

    async def recall(self, subject, *, limit=20):
        self.recall_calls += 1
        return self._result(subject)

    async def ask_or_research(self, subject, research_fn, *, limit=20):
        self.ask_or_research_calls += 1
        result = self._result(subject)
        if result.needs_research:
            await research_fn()
            self.research_fn_invocations += 1
            # The real pipeline records facts during the run; simulate that.
            if not self.facts:
                self.facts = [KnowledgeFact(
                    subject=subject, predicate="is", value="a newly researched fact",
                    source_url="https://example.com/new",
                )]
            result = self._result(subject)
        return result

    def _result(self, subject) -> KnowledgeRecallResult:
        known = bool(self.facts)
        return KnowledgeRecallResult(
            subject=subject, facts=self.facts,
            stale=not known, needs_research=not known,
            reason="" if known else "no facts known for this subject",
        )


# -- classification ---------------------------------------------------------


def test_is_general_knowledge_query_distinguishes_world_from_memory():
    assert TaskRuntime._is_general_knowledge_query("What is Python?") is True
    assert TaskRuntime._is_general_knowledge_query("Who is Guido van Rossum?") is True
    assert TaskRuntime._is_general_knowledge_query("find out about the Great Wall and remember it") is True
    assert TaskRuntime._is_general_knowledge_query("python kya hai") is True
    # Internal memory questions must never trigger live research.
    assert TaskRuntime._is_general_knowledge_query("What do you remember about my client?") is False
    assert TaskRuntime._is_general_knowledge_query("what did I tell you last time") is False
    assert TaskRuntime._is_general_knowledge_query("recall my project notes") is False


def test_general_knowledge_questions_are_not_conversation():
    """A 'what is X' question must reach the mission path (memory_search ->
    knowledge base first), not be discarded as small talk and answered from a
    model or a raw memory search. This is what previously sent 'what is X' to
    the plain reasoning path and never to the knowledge base."""
    from app.runtime.planner import is_conversational

    assert is_conversational("What is Python?") is False
    assert is_conversational("Who is Guido van Rossum?") is False
    assert is_conversational("what is Eiffel Tower") is False
    assert is_conversational("find out about the solar system and remember it") is False
    # Genuine small talk stays conversation.
    assert is_conversational("how are you") is True
    assert is_conversational("good morning") is True
    assert is_conversational("thank you") is True


def test_normalize_knowledge_subject_strips_question_framing():
    assert TaskRuntime._normalize_knowledge_subject("What is Python?") == "Python"
    assert TaskRuntime._normalize_knowledge_subject("What is Python programming language?") == "Python programming language"
    assert TaskRuntime._normalize_knowledge_subject("Who is Guido van Rossum?") == "Guido van Rossum"
    assert TaskRuntime._normalize_knowledge_subject("find out about the solar system and remember it") == "the solar system"
    assert TaskRuntime._normalize_knowledge_subject("define Eiffel Tower") == "Eiffel Tower"
    assert TaskRuntime._normalize_knowledge_subject("python kya hai") == "python"
    # A naked subject is left untouched.
    assert TaskRuntime._normalize_knowledge_subject("solar system") == "solar system"


# -- general-knowledge wiring through the real execution path ----------------


@pytest.mark.asyncio
async def test_general_knowledge_query_uses_ask_or_research_and_records():
    """'what is X' must ask the knowledge base first, run research when the
    subject is unknown, and answer from the newly recorded facts - never from
    the raw memory search."""
    research_task = _FakeResearchTask()
    knowledge = _FakeKnowledgeService()
    memory = _FakeMemoryRetriever()
    runtime = _make_runtime(
        knowledge_service=knowledge,
        phase8_engine=_FakePhase8(research_task),
        memory_retriever=memory,
    )

    collected: list[dict] = []
    result = await runtime._answer_memory_query("memory_search", "What is Python?", collected)

    # Knowledge-first: the runtime called ask_or_research, not recall.
    assert knowledge.ask_or_research_calls == 1
    # Research actually ran on the (normalized) subject and recorded the fact.
    assert knowledge.research_fn_invocations == 1
    assert len(research_task.runs) == 1
    assert research_task.runs[0][0] == "Python"  # framing stripped from the query
    # The freshly recorded fact is answered, with knowledge provenance.
    output = result["output"]
    assert result["ok"] is True
    assert any(item.get("knowledge") is True for item in output)
    assert any("newly researched fact" in item["summary"] for item in output)
    # Raw memory was never consulted for a world-knowledge question.
    assert memory.searched == []
    assert collected  # an observation was appended for UI composition


@pytest.mark.asyncio
async def test_subject_only_query_from_gk_original_request_still_researches():
    """The planner often hands over just the subject ('solar system') with the
    'find out about ... and remember it' framing dropped. When the ORIGINAL
    task request was a general-knowledge question, the subject-only query must
    still use the KB-first-then-research flow and never touch raw memory."""
    research_task = _FakeResearchTask()
    knowledge = _FakeKnowledgeService()
    memory = _FakeMemoryRetriever()
    runtime = _make_runtime(
        knowledge_service=knowledge,
        phase8_engine=_FakePhase8(research_task),
        memory_retriever=memory,
    )

    # general_knowledge=True is what the handler passes when the ORIGINAL
    # request ("find out about the solar system and remember it") is GK.
    result = await runtime._answer_memory_query(
        "memory_search", "solar system", [], general_knowledge=True)

    assert knowledge.ask_or_research_calls == 1
    assert knowledge.research_fn_invocations == 1
    assert research_task.runs[0][0] == "solar system"
    assert result["ok"] is True
    assert any(item.get("knowledge") is True for item in result["output"])
    assert memory.searched == []  # never fell to raw memory


@pytest.mark.asyncio
async def test_subject_only_query_without_gk_flag_uses_raw_memory():
    """'solar system' handed as a plain query for an internal-memory request
    ('what do you remember about my client') must use raw memory recall only -
    no research call, no knowledge base."""
    research_task = _FakeResearchTask()
    knowledge = _FakeKnowledgeService()
    memory = _FakeMemoryRetriever()
    runtime = _make_runtime(
        knowledge_service=knowledge,
        phase8_engine=_FakePhase8(research_task),
        memory_retriever=memory,
    )

    result = await runtime._answer_memory_query(
        "memory_search", "my client", [], general_knowledge=False)

    assert knowledge.ask_or_research_calls == 0
    assert research_task.runs == []
    assert memory.searched == ["my client"]
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_general_knowledge_question_already_known_skips_research():
    """A fact already in the knowledge base is answered immediately - no
    research call, no raw memory search."""
    research_task = _FakeResearchTask()
    knowledge = _FakeKnowledgeService(facts=[
        KnowledgeFact(subject="Python", predicate="created by", value="Guido van Rossum",
                      source_url="https://python.org/about"),
    ])
    memory = _FakeMemoryRetriever()
    runtime = _make_runtime(
        knowledge_service=knowledge,
        phase8_engine=_FakePhase8(research_task),
        memory_retriever=memory,
    )

    result = await runtime._answer_memory_query(
        "memory_search", "What is Python?", [])

    assert knowledge.ask_or_research_calls == 1
    assert knowledge.research_fn_invocations == 0  # fresh, no research needed
    assert research_task.runs == []
    assert result["ok"] is True
    assert result["stale"] is False
    assert any(item["summary"] == "Python created by Guido van Rossum" for item in result["output"])
    assert memory.searched == []


@pytest.mark.asyncio
async def test_internal_memory_question_stays_on_raw_recall_no_research():
    """'what do you remember about my client' is memory recall, not a world
    question - research must never be triggered for it."""
    research_task = _FakeResearchTask()
    knowledge = _FakeKnowledgeService()  # nothing in the KB
    memory = _FakeMemoryRetriever()
    runtime = _make_runtime(
        knowledge_service=knowledge,
        phase8_engine=_FakePhase8(research_task),
        memory_retriever=memory,
    )

    result = await runtime._answer_memory_query(
        "memory_search", "What do you remember about my client?", [])

    # The runtime used recall, never ask_or_research (no research_fn built).
    assert knowledge.ask_or_research_calls == 0
    assert knowledge.recall_calls == 1
    assert research_task.runs == []  # no live research
    # Fell through to the raw memory search (the honest 'nothing stored' path).
    assert memory.searched == ["What do you remember about my client?"]
    assert result["ok"] is True
    assert "nothing" in result["output"].lower() or "no stored memory" in result["output"].lower()


# -- planner routing --------------------------------------------------------


def test_planner_offers_memory_search_for_general_knowledge_questions():
    """The general-knowledge cues now route to memory_search (the tool body
    that does KB-first-then-research), not only to browser_navigate."""
    planner = GeneralPlanner(model_router=None, providers={})
    names = [tool.name for tool in planner.relevant_tools("What is Python?")]
    assert "memory_search" in names

    names = [tool.name for tool in planner.relevant_tools("find out about the Great Wall and remember it")]
    assert "memory_search" in names

    # Internal memory recall still routes to memory_search too.
    names = [tool.name for tool in planner.relevant_tools("what do you remember about my client")]
    assert "memory_search" in names
