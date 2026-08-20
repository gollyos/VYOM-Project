from __future__ import annotations

from dataclasses import dataclass

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor

from .action_planner import ActionPlanner
from .observer import PageObserver
from .session_memory import SessionMemory


@dataclass
class RecoveryOutcome:
    recovered: bool
    attempts: int
    final_selector: str | None
    message: str


class BrowserRecovery:
    """action fails -> re-observe -> inspect new state -> find a semantic
    alternative -> retry a bounded number of times. Handles changed
    selectors, overlays, and stale elements without looping unbounded."""

    def __init__(
        self,
        executor: ToolExecutor,
        observer: PageObserver,
        planner: ActionPlanner | None = None,
        max_retries: int = 3,
    ):
        self.executor = executor
        self.observer = observer
        self.planner = planner or ActionPlanner()
        self.max_retries = max(1, max_retries)

    async def recover_click(self, description: str, context: ToolContext, memory: SessionMemory) -> RecoveryOutcome:
        for attempt in range(self.max_retries):
            observation = await self.observer.observe(context)
            if observation.overlays_detected:
                memory.record_error(f"Overlay detected before retry {attempt + 1}: {observation.overlays_detected}")
            selector = self.planner.recovery_selector(description, attempt)
            result = await self.executor.invoke("browser", {"action": "click", "selector": selector}, context)
            memory.record_action("recovery_click", {"selector": selector, "attempt": attempt + 1}, result.success)
            if result.success:
                return RecoveryOutcome(True, attempt + 1, selector, f"Recovered after {attempt + 1} attempt(s)")
        memory.record_error(f"Recovery for '{description}' exhausted {self.max_retries} bounded attempts")
        return RecoveryOutcome(False, self.max_retries, None, "Bounded recovery attempts exhausted")
