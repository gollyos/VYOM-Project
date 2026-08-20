from __future__ import annotations

from typing import Any

from app.desktop.controller import DesktopController
from app.desktop.schemas import NotificationRequest
from app.desktop.worker import run_blocking
from app.native_apps.registry import NativeAppAdapterRegistry
from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult

# Reading desktop state - including the accessibility tree - observes but
# never changes anything, so it sits at L0 alongside window_list.
L0_ACTIONS = {
    "status", "window_list", "displays", "app_status", "startup_status",
    "process_list_managed", "process_status",
    "active_window", "inspect_ui_tree", "find_control", "get_control_value",
    "browser_tabs", "browser_profiles", "browser_page_read",
}
# Driving a control is an ordinary operating action at the same level as
# focusing a window: it is exactly what the user asked for, it is bounded
# to one named control, and it is fully observable.
L1_ACTIONS = {
    "app_open", "app_focus", "window_focus", "window_move", "window_resize",
    "window_minimize", "window_maximize", "window_restore", "notify", "clipboard_read",
    "clipboard_write", "clipboard_clear", "open_settings_page",
    "invoke_control", "invoke_sequence", "set_control_value",
    # Closing ONE tab is bounded and reversible (the user can reopen it
    # with Ctrl+Shift+T); it is not the same act as closing the browser.
    # Opening one is the same class of bounded, visible, reversible act -
    # and it targets the window the user is already in. Page-level
    # clicks/types/scrolls are the same: exactly what the user asked for,
    # on the visible page, fully observable.
    "browser_close_tab", "browser_open_profile", "browser_open_tab",
    "browser_page_click", "browser_first_result", "browser_page_type",
    "browser_page_scroll",
}
# Closing an application the user explicitly named is an ordinary,
# reversible desktop action; killing an arbitrary process or changing what
# runs at boot is not.
L2_ACTIONS = {"startup_enable", "startup_disable", "process_stop"}
L1_ACTIONS = L1_ACTIONS | {"app_close"}

#: Actions that change what the user can SEE on their machine. These are
#: exactly the actions that were fired without a request in the
#: 2026-08-19 physical session (apps and profiles opening on complaints
#: and fragments), so they now demand PROVENANCE: an owning task whose
#: metadata says a user command authorized them. Observations stay open
#: to any caller - looking at the world is how a decision gets grounded.
_EFFECT_ACTIONS = frozenset({
    "app_open", "app_close", "app_focus", "window_focus", "window_move",
    "window_resize", "window_minimize", "window_maximize", "window_restore",
    "clipboard_write", "clipboard_clear", "notify", "open_settings_page",
    "invoke_control", "invoke_sequence", "set_control_value",
    "browser_close_tab", "browser_open_profile", "browser_open_tab",
    "browser_page_click", "browser_first_result", "browser_page_type",
    "browser_page_scroll",
    "startup_enable", "startup_disable", "process_stop",
})


class DesktopTool(BaseTool):
    """Application launching, window management, clipboard, notification
    dispatch, system status, startup, and VYOM-managed process control.
    Every action still resolves a concrete permission level and passes
    through the same Permission Engine as every other VYOM tool (see
    docs/DESKTOP_SECURITY.md)."""

    metadata = ToolMetadata(
        name="desktop",
        description="Controlled native desktop actions: apps, windows, clipboard, notifications, system status, startup",
        category="desktop",
        required_permissions=[PermissionLevel.L0],
        risk_level="medium",
    )

    def __init__(self, controller: DesktopController, adapters: NativeAppAdapterRegistry | None = None):
        self.controller = controller
        self.adapters = adapters or NativeAppAdapterRegistry()

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", ""))
        if action in L2_ACTIONS:
            return PermissionLevel.L2
        if action in L1_ACTIONS:
            return PermissionLevel.L1
        if action in L0_ACTIONS:
            return PermissionLevel.L0
        return PermissionLevel.L1

    def validate(self, inputs: dict[str, Any], context: ToolContext) -> None:
        super().validate(inputs, context)
        action = str(inputs.get("action", ""))
        if action not in (L0_ACTIONS | L1_ACTIONS | L2_ACTIONS):
            raise ToolValidationError(f"Unsupported desktop action: {action}")

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        self.validate(inputs, context)
        action = str(inputs["action"])
        # NO ACTION WITHOUT A VALID TRIGGER. An effect arriving with no
        # owning task is denied outright: a model, a heartbeat or a stray
        # debug call must never be able to open, close or drive anything
        # on the user's desktop on its own initiative. (Authorized
        # schedules route through their own task-backed contexts.)
        if action in _EFFECT_ACTIONS and not getattr(context, "task_id", None):
            from app.tools.errors import ToolPermissionError

            raise ToolPermissionError(
                f"desktop.{action} was refused: it arrived without an owning task, so no "
                f"user command, approved schedule or safety action authorized it. "
                f"Intelligence is not permission to act."
            )
        # A cancelled or superseded mission has lost its action authority:
        # any late callback racing in after cancellation dies here, before
        # it can change anything the user can see.
        if action in _EFFECT_ACTIONS:
            context.check_cancelled()
        await context.emit("tool_progress", f"Desktop {action}", {"action": action})

        if action == "app_open":
            app_id = str(inputs.get("app_id", ""))
            adapter = self.adapters.get(app_id)
            if adapter is not None:
                result = await adapter.open(target=inputs.get("target"))
                output = {"app_id": app_id, "success": result.success, "summary": result.summary, **result.output}
            else:
                # A launch carries whatever destination the user named: a
                # url for a browser, a folder for Explorer, a project for
                # an editor. Opening a bare window when a destination was
                # named only half-performs the instruction.
                #
                # This is a BLOCKING_UIA call (waits up to ~12s for the
                # window to appear), so it runs on the desktop worker
                # thread, not inline on the event loop.
                target = str(inputs.get("url") or inputs.get("target") or "").strip()
                status = await run_blocking(
                    self.controller.app_open, app_id, args=[target] if target else None)
                output = {**status.model_dump(mode="json"), "target": target or None}
        elif action == "app_focus":
            app_id = str(inputs.get("app_id", ""))
            adapter = self.adapters.get(app_id)
            if adapter is not None:
                try:
                    result = await adapter.focus()
                    output = {"app_id": app_id, "success": result.success, "summary": result.summary}
                except NotImplementedError:
                    output = (await run_blocking(self.controller.app_focus, app_id)).model_dump(mode="json")
            else:
                output = (await run_blocking(self.controller.app_focus, app_id)).model_dump(mode="json")
        elif action == "process_stop":
            # ProcessManager.stop() is already async-native (asyncio
            # subprocess plumbing + asyncio.to_thread for the psutil tree
            # walk) - it does not touch pywinauto/UIA and needs no worker.
            output = await self.controller.process_stop(int(inputs["process_id"]))
        else:
            # Every other action - windows, clipboard, notifications,
            # startup, UI Automation tree reads/invokes, browser-page
            # automation - is a synchronous call into pywinauto/win32.
            # These run on VYOM's dedicated, serialized desktop worker
            # thread (app/desktop/worker.py) instead of the Brain event
            # loop, which is what keeps unrelated voice commands, STOP,
            # and WebSocket traffic responsive while one of these is in
            # flight (some, like invoke_sequence or the browser-page
            # actions, routinely block for multiple seconds).
            output = await run_blocking(self._dispatch_blocking, action, inputs)

        # A cancellation that arrived WHILE the physical action was running
        # on the worker thread must not be reported as success: the
        # desktop call already happened for real (it cannot be safely
        # interrupted mid-flight), but nothing downstream - evidence,
        # ActiveContext, memory, speech - may treat a superseded mission's
        # action as this task's genuine outcome.
        if action in _EFFECT_ACTIONS:
            context.check_cancelled()

        evidence = EvidenceItem(type="tool_result", summary=f"Desktop {action} completed", data=output)
        return ToolResult.completed(f"Desktop {action} completed", output=output, evidence=[evidence])

    def _dispatch_blocking(self, action: str, inputs: dict[str, Any]) -> Any:
        """Every desktop action that is not already async-native (app_open
        and app_focus when a native-app adapter exists, and process_stop).
        Runs on the single serialized desktop worker thread
        (app/desktop/worker.py) - never call this directly from async
        code."""
        if action == "status":
            snapshot = self.controller.status()
            return snapshot.model_dump(mode="json")
        if action == "window_list":
            return {"windows": [window.model_dump(mode="json") for window in self.controller.window_list()]}
        if action == "displays":
            return {"displays": [display.model_dump(mode="json") for display in self.controller.windows.displays()]}
        if action == "app_close":
            app_id = str(inputs.get("app_id", ""))
            return self.controller.app_close(app_id, force=bool(inputs.get("force", False))).model_dump(mode="json")
        if action == "app_status":
            return self.controller.app_status(str(inputs.get("app_id", ""))).model_dump(mode="json")
        if action == "open_settings_page":
            return self.controller.open_settings_page(str(inputs.get("page", "")))
        if action == "browser_tabs":
            tabs = self.controller.list_browser_tabs()
            return {"tabs": tabs, "count": len(tabs)}
        if action == "browser_page_read":
            return self.controller.browser_page_read()
        if action == "browser_page_click":
            return self.controller.browser_page_click(str(inputs["target"]))
        if action == "browser_first_result":
            return self.controller.browser_first_result()
        if action == "browser_page_type":
            return self.controller.browser_page_type(
                str(inputs["value"]), enter=bool(inputs.get("enter", True)),
                field=inputs.get("field"))
        if action == "browser_page_scroll":
            return self.controller.browser_page_scroll(
                direction=str(inputs.get("direction", "down")),
                times=int(inputs.get("times", 3)))
        if action == "browser_open_tab":
            return self.controller.open_browser_tab(str(inputs["url"]))
        if action == "browser_close_tab":
            return self.controller.close_browser_tab(str(inputs["target"]))
        if action == "browser_open_profile":
            return self.controller.open_browser_profile(
                str(inputs.get("profile", "")), url=inputs.get("url"))
        if action == "browser_profiles":
            return {"profiles": self.controller.registry.browser_profiles()}
        if action == "active_window":
            return {"window": self.controller.active_window()}
        if action == "inspect_ui_tree":
            controls = self.controller.inspect_ui_tree(
                app_id=inputs.get("app_id"), title=inputs.get("title"))
            return {"controls": controls, "count": len(controls)}
        if action == "find_control":
            return {"candidates": self.controller.find_control(
                str(inputs["target"]), app_id=inputs.get("app_id"),
                title=inputs.get("title"), role=inputs.get("role"))}
        if action == "invoke_control":
            return self.controller.invoke_control(
                str(inputs["target"]), app_id=inputs.get("app_id"), title=inputs.get("title"))
        if action == "invoke_sequence":
            return self.controller.invoke_sequence(
                [str(item) for item in inputs["targets"]],
                app_id=inputs.get("app_id"), title=inputs.get("title"))
        if action == "set_control_value":
            return self.controller.set_control_value(
                str(inputs["target"]), str(inputs.get("value", "")),
                app_id=inputs.get("app_id"), title=inputs.get("title"))
        if action == "get_control_value":
            return self.controller.get_control_value(
                str(inputs["target"]), app_id=inputs.get("app_id"), title=inputs.get("title"))
        if action == "window_focus":
            return self.controller.window_focus(str(inputs["title"])).model_dump(mode="json")
        if action == "window_minimize":
            return self.controller.window_minimize(str(inputs["title"])).model_dump(mode="json")
        if action == "window_maximize":
            return self.controller.window_maximize(str(inputs["title"])).model_dump(mode="json")
        if action == "window_restore":
            return self.controller.window_restore(str(inputs["title"])).model_dump(mode="json")
        if action == "window_move":
            return self.controller.window_move(str(inputs["title"]), int(inputs["x"]), int(inputs["y"])).model_dump(mode="json")
        if action == "window_resize":
            return self.controller.window_resize(str(inputs["title"]), int(inputs["width"]), int(inputs["height"])).model_dump(mode="json")
        if action == "clipboard_read":
            content, entry = self.controller.clipboard_read()
            return {"content": content, **entry.model_dump(mode="json")}
        if action == "clipboard_write":
            entry = self.controller.clipboard_write(str(inputs.get("content", "")))
            return entry.model_dump(mode="json")
        if action == "clipboard_clear":
            return self.controller.clipboard_clear().model_dump(mode="json")
        if action == "notify":
            request = NotificationRequest(
                title=str(inputs["title"]), body=str(inputs["body"]),
                category=str(inputs.get("category", "needs_intervention")),
                action_task_id=inputs.get("action_task_id"),
            )
            dispatched = self.controller.notify(request)
            return {"dispatched": dispatched is not None, "notification": (dispatched or request).model_dump(mode="json")}
        if action == "startup_status":
            return self.controller.startup_status().model_dump(mode="json")
        if action == "startup_enable":
            return self.controller.startup_enable().model_dump(mode="json")
        if action == "startup_disable":
            return self.controller.startup_disable().model_dump(mode="json")
        if action == "process_list_managed":
            return {"processes": self.controller.process_list_managed()}
        if action == "process_status":
            return self.controller.process_status(int(inputs["process_id"]))
        raise ToolValidationError(f"Unsupported desktop action: {action}")
