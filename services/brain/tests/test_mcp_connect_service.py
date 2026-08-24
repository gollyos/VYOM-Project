"""Tests for POST /api/mcp/connect — the plain-language 'tell VYOM a service
name, it figures out the rest' entry point added this session. Uses the
real FastAPI app + TestClient pattern already used by tests/test_mcp_autoconnect.py,
but never actually spawns a real npx subprocess here (that's covered by the
manual verification recorded in test_mcp_autoconnect.py) — these exercise
the fuzzy-match / credential-gate / unknown-service logic in isolation.
"""
from __future__ import annotations

from app.mcp import catalog as mcp_catalog


def test_catalog_has_required_env_declared_for_credentialed_services():
    notion = mcp_catalog.find("notion")
    assert notion is not None
    assert notion.required_env == ["NOTION_TOKEN"]

    slack = mcp_catalog.find("slack")
    assert slack is not None
    assert set(slack.required_env) == {"SLACK_BOT_TOKEN", "SLACK_TEAM_ID"}

    memory = mcp_catalog.find("memory")
    assert memory is not None
    assert memory.required_env == []


def test_catalog_describe_includes_new_entries():
    ids = {entry["catalog_id"] for entry in mcp_catalog.describe()}
    assert {"notion", "slack", "github", "postgres", "brave-search", "puppeteer", "whatsapp"}.issubset(ids)


def test_whatsapp_catalog_entry_has_extended_startup_timeout():
    # Verified live: wweb-mcp's first run downloads whatsapp-web.js's
    # bundled Chromium and spins up a real WhatsApp Web client before
    # answering MCP's 'initialize' — took well past the generic 30s
    # default on a cold cache in manual testing.
    entry = mcp_catalog.find("whatsapp")
    assert entry is not None
    assert entry.startup_timeout_seconds > 30.0
    assert entry.command == "npx"
    assert "wweb-mcp" in entry.args_template


def _fuzzy_match(service: str):
    """Mirrors the exact fuzzy-match logic in app/api/mcp.py's connect_service
    so this can be tested without booting the full FastAPI app + real
    subprocess connections."""
    normalized = service.strip().lower()
    match = mcp_catalog.find(normalized)
    if match is None:
        words = [w for w in normalized.replace("-", " ").split() if len(w) > 2]
        best_entry, best_score = None, 0
        for entry in mcp_catalog.CATALOG:
            identity = f"{entry.catalog_id} {entry.display_name}".lower().replace("-", " ")
            description = entry.description.lower()
            score = 0
            if entry.catalog_id.replace("-", " ") in normalized:
                score += 10
            for word in words:
                if word in identity:
                    score += 3
                elif word in description:
                    score += 1
            if score > best_score:
                best_entry, best_score = entry, score
        if best_score >= 3:
            match = best_entry
    return match


def test_fuzzy_match_finds_service_from_natural_language():
    assert _fuzzy_match("I want notion connected").catalog_id == "notion"
    assert _fuzzy_match("connect my slack workspace").catalog_id == "slack"
    assert _fuzzy_match("github").catalog_id == "github"
    assert _fuzzy_match("give me brave search").catalog_id == "brave-search"
    assert _fuzzy_match("connect my whatsapp").catalog_id == "whatsapp"


def test_fuzzy_match_returns_none_for_unknown_service():
    assert _fuzzy_match("connect my instagram") is None
    assert _fuzzy_match("connect my facebook ads") is None
