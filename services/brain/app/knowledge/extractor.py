from __future__ import annotations

import re

from .schemas import KnowledgeFact

# Deliberately conservative: only sentences that look like factual
# statements ("X is/was/are Y", "X has/had Y") are turned into facts.
# The goal is precision over recall - a wrong fact silently memorized
# forever is worse than a missed one, since the whole point of this
# store is "recall instantly without re-researching".
_PATTERNS = [
    # "X is/was/are/were a/an/the Y"  -> predicate "is"
    (re.compile(r"^(?P<subject>[A-Z][\w \-'.,]{1,80}?)\s+(?:is|was)\s+(?:a|an|the)\s+(?P<value>.{3,300})$"), "is a"),
    (re.compile(r"^(?P<subject>[A-Z][\w \-'.,]{1,80}?)\s+(?:are|were)\s+(?P<value>.{3,300})$"), "are"),
    # "X was created/founded/invented/developed by Y"
    (re.compile(r"^(?P<subject>[A-Z][\w \-'.,]{1,80}?)\s+(?:was|is)\s+(?:created|founded|invented|developed|designed|written)\s+by\s+(?P<value>.{2,200})$", re.IGNORECASE), "created by"),
    # "X was released/founded/established in Y" (dates/years/places)
    (re.compile(r"^(?P<subject>[A-Z][\w \-'.,]{1,80}?)\s+(?:was|is)\s+(?:released|founded|established|launched)\s+in\s+(?P<value>.{2,100})$", re.IGNORECASE), "founded in"),
    # "X has/had Y"
    (re.compile(r"^(?P<subject>[A-Z][\w \-'.,]{1,80}?)\s+(?:has|had)\s+(?P<value>.{3,300})$"), "has"),
]

_MAX_SENTENCE_LEN = 400
_MIN_SENTENCE_LEN = 20


def _split_sentences(text: str) -> list[str]:
    # Cheap stdlib sentence split; good enough for extracted article
    # text which is already clean prose from DefuddleExtractor.
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if _MIN_SENTENCE_LEN <= len(p.strip()) <= _MAX_SENTENCE_LEN]


class FactExtractor:
    """Turns clean article text (from DefuddleExtractor) into candidate
    KnowledgeFact rows. Never fabricates: every candidate must match a
    real sentence taken verbatim from the source content, and every
    fact carries the real source_url it came from."""

    def extract(self, *, text: str, source_url: str | None, source_title: str | None = None,
                subject_hint: str | None = None, task_id: str | None = None,
                confidence: float = 0.55, max_facts: int = 8) -> list[KnowledgeFact]:
        facts: list[KnowledgeFact] = []
        seen: set[tuple[str, str]] = set()
        for sentence in _split_sentences(text):
            for pattern, predicate in _PATTERNS:
                match = pattern.match(sentence)
                if not match:
                    continue
                subject = match.group("subject").strip(" ,.")
                value = match.group("value").strip(" ,.")
                if not subject or not value:
                    continue
                # A subject_hint (e.g. the research goal/topic) lets a
                # caller keep only facts about the thing actually being
                # researched, filtering out incidental sentences about
                # unrelated entities on the same page.
                if subject_hint and subject_hint.lower() not in subject.lower() and subject.lower() not in subject_hint.lower():
                    continue
                key = (subject.lower(), predicate)
                if key in seen:
                    continue
                seen.add(key)
                facts.append(KnowledgeFact(
                    subject=subject,
                    predicate=predicate,
                    value=value[:1000],
                    source_url=source_url,
                    source_title=source_title,
                    confidence=confidence,
                    task_id=task_id,
                ))
                break
            if len(facts) >= max_facts:
                break
        return facts
