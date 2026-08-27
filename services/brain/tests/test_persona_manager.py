"""Tests for the VYOM Persona Subsystem (Girlfriend / Companion & JARVIS Assistant)."""

import pytest
from app.persona.manager import PersonaManager
from app.persona.schemas import PersonaId, PERSONA_CATALOG


def test_persona_catalog_has_both_personas():
    assert PersonaId.COMPANION_GIRLFRIEND in PERSONA_CATALOG
    assert PersonaId.ASSISTANT_JARVIS in PERSONA_CATALOG

    gf = PERSONA_CATALOG[PersonaId.COMPANION_GIRLFRIEND]
    assert gf.care_mode is True
    assert "MAYA" in gf.system_instruction or "companion" in gf.system_instruction.lower()
    assert gf.voice == "hi-IN-SwaraNeural"

    jarvis = PERSONA_CATALOG[PersonaId.ASSISTANT_JARVIS]
    assert jarvis.care_mode is False
    assert "JARVIS" in jarvis.system_instruction or "Chief of Staff" in jarvis.system_instruction
    assert jarvis.voice == "hi-IN-MadhurNeural"


def test_persona_manager_switching(tmp_path):
    state_file = tmp_path / "persona_state.json"
    mgr = PersonaManager(state_path=state_file)

    # Initial default is Assistant JARVIS
    assert mgr.active_id == PersonaId.ASSISTANT_JARVIS

    # Switch to Companion Girlfriend
    p1 = mgr.set_persona(PersonaId.COMPANION_GIRLFRIEND)
    assert p1.id == PersonaId.COMPANION_GIRLFRIEND
    assert mgr.active_id == PersonaId.COMPANION_GIRLFRIEND
    assert p1.care_mode is True

    # Persists to disk
    mgr2 = PersonaManager(state_path=state_file)
    assert mgr2.active_id == PersonaId.COMPANION_GIRLFRIEND

    # Switch back to Assistant JARVIS
    p2 = mgr.set_persona(PersonaId.ASSISTANT_JARVIS)
    assert p2.id == PersonaId.ASSISTANT_JARVIS
    assert mgr.active_id == PersonaId.ASSISTANT_JARVIS


def test_natural_language_switch_detection(tmp_path):
    mgr = PersonaManager(state_path=tmp_path / "test.json")

    assert mgr.detect_switch_request("Switch to girlfriend mode please") == PersonaId.COMPANION_GIRLFRIEND
    assert mgr.detect_switch_request("Maya ban jao") == PersonaId.COMPANION_GIRLFRIEND
    assert mgr.detect_switch_request("companion mode on karo") == PersonaId.COMPANION_GIRLFRIEND
    assert mgr.detect_switch_request("be my girlfriend") == PersonaId.COMPANION_GIRLFRIEND

    assert mgr.detect_switch_request("switch to jarvis") == PersonaId.ASSISTANT_JARVIS
    assert mgr.detect_switch_request("assistant mode activate karo") == PersonaId.ASSISTANT_JARVIS
    assert mgr.detect_switch_request("jarvis ban jao") == PersonaId.ASSISTANT_JARVIS
    assert mgr.detect_switch_request("professional mode chalao") == PersonaId.ASSISTANT_JARVIS

    assert mgr.detect_switch_request("What is the weather today in Mumbai?") is None
