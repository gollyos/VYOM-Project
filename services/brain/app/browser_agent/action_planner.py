from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .observer import PageObservation
from .semantic_locator import SemanticLocator

CONSEQUENTIAL_HINTS = ("submit", "purchase", "pay", "confirm order", "delete", "book", "checkout")


@dataclass
class PlannedAction:
    action: str
    inputs: dict[str, Any]
    consequential: bool = False


class ActionPlanner:
    """Chooses a semantic action rather than a fixed coordinate. Consequential
    intents (submit/pay/delete/...) are flagged so the caller can apply the
    approval boundary before executing."""

    def __init__(self, locator: SemanticLocator | None = None):
        self.locator = locator or SemanticLocator()

    def plan_click(self, description: str, observation: PageObservation | None = None) -> PlannedAction:
        selector = self.locator.locate(description)
        consequential = any(hint in description.lower() for hint in CONSEQUENTIAL_HINTS)
        return PlannedAction("click", {"selector": selector, "consequential": consequential}, consequential)

    def plan_type(self, description: str, value: str) -> PlannedAction:
        selector = self.locator.locate(description)
        return PlannedAction("type", {"selector": selector, "text": value})

    def plan_select(self, description: str, value: str) -> PlannedAction:
        selector = self.locator.locate(description)
        return PlannedAction("select", {"selector": selector, "value": value})

    def recovery_selector(self, description: str, attempt: int) -> str:
        alternatives = self.locator.alternatives(description)
        return alternatives[min(attempt, len(alternatives) - 1)]
