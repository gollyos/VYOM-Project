"""Tests for app/memory/auto_linker.py - the piece that turns the
markdown vault into an actual cross-linked knowledge graph instead of
a pile of isolated files (the user's "khudki Wikipedia jaisa Obsidian"
request).
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.memory.auto_linker import (
    MAX_AUTO_LINKS_PER_MEMORY,
    find_link_candidates,
    shares_a_real_subject,
)
from app.memory.schemas import MemoryEntry, MemoryProvenance, MemoryType


def _memory(title: str, entities: list[str] | None = None, **overrides) -> MemoryEntry:
    defaults = dict(
        type=MemoryType.SEMANTIC,
        title=title,
        content=title,
        summary=title,
        entities=entities or [],
        provenance=[MemoryProvenance(type="user_statement", reference="test")],
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return MemoryEntry(**defaults)


def test_shared_entity_links_two_memories():
    a = _memory("Client wants a new website", entities=["Luxora Designs"])
    b = _memory("Invoice sent for the redesign", entities=["Luxora Designs"])
    assert shares_a_real_subject(a, b) is True


def test_no_shared_entity_and_no_title_overlap_does_not_link():
    a = _memory("Client wants a new website", entities=["Luxora Designs"])
    b = _memory("Weather forecast for tomorrow", entities=[])
    assert shares_a_real_subject(a, b) is False


def test_a_single_shared_title_word_is_not_enough():
    """One shared substantive word is too weak a signal on its own -
    the threshold requires at least 2 to avoid spurious links."""
    a = _memory("VYOM completed the deployment")
    b = _memory("VYOM said good morning")
    assert shares_a_real_subject(a, b) is False


def test_two_shared_title_words_links_without_any_entity():
    a = _memory("Luxora Designs website redesign kickoff")
    b = _memory("Luxora Designs website redesign timeline")
    assert shares_a_real_subject(a, b) is True


def test_shared_stopwords_alone_do_not_link():
    """The exact false-positive this module exists to avoid: two
    memories sharing only grammar words ("and", "is") must not link."""
    a = _memory("This and that is happening today")
    b = _memory("This and something else is also here")
    assert shares_a_real_subject(a, b) is False


def test_a_memory_never_links_to_itself():
    a = _memory("Same memory")
    assert shares_a_real_subject(a, a) is False


def test_find_link_candidates_respects_the_cap():
    subject = _memory("Luxora Designs project status")
    many_related = [
        _memory(f"Luxora Designs project status update {i}", entities=["Luxora Designs"])
        for i in range(20)
    ]
    linked = find_link_candidates(subject, many_related)
    assert len(linked) <= MAX_AUTO_LINKS_PER_MEMORY


def test_find_link_candidates_prefers_most_recently_updated():
    subject = _memory("Luxora Designs project status")
    old = _memory(
        "Luxora Designs project status early note", entities=["Luxora Designs"],
        updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
    )
    recent = _memory(
        "Luxora Designs project status latest note", entities=["Luxora Designs"],
        updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    linked = find_link_candidates(subject, [old, recent], limit=1)
    assert linked == [recent]


def test_find_link_candidates_excludes_unrelated_memories():
    subject = _memory("Luxora Designs project status", entities=["Luxora Designs"])
    unrelated = _memory("Weather forecast for tomorrow")
    linked = find_link_candidates(subject, [unrelated])
    assert linked == []
