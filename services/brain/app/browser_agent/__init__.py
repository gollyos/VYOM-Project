from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor
from app.tools.result import ToolResult

from .action_planner import ActionPlanner
from .form_filler import FormFiller, FormPreview
from .navigator import BrowserNavigator
from .observer import PageObservation, PageObserver
from .recovery import BrowserRecovery, RecoveryOutcome
from .semantic_locator import SemanticLocator
from .session_memory import DownloadRecord, SessionMemory
from .verifier import BrowserAgentVerifier

__all__ = [
    "ActionPlanner",
    "FormFiller",
    "FormPreview",
    "BrowserNavigator",
    "PageObservation",
    "PageObserver",
    "BrowserRecovery",
    "RecoveryOutcome",
    "SemanticLocator",
    "SessionMemory",
    "DownloadRecord",
    "BrowserAgentVerifier",
    "BrowserAgentRuntime",
    "SemanticActionOutcome",
]


@dataclass
class SemanticActionOutcome:
    action: str
    description: str
    success: bool
    recovered: bool
    attempts: int
    observation: PageObservation | None
    result: ToolResult


class BrowserAgentRuntime:
    """Upgrade over the raw Playwright browser tool implementing:

    observe -> understand page -> choose semantic action -> execute ->
    observe result -> verify -> continue

    Every underlying action is invoked through the shared ToolExecutor, so
    the Browser Agent never bypasses the Permission Engine, evidence
    collector, or cancellation boundary.
    """

    def __init__(
        self,
        executor: ToolExecutor,
        *,
        max_retries: int = 3,
        known_overlay_hints: tuple[str, ...] | None = None,
    ):
        self.executor = executor
        self.observer = PageObserver(executor, known_overlay_hints)
        self.planner = ActionPlanner()
        self.navigator = BrowserNavigator(executor)
        self.recovery = BrowserRecovery(executor, self.observer, self.planner, max_retries)
        self.form_filler = FormFiller(executor, self.planner)
        self.verifier = BrowserAgentVerifier(executor)

    async def navigate(self, url: str, context: ToolContext, memory: SessionMemory) -> ToolResult:
        return await self.navigator.navigate(url, context, memory)

    async def observe(self, context: ToolContext, memory: SessionMemory) -> PageObservation:
        observation = await self.observer.observe(context)
        memory.page_purpose = observation.title or memory.page_purpose
        memory.important_elements = observation.links[:10]
        return observation

    async def perform_semantic_click(
        self,
        description: str,
        context: ToolContext,
        memory: SessionMemory,
    ) -> SemanticActionOutcome:
        action = self.planner.plan_click(description)
        result = await self.executor.invoke("browser", {**action.inputs, "action": "click"}, context)
        memory.record_action("click", action.inputs, result.success)
        if result.success:
            observation = await self.observe(context, memory)
            return SemanticActionOutcome("click", description, True, False, 1, observation, result)

        outcome = await self.recovery.recover_click(description, context, memory)
        observation = await self.observe(context, memory) if outcome.recovered else None
        final_result = result if not outcome.recovered else ToolResult(
            success=True, status=result.status, summary=outcome.message,
            structured_output={"selector": outcome.final_selector},
        )
        return SemanticActionOutcome("click", description, outcome.recovered, outcome.recovered, outcome.attempts, observation, final_result)

    async def fill_form(self, fields: dict[str, str], context: ToolContext, memory: SessionMemory) -> list[ToolResult]:
        return await self.form_filler.fill(fields, context, memory)

    async def verify(self, context: ToolContext, *, expected_text: str | None = None, expected_url: str | None = None) -> ToolResult:
        return await self.verifier.verify_state(context, expected_text=expected_text, expected_url=expected_url)
