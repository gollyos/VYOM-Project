from __future__ import annotations

from typing import Protocol

from .policy import InputSafetyPolicy

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


class MouseBackend(Protocol):
    def move(self, x: int, y: int, duration: float) -> None: ...
    def click(self, x: int, y: int) -> None: ...
    def double_click(self, x: int, y: int) -> None: ...
    def scroll(self, amount: int) -> None: ...
    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float) -> None: ...
    def position(self) -> tuple[int, int]: ...


class MouseAutomationUnavailableError(Exception):
    pass


class PyAutoGuiMouseBackend:
    """Real desktop mouse control. This is the controlled fallback tier --
    never the preferred execution method (see docs/DESKTOP_CONTROL.md).
    `pyautogui.FAILSAFE` stays enabled so the user can always abort by
    moving the mouse to a screen corner."""

    def __init__(self):
        if not PYAUTOGUI_AVAILABLE:
            raise MouseAutomationUnavailableError("Mouse automation requires pyautogui")
        pyautogui.FAILSAFE = True

    def move(self, x: int, y: int, duration: float = 0.2) -> None:
        pyautogui.moveTo(x, y, duration=duration)

    def click(self, x: int, y: int) -> None:
        pyautogui.click(x, y)

    def double_click(self, x: int, y: int) -> None:
        pyautogui.doubleClick(x, y)

    def scroll(self, amount: int) -> None:
        pyautogui.scroll(amount)

    def drag(self, x1: int, y1: int, x2: int, y2: int, duration: float = 0.3) -> None:
        pyautogui.moveTo(x1, y1)
        pyautogui.dragTo(x2, y2, duration=duration)

    def position(self) -> tuple[int, int]:
        point = pyautogui.position()
        return (point.x, point.y)


class MouseController:
    """Controlled last-resort mouse automation. Requires a known
    target/context, records every action through InputSafetyPolicy, and
    is bounded by the policy's sequence limits."""

    def __init__(self, backend: MouseBackend, policy: InputSafetyPolicy):
        self.backend = backend
        self.policy = policy

    def move(self, x: int, y: int, *, context: str) -> None:
        self.policy.require_safe_target(context)
        self.backend.move(x, y, 0.2)
        self.policy.record("mouse_move", f"{x},{y}", context)

    def click(self, x: int, y: int, *, context: str) -> None:
        self.policy.require_safe_target(context)
        self.backend.click(x, y)
        self.policy.record("mouse_click", f"{x},{y}", context)

    def double_click(self, x: int, y: int, *, context: str) -> None:
        self.policy.require_safe_target(context)
        self.backend.double_click(x, y)
        self.policy.record("mouse_double_click", f"{x},{y}", context)

    def scroll(self, amount: int, *, context: str) -> None:
        self.policy.require_safe_target(context)
        self.backend.scroll(amount)
        self.policy.record("mouse_scroll", str(amount), context)

    def drag(self, x1: int, y1: int, x2: int, y2: int, *, context: str) -> None:
        self.policy.require_safe_target(context)
        self.backend.drag(x1, y1, x2, y2, 0.3)
        self.policy.record("mouse_drag", f"{x1},{y1}->{x2},{y2}", context)
