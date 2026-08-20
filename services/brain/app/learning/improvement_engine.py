from __future__ import annotations

from app.memory.manager import MemoryManager
from app.memory.schemas import MemoryQuery, MemoryType

from .failure_analyzer import FailureAnalyzer
from .lesson_store import LessonStore
from .outcome_analyzer import OutcomeAnalyzer
from .promotion_policy import LearningPromotionPolicy


class ImprovementEngine:
    """Event-driven learning. It cannot edit core/security/permission source."""

    def __init__(self, memory: MemoryManager, minimum_confidence: float = 0.65):
        self.memory = memory
        self.outcomes = OutcomeAnalyzer()
        self.failures = FailureAnalyzer()
        self.policy = LearningPromotionPolicy(minimum_confidence)
        self.lessons = LessonStore(memory)

    async def record_failure(
        self,
        *,
        task_id: str,
        title: str,
        error_summary: str,
        project_id: str | None = None,
    ):
        analysis = self.failures.analyze(error_summary)
        if not self.policy.should_store_lesson(analysis, evidence_present=bool(error_summary.strip())):
            return None
        return await self.lessons.record_failure_and_lesson(
            task_id=task_id,
            title=title,
            error_summary=error_summary,
            lesson=analysis["lesson"],
            confidence=analysis["confidence"],
            project_id=project_id,
        )

    async def relevant_lessons(self, query: str, project_id: str | None = None):
        return await self.memory.search(MemoryQuery(text=query, types={MemoryType.LESSON}, project_id=project_id, limit=5))
