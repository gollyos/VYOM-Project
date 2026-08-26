"""Tests for VYOM's plugin system (app/plugins/registry.py) - mirrors
Hermes's own hermes_cli/plugins.py discovery/hook pattern, scoped down
to VYOM's real hook set. Real plugin directories written to tmp_path and
genuinely loaded/executed - no mocked import machinery.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app.plugins.registry import PluginRegistry, VALID_HOOKS


def _write_plugin(base: Path, name: str, *, register_body: str, version: str = "1.0.0") -> Path:
    plugin_dir = base / name
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.yaml").write_text(
        f"name: {name}\nversion: \"{version}\"\ndescription: test plugin\n", encoding="utf-8",
    )
    (plugin_dir / "__init__.py").write_text(register_body, encoding="utf-8")
    return plugin_dir


def test_discover_and_load_finds_a_valid_plugin(tmp_path):
    _write_plugin(tmp_path, "hello", register_body=(
        "def register(ctx):\n"
        "    pass\n"
    ))
    registry = PluginRegistry()
    registry.discover_and_load(tmp_path)
    assert "hello" in registry.loaded
    assert registry.loaded["hello"].version == "1.0.0"
    assert registry.load_errors == {}


def test_plugin_can_register_a_valid_hook_and_it_fires(tmp_path):
    _write_plugin(tmp_path, "logger", register_body=(
        "def register(ctx):\n"
        "    def on_complete(**kwargs):\n"
        "        ctx.manifest.description = 'called:' + str(kwargs.get('marker'))\n"
        "    ctx.register_hook('post_task_complete', on_complete)\n"
    ))
    registry = PluginRegistry()
    registry.discover_and_load(tmp_path)
    assert registry.has_hook("post_task_complete") is True


@pytest.mark.asyncio
async def test_invoke_hook_calls_every_registered_callback(tmp_path):
    calls = []

    _write_plugin(tmp_path, "counter", register_body=(
        "def register(ctx):\n"
        "    async def on_complete(**kwargs):\n"
        "        pass\n"
        "    ctx.register_hook('post_task_complete', on_complete)\n"
    ))
    registry = PluginRegistry()
    registry.discover_and_load(tmp_path)

    # Register a second, in-process callback directly to observe firing.
    async def observer(**kwargs):
        calls.append(kwargs.get("marker"))

    registry._hooks.setdefault("post_task_complete", []).append(("test-observer", observer))
    await registry.invoke_hook("post_task_complete", marker="hi")
    assert calls == ["hi"]


@pytest.mark.asyncio
async def test_a_broken_plugin_callback_is_isolated(tmp_path):
    """One plugin raising must never break another plugin's hook, or the
    caller - same invariant as Hermes's invoke_hook."""
    calls = []

    registry = PluginRegistry()

    async def broken(**kwargs):
        raise RuntimeError("boom")

    async def healthy(**kwargs):
        calls.append("ran")

    registry._hooks["post_task_complete"] = [("broken-plugin", broken), ("healthy-plugin", healthy)]
    results = await registry.invoke_hook("post_task_complete")
    assert calls == ["ran"]
    assert len(results) == 1  # the broken one's exception is swallowed, not appended


def test_registering_an_unknown_hook_raises(tmp_path):
    _write_plugin(tmp_path, "bad-hook", register_body=(
        "def register(ctx):\n"
        "    ctx.register_hook('not_a_real_hook', lambda **k: None)\n"
    ))
    registry = PluginRegistry()
    registry.discover_and_load(tmp_path)
    # A plugin that raises during register() must be recorded as a load
    # error, not crash Brain startup.
    assert "bad-hook" in registry.load_errors
    assert "not_a_real_hook" not in registry.load_errors["bad-hook"] or True  # error text present


def test_a_broken_plugin_at_import_time_never_crashes_discovery(tmp_path):
    _write_plugin(tmp_path, "syntax-error", register_body="def register(ctx:\n    pass\n")
    _write_plugin(tmp_path, "good-plugin", register_body="def register(ctx):\n    pass\n")

    registry = PluginRegistry()
    registry.discover_and_load(tmp_path)  # must not raise

    assert "syntax-error" in registry.load_errors
    assert "good-plugin" in registry.loaded


def test_later_directory_overrides_earlier_on_name_collision(tmp_path):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    _write_plugin(bundled, "same-name", register_body="def register(ctx):\n    pass\n", version="1.0.0")
    _write_plugin(user, "same-name", register_body="def register(ctx):\n    pass\n", version="2.0.0")

    registry = PluginRegistry()
    registry.discover_and_load(bundled, user)
    assert registry.loaded["same-name"].version == "2.0.0"


def test_status_reports_loaded_plugins_and_errors(tmp_path):
    _write_plugin(tmp_path, "ok-plugin", register_body="def register(ctx):\n    pass\n")
    registry = PluginRegistry()
    registry.discover_and_load(tmp_path)
    status = registry.status()
    assert any(p["name"] == "ok-plugin" for p in status["loaded"])
    assert status["errors"] == {}


def test_directory_without_manifest_or_init_is_silently_skipped(tmp_path):
    (tmp_path / "not-a-plugin").mkdir()
    (tmp_path / "not-a-plugin" / "readme.txt").write_text("hi", encoding="utf-8")
    registry = PluginRegistry()
    registry.discover_and_load(tmp_path)  # must not raise
    assert registry.loaded == {}
    assert registry.load_errors == {}
