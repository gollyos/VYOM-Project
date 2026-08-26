"""VYOM Plugin System - mirrors Hermes's own hermes_cli/plugins.py (6782
lines, 4 discovery sources, ~30 lifecycle hooks). VYOM's version is
deliberately smaller (a narrow, real, working subset) rather than a
speculative full port - the hook set below covers the actual places
VYOM's own task lifecycle needs extension points, and grows from real
plugin needs rather than upfront guessing.

Discovery sources (later overrides earlier on name collision, same
rule as Hermes):
  1. Bundled:  services/brain/plugins/<name>/
  2. User:     <profile_dir>/plugins/<name>/  (VYOM_PLUGINS_DIR override)

Each plugin directory needs:
  - plugin.yaml   (name, version, description)
  - __init__.py   with a register(ctx) function

register(ctx) may call ctx.register_hook(hook_name, callback) for any
hook in VALID_HOOKS. A callback is an async or sync callable; the
registry awaits it if it returns a coroutine.
"""
from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)

# Every hook VYOM's own runtime actually fires today. Unlike Hermes's much
# larger set (kanban/gateway/approval/streaming...), this list only grows
# when a real fire site exists - see task_runtime.py / main.py for where
# each one is invoked.
VALID_HOOKS: set[str] = {
    "pre_task_create",   # before a Task is persisted; may return {"action": "block", "reason": ...}
    "post_task_complete",  # after TaskStatus.COMPLETED, alongside conversation recording
    "post_task_failed",    # after a task fails verification/execution
    "on_curator_run",      # after a curator pass completes, with its summary
}


@dataclass
class PluginManifest:
    name: str
    version: str
    description: str = ""
    path: Path | None = None


@dataclass
class PluginContext:
    """Passed to each plugin's register(ctx). Deliberately narrow - a
    plugin can register hooks and read its own manifest; it does not get
    raw access to the runtime/database (same boundary philosophy as
    Hermes's PluginContext, which exposes register_tool()/subagent
    lifecycle but not raw AIAgent internals)."""

    manifest: PluginManifest
    _registry: "PluginRegistry"

    def register_hook(self, hook_name: str, callback: Callable) -> None:
        if hook_name not in VALID_HOOKS:
            raise ValueError(
                f"Plugin '{self.manifest.name}' tried to register unknown hook "
                f"'{hook_name}'. Valid hooks: {sorted(VALID_HOOKS)}"
            )
        self._registry._hooks.setdefault(hook_name, []).append((self.manifest.name, callback))


class PluginRegistry:
    """Discovers, loads, and invokes plugins. One instance per Brain
    process, constructed at startup (see main.py)."""

    def __init__(self) -> None:
        self._hooks: dict[str, list[tuple[str, Callable]]] = {}
        self.loaded: dict[str, PluginManifest] = {}
        self.load_errors: dict[str, str] = {}

    def discover_and_load(self, *search_dirs: Path) -> None:
        """Loads every plugin found under each dir, later dirs override
        earlier ones on name collision - same rule as Hermes."""
        for directory in search_dirs:
            if not directory.exists():
                continue
            for entry in sorted(directory.iterdir()):
                if not entry.is_dir():
                    continue
                self._load_one(entry)

    def _load_one(self, plugin_dir: Path) -> None:
        manifest_path = plugin_dir / "plugin.yaml"
        init_path = plugin_dir / "__init__.py"
        if not manifest_path.exists() or not init_path.exists():
            return
        try:
            raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
            manifest = PluginManifest(
                name=raw.get("name", plugin_dir.name),
                version=str(raw.get("version", "0.0.0")),
                description=raw.get("description", ""),
                path=plugin_dir,
            )
            module_name = f"vyom_plugin_{manifest.name}"
            spec = importlib.util.spec_from_file_location(module_name, init_path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not build import spec for {init_path}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
            register_fn = getattr(module, "register", None)
            if register_fn is None or not callable(register_fn):
                raise AttributeError("Plugin __init__.py has no register(ctx) function")
            ctx = PluginContext(manifest=manifest, _registry=self)
            register_fn(ctx)
            self.loaded[manifest.name] = manifest
            self.load_errors.pop(manifest.name, None)
            logger.info("Loaded plugin '%s' v%s from %s", manifest.name, manifest.version, plugin_dir)
        except Exception as error:
            # A broken plugin must never break Brain startup - same
            # invariant as Hermes: log it, record it, keep going.
            self.load_errors[plugin_dir.name] = str(error)[:500]
            logger.warning("Failed to load plugin at %s: %s", plugin_dir, error, exc_info=True)

    async def invoke_hook(self, hook_name: str, **kwargs) -> list[Any]:
        """Runs every registered callback for hook_name, isolated - one
        broken plugin callback can never break another's, or the caller.
        Returns the list of non-exception results (Nones included) in
        registration order."""
        results: list[Any] = []
        for plugin_name, callback in self._hooks.get(hook_name, []):
            try:
                outcome = callback(**kwargs)
                if inspect.isawaitable(outcome):
                    outcome = await outcome
                results.append(outcome)
            except Exception:
                logger.warning(
                    "Plugin '%s' hook '%s' raised; isolated, other plugins unaffected",
                    plugin_name, hook_name, exc_info=True,
                )
        return results

    def has_hook(self, hook_name: str) -> bool:
        return bool(self._hooks.get(hook_name))

    def status(self) -> dict:
        return {
            "loaded": [
                {"name": m.name, "version": m.version, "description": m.description,
                 "hooks": [h for h, cbs in self._hooks.items() if any(n == m.name for n, _ in cbs)]}
                for m in self.loaded.values()
            ],
            "errors": self.load_errors,
        }
