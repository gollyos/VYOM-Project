from __future__ import annotations

from typing import Any

from app.desktop.worker import run_blocking
from app.input_control.accessibility import AccessibilityUnavailableError, NativeAccessibilityController
from app.input_control.keyboard import KeyboardController
from app.input_control.mouse import MouseController
from app.input_control.policy import EmergencyPauseActiveError, InputSafetyPolicy, SensitiveInputBlockedError
from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolPermissionError, ToolUnavailableError, ToolValidationError
from app.tools.result import EvidenceItem, ToolResult

ACCESSIBILITY_ACTIONS = {"accessibility_click", "accessibility_set_value", "accessibility_read_text", "accessibility_invoke"}
MOUSE_ACTIONS = {"mouse_move", "mouse_click", "mouse_double_click", "mouse_scroll", "mouse_drag"}
KEYBOARD_ACTIONS = {"keyboard_type", "keyboard_press", "keyboard_shortcut"}


class InputControlTool(BaseTool):
    """Accessibility-first native automation (L1) with a bounded, last-
    resort mouse/keyboard fallback (L2). Every action requires a known
    target/context, is policy- and emergency-pause-checked, and is
    recorded to the action log before execution -- see
    docs/DESKTOP_SECURITY.md's preferred execution order."""

    metadata = ToolMetadata(
        name="input_control",
        description="Accessibility-first control with bounded mouse/keyboard fallback",
        category="input",
        required_permissions=[PermissionLevel.L1],
        risk_level="high",
    )

    def __init__(
        self,
        accessibility: NativeAccessibilityController,
        mouse: MouseController,
        keyboard: KeyboardController,
        policy: InputSafetyPolicy,
    ):
        self.accessibility = accessibility
        self.mouse = mouse
        self.keyboard = keyboard
        self.policy = policy

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", ""))
        if action in ACCESSIBILITY_ACTIONS:
            return PermissionLevel.L1
        # Pressing ONE named key on the focused page (media shortcuts like
        # "k" for YouTube play) is the same bounded, visible, reversible
        # class as a page click - L1. Typing arbitrary strings and mouse
        # paths stay L2.
        if action == "keyboard_press" and len(str(inputs.get("key", ""))) == 1:
            return PermissionLevel.L1
        if action in MOUSE_ACTIONS | KEYBOARD_ACTIONS:
            return PermissionLevel.L2
        return PermissionLevel.L2

    def validate(self, inputs: dict[str, Any], context: ToolContext) -> None:
        super().validate(inputs, context)
        action = str(inputs.get("action", ""))
        if action not in (ACCESSIBILITY_ACTIONS | MOUSE_ACTIONS | KEYBOARD_ACTIONS):
            raise ToolValidationError(f"Unsupported input_control action: {action}")

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        self.validate(inputs, context)
        action = str(inputs["action"])
        context_label = str(inputs.get("context", ""))

        try:
            if action in ACCESSIBILITY_ACTIONS:
                event_type = "accessibility_action"
                # Same pywinauto/UI Automation controller desktop.py drives
                # (app.input_control.accessibility.NativeAccessibilityController)
                # - routed through the same single desktop worker thread
                # so it never blocks the Brain event loop, and so it can
                # never run concurrently with a desktop-tool UIA action.
                output = await run_blocking(self._run_accessibility, action, inputs)
            elif action in MOUSE_ACTIONS:
                event_type = "mouse_action"
                # pyautogui move/drag durations and typewrite intervals are
                # real sleeps - also routed off the event loop.
                output = await run_blocking(self._run_mouse, action, inputs, context_label)
            else:
                event_type = "keyboard_action"
                output = await run_blocking(self._run_keyboard, action, inputs, context_label)
        except EmergencyPauseActiveError as error:
            raise ToolPermissionError(str(error)) from error
        except SensitiveInputBlockedError as error:
            raise ToolPermissionError(str(error)) from error
        except AccessibilityUnavailableError as error:
            raise ToolUnavailableError(str(error)) from error

        # See desktop.py's DesktopTool.execute(): a mission cancelled while
        # this ran on the worker thread must not have its (already
        # physically performed) action reported as this task's success.
        context.check_cancelled()

        await context.emit(event_type, f"Input {action}", {"action": action, "context": context_label})
        evidence = EvidenceItem(type="tool_result", summary=f"Input {action} completed", data=output)
        return ToolResult.completed(f"Input {action} completed", output=output, evidence=[evidence])

    def _run_accessibility(self, action: str, inputs: dict[str, Any]) -> dict[str, Any]:
        process_id = int(inputs["process_id"])
        label = str(inputs["label"])
        if action == "accessibility_click":
            result = self.accessibility.click(process_id, label)
        elif action == "accessibility_set_value":
            self.policy.require_not_sensitive(label, str(inputs.get("value", "")))
            result = self.accessibility.set_value(process_id, label, str(inputs.get("value", "")))
        elif action == "accessibility_read_text":
            result = self.accessibility.read_text(process_id, label)
        else:
            result = self.accessibility.invoke(process_id, label)
        return {"success": result.success, "summary": result.summary, "value": result.value}

    def _run_mouse(self, action: str, inputs: dict[str, Any], context_label: str) -> dict[str, Any]:
        if action == "mouse_move":
            self.mouse.move(int(inputs["x"]), int(inputs["y"]), context=context_label)
        elif action == "mouse_click":
            self.mouse.click(int(inputs["x"]), int(inputs["y"]), context=context_label)
        elif action == "mouse_double_click":
            self.mouse.double_click(int(inputs["x"]), int(inputs["y"]), context=context_label)
        elif action == "mouse_scroll":
            self.mouse.scroll(int(inputs["amount"]), context=context_label)
        else:
            self.mouse.drag(int(inputs["x1"]), int(inputs["y1"]), int(inputs["x2"]), int(inputs["y2"]), context=context_label)
        return {"action": action, "context": context_label}

    def _run_keyboard(self, action: str, inputs: dict[str, Any], context_label: str) -> dict[str, Any]:
        if action == "keyboard_type":
            self.keyboard.type_text(str(inputs["text"]), field_label=str(inputs.get("field_label", "")), context=context_label)
        elif action == "keyboard_press":
            self.keyboard.press(str(inputs["key"]), context=context_label)
        else:
            self.keyboard.shortcut(*[str(key) for key in inputs["keys"]], context=context_label)
        return {"action": action, "context": context_label}
