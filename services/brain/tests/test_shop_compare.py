from __future__ import annotations

import pytest

from app.execution.action_engine import ActionEngine
from app.runtime.task_classifier import TaskClassifier


# ======================================================================
# Classification: plain "find <product>" must reach shop_compare
# ======================================================================

@pytest.mark.parametrize("utterance", [
    "mere liye blue shoes 12 no find karo",
    "find blue shoes size 12",
    "find blue shoes size 12 for me",
    "find a black jacket",
])
def test_plain_find_product_reaches_shop_compare(utterance):
    """Only the narrow 'find me the best ...' phrase used to trigger
    shop_compare; ordinary 'find <product>' (including the common
    Hinglish '<product> <size> find karo' word order) fell through to
    the general reasoning path instead - a paid model call with no real
    multi-retailer search, for the exact kind of request this workflow
    exists to handle deterministically and for free."""
    assert TaskClassifier().classify(utterance).intent == "shop_compare"


@pytest.mark.parametrize("utterance,expected_intent", [
    ("find qualified companies for outreach", "lead_research"),
    ("find qualified leads in Mumbai", "lead_research"),
    ("find a tool to compare subscriptions", "tool_discovery"),
    ("find me a restaurant nearby", "booking_search"),
    ("find me a hotel in Goa", "booking_search"),
    ("find the files in my project", "fs_search"),
])
def test_broadened_find_trigger_does_not_hijack_other_find_intents(utterance, expected_intent):
    """Broadening shop_compare's trigger to plain 'find' must not steal
    traffic from the other 'find ...'-triggered intents earlier in the
    classifier cascade - each of those requires its own specific noun
    (qualified leads/companies, a tool, a restaurant/hotel, files), none
    of which overlaps with shop_compare's product-noun list."""
    assert TaskClassifier().classify(utterance).intent == expected_intent


# ======================================================================
# Real logged failures: Devanagari product nouns + "chahiye" ("want")
# ======================================================================
#
# Pulled directly from the live task database after a user reported VYOM
# repeatedly failing to actually shop for something they asked for. Every
# one of these fell through to the general conversational path (a generic
# suggestion list, or a blind browser search with nothing to search for)
# instead of the deterministic shop_compare workflow - even after the
# plain-"find" fix above, because the product itself was either written
# in Devanagari script ("शूज") or the request used "chahiye" ("I want/need
# X"), the ordinary Hindi way to want a product, which was not recognised
# as shopping language at all.

@pytest.mark.parametrize("utterance", [
    "मेरे लिए ब्लू कलर के शूज तुम फाइंड कर सकती हो?",
    "pots chahiye blue colour ke hone chahiye",
    "find me a pot",
    "mujhe ek shoes chahiye",
])
def test_real_logged_shopping_requests_now_reach_shop_compare(utterance):
    assert TaskClassifier().classify(utterance).intent == "shop_compare"


@pytest.mark.parametrize("utterance", [
    "mujhe help chahiye",
    "mujhe jawab chahiye",
    "mujhe thoda time chahiye",
    "mujhe ek achha explanation chahiye is code ka",
])
def test_chahiye_does_not_false_positive_without_a_product_noun(utterance):
    """'chahiye' alone means 'want/need' in any context, not just
    shopping - it must only trigger shop_compare paired with an actual
    product noun, exactly like 'buy'/'find' already require."""
    assert TaskClassifier().classify(utterance).intent != "shop_compare"


# ======================================================================
# _parse_shopping_request: size extraction
# ======================================================================

@pytest.fixture
def engine() -> ActionEngine:
    return ActionEngine.__new__(ActionEngine)


@pytest.mark.parametrize("utterance,expected_size", [
    ("mere liye blue shoes 12 no find karo", "12"),
    ("find blue shoes size 12", "12"),
    ("find blue shoes UK 9", "9"),
    ("find blue shoes US 10", "10"),
    ("find me the best blue running shoes", None),
])
def test_size_is_extracted(engine: ActionEngine, utterance, expected_size):
    """A numeric size ('size 12', '12 no', 'UK 9') used to be silently
    discarded - _parse_shopping_request dropped every bare-digit word
    from the query, including the one number that actually mattered for
    a shoe/clothing search, and nothing told the user their size was
    ignored."""
    _, _, _, size = engine._parse_shopping_request(utterance)
    assert size == expected_size


def test_size_appears_exactly_once_in_the_query(engine: ActionEngine):
    """The size marker word ('size', 'no', 'uk', ...) must not survive
    in the base word list AND be re-appended - that produced a doubled
    'blue shoes size size 12' query sent to the retailer."""
    query, _, _, size = engine._parse_shopping_request("find blue shoes size 12")
    assert size == "12"
    assert query.count("size") == 1
    assert "12" in query


def test_size_marker_removal_is_scoped_to_its_own_match(engine: ActionEngine):
    """Stripping the size marker must remove only the matched span, not
    every occurrence of a short marker word - otherwise 'US Polo' loses
    its own brand name to the same filter that strips 'US' from 'US 10'."""
    query, _, _, size = engine._parse_shopping_request("find me the best US Polo shirt")
    assert size is None
    assert "polo" in query


def test_budget_and_size_both_extracted_together(engine: ActionEngine):
    query, colour, budget, size = engine._parse_shopping_request(
        "find me the best blue shoes size 12 under 3000"
    )
    assert colour == "blue"
    assert budget == 3000
    assert size == "12"
    assert "12" in query
