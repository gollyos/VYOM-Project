"""Dialectic reasoning pass - the "Honcho-style" upgrade to VYOM's
Curator: instead of only linting existing facts for contradictions
(app/knowledge/service.py's lint()), this actively DERIVES new facts
from the raw conversation transcript that the user never explicitly
asked to be remembered.

Deliberately deterministic/pattern-based, not LLM-based: VYOM's only
reliably-configured provider in this deployment is a free-tier model
without guaranteed tool-calling (see task_runtime's action_engine
notes), so a reasoning pass that REQUIRES a paid model would silently
do nothing for most users. Real, working, keyless pattern extraction
today beats a theoretically-richer LLM pass that may never actually
run. The pattern set is intentionally small and precise (few, high-
confidence signals) rather than broad and noisy - a wrong inferred
preference is worse than no inferred preference.

This is genuinely the same shape as Honcho's "dialectic reasoning":
after conversation turns happen, derive insights about the user
(preferences, recurring topics, habits) that accumulate over time,
distinct from what was explicitly told to memory.remember(). The
difference is HOW the reasoning is done (deterministic patterns here,
an LLM call in Honcho) - the accumulation model is the same.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from app.knowledge.schemas import KnowledgeFact
from app.knowledge.service import KnowledgeService
from app.persistence.conversation_store import ConversationStore, ConversationTurn

# Each pattern captures a subject/predicate/value shape from a raw user
# message. Confidence is intentionally lower than an explicit
# memory.remember() entry (0.5-0.6 here vs 1.0 for explicit) because
# these are INFERRED, not stated - the honest distinction Honcho itself
# draws between "observation" and "conclusion".
_PREFERENCE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bi (?:prefer|like|want)\s+(.{3,80}?)(?:[.!?]|$)", re.I), "prefers"),
    (re.compile(r"\bi (?:hate|dislike|don'?t like)\s+(.{3,80}?)(?:[.!?]|$)", re.I), "dislikes"),
    (re.compile(r"\balways\s+(.{3,80}?)(?:[.!?]|$)", re.I), "always"),
    (re.compile(r"\bnever\s+(.{3,80}?)(?:[.!?]|$)", re.I), "never"),
]

_MIN_TOPIC_MENTIONS = 3  # a topic must recur this many times to count as a real pattern, not noise
_MIN_WORD_LEN = 4  # skip short/common words when extracting recurring topics


@dataclass
class DialecticFinding:
    subject: str
    predicate: str
    value: str
    confidence: float
    evidence_turn_ids: list[str]


class DialecticReasoner:
    """Runs over recent conversation turns and derives KnowledgeFact
    entries under the PERSONAL domain - the Honcho-style "understanding
    that goes beyond what was explicitly stated"."""

    def __init__(self, conversation_store: ConversationStore, knowledge_service: KnowledgeService) -> None:
        self.conversation_store = conversation_store
        self.knowledge_service = knowledge_service

    async def run(self, *, context_id: str = "desktop:primary", lookback: int = 200) -> list[DialecticFinding]:
        turns = await self.conversation_store.history(context_id, limit=lookback)
        user_turns = [t for t in turns if t.role == "user"]
        findings: list[DialecticFinding] = []
        findings.extend(self._extract_preference_statements(user_turns))
        findings.extend(self._extract_recurring_topics(user_turns))

        for finding in findings:
            await self.knowledge_service.record_fact(KnowledgeFact(
                subject=finding.subject, predicate=finding.predicate, value=finding.value,
                domain="personal", confidence=finding.confidence,
            ))
        return findings

    def _extract_preference_statements(self, user_turns: list[ConversationTurn]) -> list[DialecticFinding]:
        findings: list[DialecticFinding] = []
        for turn in user_turns:
            for pattern, predicate in _PREFERENCE_PATTERNS:
                match = pattern.search(turn.content)
                if not match:
                    continue
                value = match.group(1).strip()
                if len(value) < 3:
                    continue
                findings.append(DialecticFinding(
                    subject="user", predicate=predicate, value=value,
                    confidence=0.55, evidence_turn_ids=[turn.id],
                ))
        return findings

    def _extract_recurring_topics(self, user_turns: list[ConversationTurn]) -> list[DialecticFinding]:
        """A topic (word) the user brings up repeatedly across DISTINCT
        turns is itself a signal worth surfacing - "this user keeps
        asking about X" - even with no single explicit preference
        statement. Requires _MIN_TOPIC_MENTIONS distinct turns, not just
        repeated words within one message, to avoid one verbose message
        looking like a recurring pattern."""
        word_to_turns: dict[str, set[str]] = {}
        for turn in user_turns:
            words = {w.lower().strip(".,!?;:\"'()") for w in turn.content.split() if len(w) >= _MIN_WORD_LEN}
            for word in words:
                if not word.isalpha():
                    continue
                word_to_turns.setdefault(word, set()).add(turn.id)

        findings: list[DialecticFinding] = []
        for word, turn_ids in word_to_turns.items():
            if len(turn_ids) >= _MIN_TOPIC_MENTIONS:
                findings.append(DialecticFinding(
                    subject="user", predicate="frequently discusses", value=word,
                    confidence=0.5, evidence_turn_ids=sorted(turn_ids),
                ))
        return findings
