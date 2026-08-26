"""Automatic cross-linking between memories - the piece that turns the
markdown vault (app/memory/vault.py) from a pile of isolated files into
an actual Zettelkasten/Obsidian-style knowledge graph: memories that
share a real subject (an entity, or substantial title-token overlap)
get a genuine RELATED_TO relationship recorded, which the vault then
renders as [[wikilinks]].

Deliberately conservative: this is NOT semantic/embedding similarity
(that already exists for search, in retrieval.py) - auto-linking only
connects memories with a CONCRETE shared signal (the same named entity,
or enough shared title words to be about the same thing), because a
false link in a permanent knowledge graph is worse than a missing one.
"""
from __future__ import annotations

import re

from .schemas import MemoryEntry

#: Same stopword rationale as retrieval.py's MemoryRetriever - common
#: words must never count as the "shared subject" that justifies a
#: permanent link between two memories.
_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "has", "have", "he", "her", "his", "i", "in", "is", "it", "its",
    "of", "on", "or", "our", "s", "she", "that", "the", "their",
    "there", "these", "this", "those", "to", "was", "we", "were",
    "will", "with", "you", "your", "completed", "failed",
    "hai", "hain", "ka", "ke", "ki", "ko", "me", "mein", "se", "hi",
    "bhi", "aur", "ye", "yeh", "wo", "woh", "tum", "tumhara", "mera",
    "meri", "है", "हैं", "का", "के", "की", "को", "में", "से", "और",
    "भी", "यह", "वह", "तुम", "मेरा", "मेरी",
})

#: Minimum shared title tokens (after stopword removal) before two
#: memories are considered "about the same thing" on title grounds
#: alone. Kept high because titles are short - even 2 shared
#: substantive words is a real signal at this length.
_MIN_TITLE_TOKEN_OVERLAP = 2

#: Hard cap on how many auto-links one memory accumulates. Without a
#: cap, a very common entity (this user's own name) would connect
#: every memory to every other memory, defeating the point of a
#: knowledge graph (everything linked to everything is the same as
#: nothing being linked).
MAX_AUTO_LINKS_PER_MEMORY = 8


def _title_tokens(title: str) -> set[str]:
    return set(re.findall(r"\w+", title.lower(), re.UNICODE)) - _STOPWORDS


def shares_a_real_subject(a: MemoryEntry, b: MemoryEntry) -> bool:
    """True when two memories are concretely about the same thing -
    a shared named entity, or enough shared substantive title words.
    Pure function, no I/O, so it is trivially unit-testable."""
    if a.id == b.id:
        return False
    entities_a = {e.strip().lower() for e in a.entities if e.strip()}
    entities_b = {e.strip().lower() for e in b.entities if e.strip()}
    if entities_a and entities_b and (entities_a & entities_b):
        return True
    overlap = _title_tokens(a.title) & _title_tokens(b.title)
    return len(overlap) >= _MIN_TITLE_TOKEN_OVERLAP


def find_link_candidates(
    memory: MemoryEntry, others: list[MemoryEntry], *, limit: int = MAX_AUTO_LINKS_PER_MEMORY,
) -> list[MemoryEntry]:
    """Which of `others` should get a RELATED_TO link with `memory`,
    most-recently-updated first (recent context is more likely to
    still be relevant than something from years ago), capped at
    `limit` so one common entity cannot connect everything to
    everything."""
    candidates = [other for other in others if shares_a_real_subject(memory, other)]
    candidates.sort(key=lambda item: item.updated_at, reverse=True)
    return candidates[:limit]
