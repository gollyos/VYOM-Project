from __future__ import annotations

from app.schemas.approvals import PermissionLevel


class PermissionEngine:
    L3_MARKERS = {
        "pay ", "payment", "transfer money", "trade ", "buy stock", "sell stock",
        "sign contract", "delete important", "delete all", "credentials", "password",
        "security setting", "delete that file", "delete the file", "remove that file",
        "install software", "install a program", "admin action", "elevated action", "run as administrator",
    }
    L2_MARKERS = {
        "send email", "send message", "post publicly", "publish", "deploy",
        "book a", "reserve a", "schedule meeting", "schedule a meeting", "update crm", "submit form",
        "send approved outreach", "send the approved email",
        "send to client", "deliver to", "prepare everything ready to send", "upload deliverable",
        "close vs code", "close chrome", "close the app", "close application",
        "enable auto-start", "enable autostart", "enable startup", "disable auto-start",
        "disable autostart", "disable startup", "modify setting",
    }
    L1_MARKERS = {
        "open vs code", "open chrome", "open notepad", "open my", "focus", "move window",
        "put the editor", "put vs code", "send notification", "notify me", "click the",
        "type into", "open file", "open folder", "open url",
    }
    L0_MARKERS = (
        "status", "explain", "analyze", "summarize", "research", "inspect this project",
        "show me what changed", "show agency", "show inbox", "what needs approval",
        "compare tools", "find a tool", "can vyom connect to", "does vyom have",
        "list windows", "why is my pc slow",
    )

    # The permission a resolved intent genuinely needs, independent of how
    # the sentence was phrased. `classify` alone scans the request text, so
    # a compound request like "create a file ... and show me what changed"
    # matched the read-only marker "show me what changed" and was granted
    # L0 - and then the write tool it was always going to call was refused
    # with "filesystem requires L1; task has L0". The task's granted level
    # is now raised to the floor its own resolved intent requires. Raising
    # the floor never bypasses a gate: L2/L3 floors still route through the
    # normal approval path in TaskRuntime.
    INTENT_FLOOR = {
        "fs_list": PermissionLevel.L0, "fs_read": PermissionLevel.L0,
        "fs_search": PermissionLevel.L0, "inspect_project": PermissionLevel.L0,
        "show_changes": PermissionLevel.L0, "situation_report": PermissionLevel.L0,
        # Looking at the desktop, or reading this machine's own state,
        # changes nothing at all.
        "screen_observe": PermissionLevel.L0, "system_query": PermissionLevel.L0,
        # Closing an application the user just asked to close, opening a
        # Settings page, and pressing a named control in a visible window
        # are ordinary operating actions at the same level as launching an
        # app. They are bounded, immediately observable and trivially
        # reversible, so they do not sit behind an approval prompt - the
        # destructive set (delete, send, money, security settings) keeps
        # its own L2/L3 gates below and is unaffected.
        "app_close": PermissionLevel.L1, "settings_open": PermissionLevel.L1,
        "ui_interact": PermissionLevel.L1,
        # Browser targets. Listing tabs only reads; closing ONE tab and
        # opening a profile are bounded, reversible operating actions.
        "browser_tab_list": PermissionLevel.L0,
        "browser_tab_close": PermissionLevel.L1,
        "browser_profile_open": PermissionLevel.L1,
        # Bringing a window the user asked for back to the front.
        "recover_visibility": PermissionLevel.L1,
        "create_project_file": PermissionLevel.L1, "app_launch": PermissionLevel.L1,
        "web_browse": PermissionLevel.L1, "run_command": PermissionLevel.L1,
        # Comparing listings only reads retailer pages. Placing an order is
        # a separate, consequential action that keeps its own L2/L3 gate -
        # shop_compare can never buy anything.
        "shop_compare": PermissionLevel.L1,
        "run_tests": PermissionLevel.L1, "inspect_project_build": PermissionLevel.L1,
        "open_local_app": PermissionLevel.L1,
        "delete_project_file": PermissionLevel.L3,
    }
    _ORDER = {PermissionLevel.L0: 0, PermissionLevel.L1: 1, PermissionLevel.L2: 2, PermissionLevel.L3: 3}

    def minimum_for_intent(self, intent: str) -> PermissionLevel | None:
        return self.INTENT_FLOOR.get(intent)

    def raise_to_intent_floor(self, level: PermissionLevel, intent: str) -> PermissionLevel:
        floor = self.minimum_for_intent(intent)
        if floor is None:
            return level
        return floor if self._ORDER[floor] > self._ORDER[level] else level

    def classify(self, request: str) -> PermissionLevel:
        normalized = request.lower()
        # Phase 10: paper trading is simulated, never real money. Checked
        # before the generic "trade "/"buy stock" L3 markers below so a
        # phrase like "create a paper trade setup" is never misclassified
        # as the real-money action those markers exist to catch. See
        # docs/TRADING_RISK_POLICY.md and docs/AUTONOMY_POLICY.md.
        if "paper" in normalized and ("trade" in normalized or "order" in normalized or "position" in normalized):
            if "strategy" in normalized or "automat" in normalized:
                return PermissionLevel.L2
            if any(word in normalized for word in ("place", "execute", "submit", "confirm", "close", "cancel")):
                return PermissionLevel.L2
            return PermissionLevel.L1
        if any(marker in normalized for marker in self.L3_MARKERS):
            return PermissionLevel.L3
        if any(marker in normalized for marker in self.L2_MARKERS):
            return PermissionLevel.L2
        if "build" in normalized or "run the tests" in normalized or "open the project" in normalized:
            return PermissionLevel.L1
        if any(marker in normalized for marker in self.L0_MARKERS):
            return PermissionLevel.L0
        if any(marker in normalized for marker in self.L1_MARKERS):
            return PermissionLevel.L1
        return PermissionLevel.L1

    def authorize_tool(self, granted: PermissionLevel, required: PermissionLevel) -> bool:
        order = {PermissionLevel.L0: 0, PermissionLevel.L1: 1, PermissionLevel.L2: 2, PermissionLevel.L3: 3}
        return order[granted] >= order[required]

    @staticmethod
    def requires_approval(level: PermissionLevel) -> bool:
        return level in {PermissionLevel.L2, PermissionLevel.L3}
