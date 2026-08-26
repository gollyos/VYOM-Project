"""Example VYOM plugin - proves the plugin system genuinely works end to
end by appending one line per completed task to a local log file. Real
plugins live in <profile_dir>/plugins/<name>/ (see PluginRegistry in
app/plugins/registry.py); this one ships bundled as a working example.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def register(ctx) -> None:
    log_path = Path(__file__).parent / "task_log.txt"

    async def on_task_complete(task=None, **_kwargs) -> None:
        if task is None:
            return
        line = f"{datetime.now(timezone.utc).isoformat()} | {task.id} | {task.user_request[:120]}\n"
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(line)

    ctx.register_hook("post_task_complete", on_task_complete)
