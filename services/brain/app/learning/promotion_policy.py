from __future__ import annotations


class LearningPromotionPolicy:
    def __init__(self, minimum_confidence: float = 0.65):
        self.minimum_confidence = minimum_confidence

    def should_store_lesson(self, analysis: dict | None, *, evidence_present: bool) -> bool:
        return bool(analysis and evidence_present and analysis.get("confidence", 0) >= self.minimum_confidence)
