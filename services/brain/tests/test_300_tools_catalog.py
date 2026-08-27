"""Tests for the 300+ Universal Tool Catalog and Dynamic JIT Matcher."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.api.tools import router as tools_router
from app.tools.catalog_300 import (
    ALL_300_TOOLS,
    count_tools,
    get_all_tool_definitions,
    get_tools_by_category,
    search_tools,
)
from app.tools.dynamic_matcher import DynamicToolMatcher, get_tool_matcher


def test_tool_catalog_contains_over_300_tools():
    """Verify that the tool catalog contains at least 300 curated tools."""
    tools = get_all_tool_definitions()
    assert len(tools) >= 300, f"Expected at least 300 tools, found {len(tools)}"


def test_tool_catalog_all_10_domains_populated():
    """Verify that all 10 domain categories are populated."""
    counts = count_tools()
    expected_categories = [
        "dev",
        "productivity",
        "communication",
        "research",
        "media",
        "system",
        "business",
        "data",
        "security",
        "automation",
    ]
    for category in expected_categories:
        assert category in counts, f"Missing category {category}"
        assert counts[category] >= 15, f"Category {category} has too few tools: {counts[category]}"


def test_every_tool_definition_valid_schema():
    """Ensure every tool has unique ID, non-empty name, description, category, and tags."""
    seen_ids = set()
    for tool in ALL_300_TOOLS:
        assert tool.id, "Tool ID cannot be empty"
        assert tool.id not in seen_ids, f"Duplicate tool ID found: {tool.id}"
        seen_ids.add(tool.id)

        assert tool.name, f"Tool {tool.id} has empty name"
        assert tool.description, f"Tool {tool.id} has empty description"
        assert tool.category, f"Tool {tool.id} has empty category"
        assert isinstance(tool.tags, list), f"Tool {tool.id} tags must be list"


def test_dynamic_matcher_lexical_and_tag_search():
    """Test dynamic matching against diverse user prompt keywords."""
    matcher = get_tool_matcher()

    # Dev/Docker query
    dev_results = matcher.match_for_prompt("Docker containers logs check karo", max_tools=5)
    assert any("docker" in t.id for t in dev_results)

    # WhatsApp messaging query
    comm_results = matcher.match_for_prompt("WhatsApp pe message bhejo Gunjan ko", max_tools=5)
    assert any("whatsapp" in t.id for t in comm_results)

    # Billing / GST / Invoice query
    biz_results = matcher.match_for_prompt("GST invoice calculate and generate PDF", max_tools=5)
    assert any("invoice" in t.id or "gst" in t.id or "tax" in t.id for t in biz_results)

    # System / Battery query
    sys_results = matcher.match_for_prompt("Laptop battery percentage check karo", max_tools=5)
    assert any("battery" in t.id for t in sys_results)

    # n8n Automation query
    auto_results = matcher.match_for_prompt("Trigger n8n webhook workflow", max_tools=5)
    assert any("n8n" in t.id for t in auto_results)


def test_tools_api_endpoints():
    """Test FastAPI /api/tools/catalog and search endpoints."""
    app = FastAPI()
    app.include_router(tools_router)
    client = TestClient(app)

    # 1. /api/tools/catalog
    resp = client.get("/api/tools/catalog")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 300
    assert "counts" in data
    assert data["counts"]["total"] >= 300

    # 2. /api/tools/categories
    cat_resp = client.get("/api/tools/categories")
    assert cat_resp.status_code == 200
    cat_data = cat_resp.json()
    assert "categories" in cat_data
    assert cat_data["categories"]["total"] >= 300

    # 3. /api/tools/search
    search_resp = client.get("/api/tools/search?q=invoice")
    assert search_resp.status_code == 200
    search_data = search_resp.json()
    assert search_data["count"] > 0
    assert any("invoice" in item["id"] for item in search_data["results"])
