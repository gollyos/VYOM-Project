"""Tests for extract_durable_facts (app/memory/consolidation.py) -
specifically the "I am X" identity pattern's manual case check, which
fixes a real production bug: under re.IGNORECASE (applied to the whole
pattern list), the [A-Z] shape in the old pattern silently matched
lowercase too, so "I am also good" extracted the user's name as
"also".
"""
from __future__ import annotations

from app.memory.consolidation import extract_durable_facts


def _names(facts: list[dict]) -> list[str]:
    return [f["value"] for f in facts if f["title"] == "User name"]


def test_i_am_also_good_does_not_extract_a_name():
    facts = extract_durable_facts("Ja. I am also good and please talk here in Hindi with me.")
    assert _names(facts) == []


def test_i_am_fine_does_not_extract_a_name():
    facts = extract_durable_facts("I am fine, thank you.")
    assert _names(facts) == []


def test_i_am_not_x_does_not_extract_a_name():
    facts = extract_durable_facts("I am not sure about that.")
    assert _names(facts) == []


def test_i_am_capitalized_name_still_extracts():
    facts = extract_durable_facts("I am Gunjan and I run a design agency.")
    assert "Gunjan" in _names(facts)


def test_my_name_is_still_extracts():
    facts = extract_durable_facts("my name is Rahul")
    assert "Rahul" in _names(facts)


def test_hindi_mera_naam_still_extracts():
    facts = extract_durable_facts("mera naam Gunjan hai")
    names = _names(facts)
    assert any("Gunjan" in n for n in names)
