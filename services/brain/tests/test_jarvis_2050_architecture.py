"""Tests for the 2050 JARVIS autonomous architecture components."""
from __future__ import annotations

import math
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock


# ─── Memory Holographic Relevance ───────────────────────────────────────────

def _make_memory(importance=0.5, confidence=0.7, age_days=0, verified=True):
    """Create a minimal MemoryEntry-like mock."""
    from app.memory.schemas import (
        MemoryEntry, MemoryProvenance, MemoryType,
        ProvenanceType, Sensitivity, VerificationState,
    )
    now = datetime.now(timezone.utc) - timedelta(days=age_days)
    m = MemoryEntry(
        id="test-mem",
        type=MemoryType.SEMANTIC,
        title="Test Memory",
        summary="test summary",
        content="test content",
        sensitivity=Sensitivity.NORMAL,
        provenance=[MemoryProvenance(type=ProvenanceType.USER_STATEMENT)],
        verification_state=VerificationState.VERIFIED if verified else VerificationState.UNVERIFIED,
        importance=importance,
        confidence=confidence,
        created_at=now,
        updated_at=now,
        last_accessed_at=now,
    )
    return m


class TestHolographicRelevance:
    """Verifies the Gaussian + temporal-anchor infinite memory scorer."""

    def test_very_recent_memory_scores_high(self):
        from app.memory.relevance import relevance_score
        m = _make_memory(importance=0.5, age_days=0)
        score, reasons = relevance_score(m, keyword_score=0.8, semantic_score=0.7, relationship_score=0.2)
        assert score > 0.5

    def test_high_importance_old_memory_survives_age(self):
        """Core infinite-memory test: a 2000-day-old important memory must stay surfaceable."""
        from app.memory.relevance import relevance_score
        old_important = _make_memory(importance=0.95, confidence=0.9, age_days=2000)
        fresh_trivial = _make_memory(importance=0.2, confidence=0.4, age_days=1)
        score_old, reasons_old = relevance_score(
            old_important, keyword_score=0.7, semantic_score=0.6, relationship_score=0.1
        )
        score_fresh, _ = relevance_score(
            fresh_trivial, keyword_score=0.6, semantic_score=0.4, relationship_score=0.0
        )
        # High-importance very-old memory must outscore a low-importance fresh one
        assert score_old > score_fresh, (
            f"Old important memory ({score_old:.3f}) should outscore trivial fresh one ({score_fresh:.3f})"
        )
        assert "long-term anchored memory" in reasons_old

    def test_temporal_anchor_label_fires_for_old_important(self):
        from app.memory.relevance import relevance_score
        m = _make_memory(importance=0.9, age_days=365)
        _, reasons = relevance_score(m, keyword_score=0.5, semantic_score=0.5)
        assert "long-term anchored memory" in reasons

    def test_personal_salience_fires_for_high_confidence(self):
        from app.memory.relevance import relevance_score
        m = _make_memory(confidence=0.85, age_days=5)
        _, reasons = relevance_score(m, keyword_score=0.0, semantic_score=0.5)
        assert "high personal salience" in reasons

    def test_unverified_memory_penalised(self):
        from app.memory.relevance import relevance_score
        verified = _make_memory(verified=True, age_days=10)
        unverified = _make_memory(verified=False, age_days=10)
        sv, _ = relevance_score(verified, keyword_score=0.5, semantic_score=0.5)
        su, _ = relevance_score(unverified, keyword_score=0.5, semantic_score=0.5)
        assert sv > su


# ─── CognitiveScaffolder ────────────────────────────────────────────────────

class TestCognitiveScaffolder:

    def test_scaffold_request_returns_enhanced_instruction(self):
        from app.routing.cognitive_scaffolder import CognitiveScaffolder
        scaffolder = CognitiveScaffolder()
        result = scaffolder.scaffold_request(
            "research competitors for my SaaS startup", domain="research", complexity=3
        )
        assert "VYOM" in result.enhanced_instruction
        assert "GROUNDING" in result.enhanced_instruction
        assert result.confidence_boost > 0

    def test_memory_injection_in_scaffold(self):
        from app.routing.cognitive_scaffolder import CognitiveScaffolder
        scaffolder = CognitiveScaffolder()
        result = scaffolder.scaffold_request(
            "open chrome",
            active_memory_context=["User prefers dark mode", "User works on Luxora Designs"],
        )
        assert "Luxora" in result.enhanced_instruction

    def test_reflexion_prompt_contains_error(self):
        from app.routing.cognitive_scaffolder import CognitiveScaffolder
        scaffolder = CognitiveScaffolder()
        prompt = scaffolder.formulate_reflexion_prompt(
            action="list_directory('/nonexistent')",
            error_message="FileNotFoundError: path does not exist",
            attempt=2,
        )
        assert "Attempt 2" in prompt
        assert "FileNotFoundError" in prompt
        assert "Root cause" in prompt or "root cause" in prompt.lower()


# ─── DynamicToolSynthesizer ─────────────────────────────────────────────────

class TestDynamicToolSynthesizer:

    def test_safe_code_passes_validation(self):
        from app.skills.dynamic_tool_synthesizer import DynamicToolSynthesizer
        synth = DynamicToolSynthesizer()
        safe_code = "import math\n\ndef run(n: int) -> float:\n    return math.sqrt(n)\n"
        ok, reason = synth.validate_code_safety(safe_code)
        assert ok, reason

    def test_unsafe_eval_blocked(self):
        from app.skills.dynamic_tool_synthesizer import DynamicToolSynthesizer
        synth = DynamicToolSynthesizer()
        bad_code = "def run(x):\n    return eval(x)\n"
        ok, reason = synth.validate_code_safety(bad_code)
        assert not ok
        assert "eval" in reason.lower() or "disallowed" in reason.lower()

    def test_unsafe_import_blocked(self):
        from app.skills.dynamic_tool_synthesizer import DynamicToolSynthesizer
        synth = DynamicToolSynthesizer()
        bad_code = "import os\ndef run():\n    return os.listdir('.')\n"
        ok, reason = synth.validate_code_safety(bad_code)
        assert not ok

    def test_synthesize_registers_spec(self):
        from app.skills.dynamic_tool_synthesizer import DynamicToolSynthesizer
        synth = DynamicToolSynthesizer()
        spec = synth.synthesize_tool(
            name="square_root",
            description="Computes the square root of a number",
            parameters_schema={"n": {"type": "number"}},
            implementation_code="import math\ndef run(n):\n    return math.sqrt(n)\n",
        )
        assert spec.name == "square_root"
        assert "square_root" in synth.synthesized

    def test_unsafe_tool_raises(self):
        from app.skills.dynamic_tool_synthesizer import DynamicToolSynthesizer
        synth = DynamicToolSynthesizer()
        with pytest.raises(ValueError, match="security policy"):
            synth.synthesize_tool(
                name="bad_tool",
                description="malicious",
                parameters_schema={},
                implementation_code="import subprocess\ndef run():\n    subprocess.call(['rm', '-rf', '/'])\n",
            )


# ─── TaskClassifier agency intent routing ──────────────────────────────────

class TestClassifierAgencyIntents:

    def _classify(self, text: str):
        from app.runtime.task_classifier import TaskClassifier
        return TaskClassifier().classify(text)

    def test_autonomous_agency_pipeline_trigger(self):
        profile = self._classify("client ka full project handle karo aur research bhi karo")
        assert profile.intent == "autonomous_agency_pipeline"

    def test_agency_pipeline_english_trigger(self):
        profile = self._classify("run full agency pipeline for client Acme Corp")
        assert profile.intent == "autonomous_agency_pipeline"

    def test_tool_synthesis_trigger(self):
        profile = self._classify("create a tool that fetches live gold price from API")
        assert profile.intent == "synthesize_tool"

    def test_tool_synthesis_hindi_trigger(self):
        profile = self._classify("bana ek tool jo mujhe weather data de")
        assert profile.intent == "synthesize_tool"

    def test_regular_agency_crm_unaffected(self):
        profile = self._classify("show crm")
        assert profile.intent == "crm_summary"

    def test_regular_lead_research_unaffected(self):
        profile = self._classify("find qualified leads in Bangalore")
        assert profile.intent == "lead_research"
