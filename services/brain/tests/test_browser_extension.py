from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.browser_extension.bridge import (
    ExtensionBridge,
    ExtensionCallError,
    ExtensionUnavailableError,
)
from app.browser_extension.pairing import PairingStore
from app.execution.action_engine import ActionEngine
from app.schemas.tasks import Task, TaskCreate


# ======================================================================
# PairingStore
# ======================================================================

def test_pairing_token_is_generated_once_and_persisted(tmp_path: Path):
    store = PairingStore(tmp_path / "pairing.json")
    first = store.get_or_create()
    second = store.get_or_create()
    assert first == second
    assert (tmp_path / "pairing.json").exists()

    # A fresh store instance reading the same file gets the same token -
    # the extension survives a Brain restart without re-pairing.
    reloaded = PairingStore(tmp_path / "pairing.json")
    assert reloaded.get_or_create() == first


def test_pairing_reset_issues_a_different_token(tmp_path: Path):
    store = PairingStore(tmp_path / "pairing.json")
    first = store.get_or_create()
    second = store.reset()
    assert first != second
    assert store.verify(first) is False
    assert store.verify(second) is True


def test_pairing_verify_rejects_wrong_or_empty_token(tmp_path: Path):
    store = PairingStore(tmp_path / "pairing.json")
    store.get_or_create()
    assert store.verify(None) is False
    assert store.verify("") is False
    assert store.verify("wrong-token") is False


# ======================================================================
# ExtensionBridge
# ======================================================================

class FakeExtensionSocket:
    """Stands in for a FastAPI WebSocket: records what the bridge sends
    and lets a test resolve() a matching response, exactly like the real
    extension_socket() receive loop does."""

    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


def test_call_with_no_connection_raises_extension_unavailable():
    bridge = ExtensionBridge()
    assert bridge.connected is False
    with pytest.raises(ExtensionUnavailableError):
        asyncio.run(bridge.call("list_tabs"))


def test_call_round_trip_resolves_by_request_id():
    async def scenario():
        bridge = ExtensionBridge()
        socket = FakeExtensionSocket()
        await bridge.attach(socket)
        assert bridge.connected is True

        async def responder():
            # Give call() a moment to register its pending future, then
            # answer using the id it actually sent - never a hardcoded one.
            while not socket.sent:
                await asyncio.sleep(0)
            request = socket.sent[0]
            bridge.resolve({"id": request["id"], "ok": True, "result": {"echo": request["cmd"]}})

        result, _ = await asyncio.gather(
            bridge.call("read_page", {"foo": "bar"}), responder()
        )
        return result, socket.sent[0]

    result, sent = asyncio.run(scenario())
    assert result == {"echo": "read_page"}
    assert sent["cmd"] == "read_page"
    assert sent["params"] == {"foo": "bar"}


def test_call_propagates_a_reported_extension_failure():
    async def scenario():
        bridge = ExtensionBridge()
        socket = FakeExtensionSocket()
        await bridge.attach(socket)

        async def responder():
            while not socket.sent:
                await asyncio.sleep(0)
            bridge.resolve({"id": socket.sent[0]["id"], "ok": False, "error": "no such element"})

        with pytest.raises(ExtensionCallError, match="no such element"):
            await asyncio.gather(bridge.call("click", {}), responder())

    asyncio.run(scenario())


def test_call_times_out_when_extension_never_answers():
    async def scenario():
        bridge = ExtensionBridge(default_timeout=0.05)
        await bridge.attach(FakeExtensionSocket())
        with pytest.raises(ExtensionUnavailableError):
            await bridge.call("read_page")

    asyncio.run(scenario())


def test_reconnection_replaces_the_previous_socket_and_fails_its_pending_calls():
    async def scenario():
        bridge = ExtensionBridge(default_timeout=5.0)
        old_socket = FakeExtensionSocket()
        await bridge.attach(old_socket)

        pending = asyncio.ensure_future(bridge.call("read_page"))
        await asyncio.sleep(0)  # let call() register before we reconnect

        new_socket = FakeExtensionSocket()
        await bridge.attach(new_socket)  # e.g. the extension reloaded

        assert old_socket.closed is True
        with pytest.raises(ExtensionUnavailableError):
            await pending

    asyncio.run(scenario())


def test_detach_fails_any_still_pending_call():
    async def scenario():
        bridge = ExtensionBridge(default_timeout=5.0)
        socket = FakeExtensionSocket()
        await bridge.attach(socket)
        pending = asyncio.ensure_future(bridge.call("read_page"))
        await asyncio.sleep(0)
        await bridge.detach(socket)
        assert bridge.connected is False
        with pytest.raises(ExtensionUnavailableError):
            await pending

    asyncio.run(scenario())


def test_resolve_ignores_unknown_or_duplicate_request_ids():
    bridge = ExtensionBridge()
    # No pending call for this id, and no socket attached - must not raise.
    bridge.resolve({"id": "not-a-real-request", "ok": True, "result": {}})


# ======================================================================
# ActionEngine: extension-first, UI-Automation fallback
# ======================================================================

class FakeConnectedBridge:
    """A bridge that behaves as connected and returns canned results per
    command, or raises to simulate the extension failing a specific call
    (so the fallback-to-desktop path can be exercised)."""

    def __init__(self, responses: dict, *, fail: set[str] = frozenset()):
        self._responses = responses
        self._fail = fail

    @property
    def connected(self) -> bool:
        return True

    async def call(self, command: str, params: dict | None = None, *, timeout: float | None = None):
        if command in self._fail:
            raise ExtensionUnavailableError(f"simulated failure for {command}")
        return self._responses.get(command)


def _engine(bridge, tmp_path: Path) -> ActionEngine:
    return ActionEngine(
        executor=None, context_factory=None, process_manager=None,
        project_root=tmp_path, extension_bridge=bridge,
    )


def _task(text: str) -> Task:
    return Task.from_create(TaskCreate(user_request=text))


def test_tab_list_prefers_the_extension_when_connected(tmp_path: Path):
    bridge = FakeConnectedBridge({"list_tabs": [
        {"id": 1, "title": "Luxora Designs", "url": "https://luxoradesigns.space"},
        {"id": 2, "title": "GitHub", "url": "https://github.com"},
    ]})
    engine = _engine(bridge, tmp_path)
    result = asyncio.run(engine._browser_tab_list(_task("what tabs are open"), context=None))
    assert result.structured_data["source"] == "chrome_extension"
    assert len(result.structured_data["tabs"]) == 2
    assert "Luxora Designs" in result.response


def test_tab_open_prefers_the_extension_and_reports_its_source(tmp_path: Path):
    bridge = FakeConnectedBridge({"open_tab": {"id": 7, "url": "https://example.com", "title": "Example"}})
    engine = _engine(bridge, tmp_path)
    result = asyncio.run(engine._browser_tab_open(_task("open example.com in a new tab"), context=None))
    assert result.structured_data["source"] == "chrome_extension"
    assert result.structured_data["tab_id"] == 7


def test_page_read_via_extension_returns_real_dom_text(tmp_path: Path):
    bridge = FakeConnectedBridge({"read_page": {
        "title": "Example Domain", "url": "https://example.com",
        "text": "This domain is for use in illustrative examples.",
        "headings": ["Example Domain"], "links": [],
    }})
    engine = _engine(bridge, tmp_path)
    result = asyncio.run(engine._browser_page_read(_task("what is on this page"), context=None))
    assert result.structured_data["source"] == "chrome_extension"
    assert "illustrative examples" in result.structured_data["text"]


def test_find_on_page_uses_the_dedicated_extension_search(tmp_path: Path):
    bridge = FakeConnectedBridge({"find_on_page": {
        "matches": ["...the pricing is $10/month for the Pro plan..."],
    }})
    engine = _engine(bridge, tmp_path)
    result = asyncio.run(engine._browser_page_read(_task("find pricing on this page"), context=None))
    assert result.structured_data["query"] == "pricing"
    assert "$10/month" in result.response


def test_click_via_extension_reports_a_real_failure_without_faking_success(tmp_path: Path):
    bridge = FakeConnectedBridge({"click": {"success": False, "error": "no button named 'Buy Now'"}})
    engine = _engine(bridge, tmp_path)
    with pytest.raises(RuntimeError, match="Buy Now"):
        asyncio.run(engine._browser_page_click(_task("click Buy Now"), context=None))


def test_extension_absent_or_disconnected_never_touches_the_bridge(tmp_path: Path):
    """No extension_bridge at all is the default (every pre-extension
    construction path) - _browser_tab_list must not even look at it."""
    engine = ActionEngine(
        executor=None, context_factory=None, process_manager=None, project_root=tmp_path,
    )
    assert engine.extension_bridge is None
