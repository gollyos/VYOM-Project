from __future__ import annotations

from app.memory.manager import MemoryManager
from app.memory.schemas import (
    MemoryEntry,
    MemoryProvenance,
    MemoryType,
    ProvenanceType,
    VerificationState,
)


class LessonStore:
    def __init__(self, memory: MemoryManager):
        self.memory = memory

    async def record_failure_and_lesson(
        self,
        *,
        task_id: str,
        title: str,
        error_summary: str,
        lesson: str,
        confidence: float,
        project_id: str | None = None,
    ) -> tuple[MemoryEntry, MemoryEntry]:
        provenance = [MemoryProvenance(type=ProvenanceType.TASK_RESULT, task_id=task_id, reference="verified failure outcome")]
        failure = await self.memory.remember(MemoryEntry(
            type=MemoryType.FAILURE,
            title=title,
            content=error_summary,
            summary=error_summary[:500],
            provenance=provenance,
            task_id=task_id,
            project_id=project_id,
            importance=0.65,
            confidence=1,
            verification_state=VerificationState.VERIFIED,
            tags=["failure", "verified-outcome"],
        ))
        lesson_memory = await self.memory.remember(MemoryEntry(
            type=MemoryType.LESSON,
            title=f"Lesson from {title}",
            content=lesson,
            summary=lesson,
            provenance=provenance,
            task_id=task_id,
            project_id=project_id,
            importance=0.75,
            confidence=confidence,
            verification_state=VerificationState.INFERRED,
            tags=["lesson", "failure-prevention"],
        ))
        from app.memory.schemas import RelationType
        await self.memory.relationships.connect(lesson_memory.id, failure.id, RelationType.LEARNED_FROM, confidence)
        return failure, lesson_memory
