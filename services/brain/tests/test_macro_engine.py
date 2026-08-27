"""Tests for MacroEngine.
Validates teaching macros, pattern matching, action execution,
parameter interpolation, and persistence.
"""
from __future__ import annotations

from pathlib import Path
import pytest

from app.skills.macro_engine import MacroEngine


@pytest.mark.asyncio
async def test_teach_and_match_macro(tmp_path: Path):
    storage = tmp_path / "macros.json"
    engine = MacroEngine(storage)

    macro = engine.teach_macro(
        name="Morning Desk Setup",
        trigger_pattern="shuru karo morning routine",
        actions=[
            {"action_type": "speak", "params": {"text": "Good morning boss, desk ready kar raha hu."}},
            {"action_type": "open_app", "params": {"app_name": "VS Code"}},
            {"action_type": "delay", "params": {"seconds": 0.01}},
        ],
    )

    assert macro.id == "morning_desk_setup"
    assert len(macro.actions) == 3

    # Pattern matching
    matched = engine.find_matching_macro("Boss shuru karo morning routine abhi")
    assert matched is not None
    assert matched.id == "morning_desk_setup"


@pytest.mark.asyncio
async def test_execute_macro_with_handlers(tmp_path: Path):
    storage = tmp_path / "macros.json"
    engine = MacroEngine(storage)

    executed_calls = []

    def mock_type_handler(params):
        executed_calls.append(("type", params["text"]))
        return "typed"

    engine.register_handler("type_text", mock_type_handler)

    engine.teach_macro(
        name="Quick WhatsApp Reply",
        trigger_pattern="reply to client",
        actions=[
            {"action_type": "type_text", "params": {"text": "Hello {{client_name}}, proposal ready hai."}},
        ],
    )

    results = await engine.execute_macro("quick_whatsapp_reply", context={"client_name": "Rahul"})
    assert len(results) == 1
    assert len(executed_calls) == 1
    assert executed_calls[0] == ("type", "Hello Rahul, proposal ready hai.")
