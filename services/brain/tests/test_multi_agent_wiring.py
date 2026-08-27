"""Phase 13 - the MultiAgentOrchestrator is wired into the command path.

Covers the pieces that had no coverage before and were the actual bugs:
  - registry.seed() now reads `tools` (the hard run-time scope) and
    per-seed `budget` from config/agents.yaml
  - the role agents (ceo/researcher/.../seo/security) are seeded with
    scoped tool lists
  - orchestrator.should_orchestrate() only fires for a genuinely
    multi-domain goal
  - _sanitize_gemini_schema() strips the JSON-Schema keywords Gemini's
    function-calling validator rejects (an `exclusiveMaximum` in one
    tool's schema was failing the whole generateContent call with 400)
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.agents.multi_agent_orchestrator import MultiAgentOrchestrator
from app.agents.registry import AgentRegistry
from app.providers.google import _sanitize_gemini_schema

_CONFIG = Path(__file__).resolve().parents[3] / "config" / "agents.yaml"


def _seeded_registry(tmp_path: Path) -> AgentRegistry:
    reg = AgentRegistry(tmp_path / "agents")
    reg.load()
    reg.seed(_CONFIG)
    return reg


def test_role_agents_are_seeded_with_scoped_tools(tmp_path: Path) -> None:
    reg = _seeded_registry(tmp_path)
    ids = {a.id for a in reg.list()}
    for role in ("ceo", "researcher", "coder", "analyst", "seo", "security",
                 "desktop-operator", "browser-operator", "qa-verifier"):
        assert role in ids, f"{role} was not seeded"

    researcher = reg.get("researcher")
    assert researcher.tools  # a real scope, not empty
    assert "browser" in researcher.tools
    assert "desktop" not in researcher.tools  # scoped OUT of its job

    ceo = reg.get("ceo")
    # The coordinator holds no world tools - it can only plan/delegate.
    assert ceo.tools == ["mcp.seq-thinking.sequentialthinking"]

    security = reg.get("security")
    assert "telegram" not in security.tools and "email" not in security.tools


def test_role_agents_get_the_shared_budget_ceiling(tmp_path: Path) -> None:
    reg = _seeded_registry(tmp_path)
    coder = reg.get("coder")
    assert coder.budget.max_model_calls == 3
    assert coder.budget.max_tool_calls == 8


def test_should_orchestrate_only_for_multi_domain_goals(tmp_path: Path) -> None:
    orch = MultiAgentOrchestrator(agent_registry=_seeded_registry(tmp_path), agent_runtime=None)

    # single domain -> keep the cheap single planner
    assert orch.should_orchestrate("open Chrome") is False
    assert orch.should_orchestrate("what is the capital of France") is False

    # two distinct role domains -> orchestrate
    assert orch.should_orchestrate(
        "research the latest AI news and write a summary file"
    ) is True
    # explicit team ask -> orchestrate
    assert orch.should_orchestrate("poori team lagao aur ye kaam karo") is True


def test_decompose_covers_seo_and_security() -> None:
    orch = MultiAgentOrchestrator(agent_registry=None, agent_runtime=None)
    seo_plan = orch.decompose("do a keyword and SERP analysis for my landing page")
    assert any(st.agent_id == "seo" for st in seo_plan.sub_tasks)
    sec_plan = orch.decompose("audit the repo for hardcoded secrets and injection risks")
    assert any(st.agent_id == "security" for st in sec_plan.sub_tasks)


@pytest.mark.parametrize(
    "schema, must_be_gone",
    [
        ({"type": "integer", "exclusiveMaximum": 5, "minimum": 0}, ("exclusiveMaximum", "minimum")),
        ({"type": "object", "additionalProperties": False,
          "properties": {"x": {"type": "string", "pattern": "^a", "maxLength": 3}}},
         ("additionalProperties",)),
        ({"$schema": "http://json-schema.org/draft-07/schema#", "type": "object"}, ("$schema",)),
        ({"type": "string", "format": "uuid"}, ("format",)),  # unsupported format dropped
    ],
)
def test_sanitize_gemini_schema_strips_unsupported_keywords(schema, must_be_gone) -> None:
    cleaned = _sanitize_gemini_schema(schema)
    flat = repr(cleaned)
    for key in must_be_gone:
        assert key not in flat
    # a supported shape survives
    assert cleaned.get("type") == schema["type"]


def test_sanitize_keeps_enum_and_nested_properties() -> None:
    schema = {
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": ["a", "b"]},
            "nested": {"type": "object", "properties": {"n": {"type": "integer", "maximum": 9}}},
        },
        "required": ["mode"],
    }
    cleaned = _sanitize_gemini_schema(schema)
    assert cleaned["properties"]["mode"]["enum"] == ["a", "b"]
    assert "maximum" not in repr(cleaned)
    assert cleaned["required"] == ["mode"]


def test_config_agents_yaml_is_valid_and_ids_unique() -> None:
    data = yaml.safe_load(_CONFIG.read_text(encoding="utf-8"))
    ids = [s["id"] for s in data["seeds"]]
    assert len(ids) == len(set(ids)), "duplicate agent id in config/agents.yaml"
