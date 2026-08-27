"""
Interactive Teachable Macros Engine for VYOM.
Allows the owner (Gunjan) to teach, record, parameterize, and execute
custom macro workflows across desktop tools, keyboard typing, apps, and messaging.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


@dataclass
class MacroAction:
    action_type: str  # "type_text" | "open_app" | "send_message" | "send_email" | "run_command" | "delay" | "speak"
    params: dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass
class Macro:
    id: str
    name: str
    trigger_type: str  # "phrase" | "event" | "shortcut" | "schedule"
    trigger_pattern: str
    actions: list[MacroAction] = field(default_factory=list)
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    execution_count: int = 0


class MacroEngine:
    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or Path("services/brain/data/macros.json")
        self.macros: dict[str, Macro] = {}
        self.action_handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._load()

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                for item in data.get("macros", []):
                    actions = [MacroAction(**act) for act in item.get("actions", [])]
                    macro_data = dict(item)
                    macro_data["actions"] = actions
                    macro = Macro(**macro_data)
                    self.macros[macro.id] = macro
            except Exception:
                self.macros = {}

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "macros": [
                {
                    **asdict(m),
                    "actions": [asdict(a) for a in m.actions],
                }
                for m in self.macros.values()
            ]
        }
        self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def register_handler(self, action_type: str, handler: Callable[[dict[str, Any]], Any]) -> None:
        self.action_handlers[action_type] = handler

    def teach_macro(
        self,
        name: str,
        trigger_pattern: str,
        actions: list[dict[str, Any]],
        *,
        trigger_type: str = "phrase",
    ) -> Macro:
        macro_id = name.lower().replace(" ", "_").strip()
        parsed_actions = [MacroAction(**act) for act in actions]
        macro = Macro(
            id=macro_id,
            name=name,
            trigger_type=trigger_type,
            trigger_pattern=trigger_pattern.lower().strip(),
            actions=parsed_actions,
        )
        self.macros[macro_id] = macro
        self._save()
        return macro

    def find_matching_macro(self, text: str) -> Macro | None:
        cleaned = text.lower().strip()
        for macro in self.macros.values():
            if not macro.enabled:
                continue
            if macro.trigger_pattern in cleaned or cleaned in macro.trigger_pattern:
                return macro
        return None

    async def execute_macro(self, macro_id: str, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        macro = self.macros.get(macro_id)
        if not macro:
            raise ValueError(f"Macro {macro_id!r} not found.")

        results: list[dict[str, Any]] = []
        for step_idx, action in enumerate(macro.actions):
            handler = self.action_handlers.get(action.action_type)
            params = dict(action.params)
            # Interpolate context
            if context:
                for k, v in params.items():
                    if isinstance(v, str) and "{{" in v:
                        for ck, cv in context.items():
                            params[k] = params[k].replace(f"{{{{{ck}}}}}", str(cv))

            if action.action_type == "delay":
                secs = float(params.get("seconds", 1.0))
                await asyncio.sleep(secs)
                res = {"action": "delay", "seconds": secs, "status": "completed"}
            elif handler:
                if asyncio.iscoroutinefunction(handler):
                    output = await handler(params)
                else:
                    output = handler(params)
                res = {"action": action.action_type, "output": output, "status": "completed"}
            else:
                res = {"action": action.action_type, "params": params, "status": "simulated"}

            results.append(res)

        macro.execution_count += 1
        self._save()
        return results
