from __future__ import annotations

from dataclasses import dataclass, field

from app.tools.context import ToolContext
from app.tools.executor import ToolExecutor


@dataclass
class PageObservation:
    url: str
    title: str
    text_summary: str
    links: list[str] = field(default_factory=list)
    overlays_detected: list[str] = field(default_factory=list)


class PageObserver:
    """Observe -> understand page. Uses the registered browser tool so every
    read still passes through the Permission Engine and audit evidence."""

    KNOWN_OVERLAY_HINTS = ("cookie", "consent", "subscribe", "newsletter", "sign up to continue", "accept all")

    def __init__(self, executor: ToolExecutor, known_overlay_hints: tuple[str, ...] | None = None):
        self.executor = executor
        self.overlay_hints = known_overlay_hints or self.KNOWN_OVERLAY_HINTS

    async def observe(self, context: ToolContext) -> PageObservation:
        read_result = await self.executor.invoke("browser", {"action": "read"}, context)
        text = str(read_result.structured_output.get("text", ""))
        extract_result = await self.executor.invoke("browser", {"action": "extract", "selector": "a[href]"}, context)
        links = [str(item) for item in extract_result.structured_output.get("items", [])][:25]
        overlays = [hint for hint in self.overlay_hints if hint in text.lower()]
        return PageObservation(
            url=str(read_result.structured_output.get("url", "")),
            title=str(read_result.structured_output.get("title", "")),
            text_summary=text[:2000],
            links=links,
            overlays_detected=overlays,
        )
