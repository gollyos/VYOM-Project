from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

from app.persistence.database import Database

from .schemas import KnowledgeFact, utc_now


def _normalize_subject(subject: str) -> str:
    """Lowercased, whitespace-collapsed subject key used for fast exact
    and prefix lookups in the structured table. Semantic/keyword recall
    on top of this still goes through MemoryStore.search_fts +
    embeddings - this key only makes 'give me everything about X'
    cheap and exact."""
    return re.sub(r"\s+", " ", subject.strip().lower())


#: Common short words that pass the `len(t) > 2` token filter below but
#: carry no real subject signal - counting them meant a query like
#: "Gunjan's preferences AND business details" LIKE-matched any subject
#: merely CONTAINING "and" as a substring (e.g. "formation and evolution
#: of the Solar System"), surfacing completely unrelated stored facts.
#: A real production bug: this is what made VYOM answer a Hindi
#: personal-memory question with unrelated old Solar System research.
_SUBJECT_SEARCH_STOPWORDS = frozenset({
    "and", "the", "for", "are", "was", "were", "has", "have", "you",
    "your", "its", "his", "her", "our", "not", "but", "with", "from",
})


class KnowledgeStore:
    """Structured fact storage layered on the EXISTING Database/migration
    pattern - a new `knowledge_facts` table (added via a real
    Migration, see app/migrations/manager.py) that holds the
    subject/predicate/value/source/confidence/timestamps row-level
    record, PLUS a mirrored MemoryEntry in the 'knowledge' memory
    namespace so every fact is reachable through the existing FTS5 +
    embedding MemoryRetriever without a second search engine.

    This is intentionally NOT a replacement for MemoryStore: it is a
    thin structured index over the same facts, addressable by exact
    subject the way a wiki infobox is addressable by title.
    """

    def __init__(self, database: Database):
        self.database = database

    async def save(self, fact: KnowledgeFact) -> KnowledgeFact:
        connection = self.database.require_connection()
        subject_key = _normalize_subject(fact.subject)
        payload = json.dumps(fact.model_dump(mode="json"), separators=(",", ":"))
        await connection.execute(
            """
            INSERT INTO knowledge_facts(
                id, subject, subject_key, predicate, value, source_url, source_title,
                confidence, first_learned_at, last_confirmed_at, confirmations,
                task_id, memory_id, domain, contradicted, contradiction_count, fact_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                subject=excluded.subject, subject_key=excluded.subject_key,
                predicate=excluded.predicate, value=excluded.value,
                source_url=excluded.source_url, source_title=excluded.source_title,
                confidence=excluded.confidence, last_confirmed_at=excluded.last_confirmed_at,
                confirmations=excluded.confirmations, memory_id=excluded.memory_id,
                domain=excluded.domain, contradicted=excluded.contradicted,
                contradiction_count=excluded.contradiction_count, fact_json=excluded.fact_json
            """,
            (
                fact.id, fact.subject, subject_key, fact.predicate, fact.value,
                fact.source_url, fact.source_title, fact.confidence,
                fact.first_learned_at.isoformat(), fact.last_confirmed_at.isoformat(),
                fact.confirmations, fact.task_id, fact.memory_id, fact.domain,
                fact.contradicted, fact.contradiction_count, payload,
            ),
        )
        await connection.commit()
        return fact

    async def find_existing(self, subject: str, predicate: str, *, domain: str = "general") -> KnowledgeFact | None:
        """The (subject, predicate, domain) triple that record_fact() re-
        confirms instead of duplicating. Scoped per-domain so the SAME
        fact can exist independently in two agents' wikis without one
        overwriting/conflicting with the other."""
        connection = self.database.require_connection()
        cursor = await connection.execute(
            "SELECT fact_json FROM knowledge_facts WHERE domain = ? AND subject_key = ? AND predicate = ? LIMIT 1",
            (domain, _normalize_subject(subject), predicate),
        )
        row = await cursor.fetchone()
        return KnowledgeFact.model_validate_json(row["fact_json"]) if row else None

    async def by_subject(self, subject: str, limit: int = 50, *, domain: str | None = None) -> list[KnowledgeFact]:
        """Exact-subject lookup - the infobox path. Fast, no search
        ranking involved. When `domain` is given, restrict to that
        agent's wiki; otherwise search across all domains (global)."""
        connection = self.database.require_connection()
        key = _normalize_subject(subject)
        if domain is not None:
            cursor = await connection.execute(
                "SELECT fact_json FROM knowledge_facts WHERE domain = ? AND subject_key = ? "
                "ORDER BY last_confirmed_at DESC LIMIT ?",
                (domain, key, limit),
            )
        else:
            cursor = await connection.execute(
                "SELECT fact_json FROM knowledge_facts WHERE subject_key = ? "
                "ORDER BY last_confirmed_at DESC LIMIT ?",
                (key, limit),
            )
        rows = await cursor.fetchall()
        if rows:
            return [KnowledgeFact.model_validate_json(row["fact_json"]) for row in rows]
        # Fall back to a substring match ("python" should surface facts
        # stored under "python programming language").
        if domain is not None:
            cursor = await connection.execute(
                "SELECT fact_json FROM knowledge_facts WHERE domain = ? AND subject_key LIKE ? "
                "ORDER BY last_confirmed_at DESC LIMIT ?",
                (domain, f"%{key}%", limit),
            )
        else:
            cursor = await connection.execute(
                "SELECT fact_json FROM knowledge_facts WHERE subject_key LIKE ? "
                "ORDER BY last_confirmed_at DESC LIMIT ?",
                (f"%{key}%", limit),
            )
        return [KnowledgeFact.model_validate_json(row["fact_json"]) for row in await cursor.fetchall()]

    async def search_subjects(self, text: str, limit: int = 20, *, domain: str | None = None) -> list[str]:
        """Distinct subjects whose key contains any token of `text` -
        used to resolve a loose query ('who made python') to a known
        subject before falling back to full memory search. When `domain`
        is given, restrict to that agent's wiki."""
        connection = self.database.require_connection()
        tokens = [
            t for t in re.findall(r"[a-z0-9]+", text.lower())
            if len(t) > 2 and t not in _SUBJECT_SEARCH_STOPWORDS
        ]
        if not tokens:
            return []
        clauses = " OR ".join("subject_key LIKE ?" for _ in tokens)
        if domain is not None:
            cursor = await connection.execute(
                f"SELECT DISTINCT subject FROM knowledge_facts WHERE domain = ? AND ({clauses}) "
                f"ORDER BY last_confirmed_at DESC LIMIT ?",
                (domain, *[f"%{token}%" for token in tokens], limit),
            )
        else:
            cursor = await connection.execute(
                f"SELECT DISTINCT subject FROM knowledge_facts WHERE {clauses} "
                f"ORDER BY last_confirmed_at DESC LIMIT ?",
                (*[f"%{token}%" for token in tokens], limit),
            )
        return [row["subject"] for row in await cursor.fetchall()]

    async def namespaces(self) -> list[str]:
        """Distinct agent domains ('wikis') that currently hold facts,
        e.g. ['general', 'research', 'coding']. Used by the UI to show a
        client which per-agent knowledge bases actually exist."""
        connection = self.database.require_connection()
        cursor = await connection.execute("SELECT DISTINCT domain FROM knowledge_facts ORDER BY domain")
        return [row["domain"] for row in await cursor.fetchall()]

    async def facts_in_domain(self, domain: str, *, limit: int = 500) -> list[KnowledgeFact]:
        """All facts in one agent's wiki (bounded). Feeds the wiki lint /
        audit (orphans, contradictions, stale, low-confidence) and the
        cross-reference (related) view."""
        connection = self.database.require_connection()
        cursor = await connection.execute(
            "SELECT fact_json FROM knowledge_facts WHERE domain = ? "
            "ORDER BY last_confirmed_at DESC LIMIT ?",
            (domain, limit),
        )
        return [KnowledgeFact.model_validate_json(row["fact_json"]) for row in await cursor.fetchall()]

    async def related(self, subject: str, domain: str | None = None, *, limit: int = 20) -> list[KnowledgeFact]:
        """Karpathy-style cross-reference: facts in the same 'wiki' that
        are related to `subject` because they share a subject token or the
        same predicate (the structured analogue of a [[wikilink]]). Lets
        the KB compound knowledge into a connected graph instead of
        isolated rows."""
        key = _normalize_subject(subject)
        tokens = [t for t in re.findall(r"[a-z0-9]+", key) if len(t) > 2]
        connection = self.database.require_connection()
        clauses: list[str] = []
        params: list[object] = []
        if domain is not None:
            clauses.append("domain = ?")
            params.append(domain)
        if tokens:
            clauses.append("(" + " OR ".join("subject_key LIKE ?" for _ in tokens) + ")")
            params.extend(f"%{token}%" for token in tokens)
        if not clauses:
            return []
        cursor = await connection.execute(
            f"SELECT fact_json FROM knowledge_facts WHERE {' AND '.join(clauses)} "
            "AND subject_key != ? ORDER BY last_confirmed_at DESC LIMIT ?",
            (*params, key, limit),
        )
        return [KnowledgeFact.model_validate_json(row["fact_json"]) for row in await cursor.fetchall()]

    async def confirm(self, fact: KnowledgeFact, *, source_url: str | None = None,
                       confidence: float | None = None) -> KnowledgeFact:
        """Re-seeing a fact: bump last_confirmed_at/confirmations rather
        than treating the moment of writing as the moment of truth
        forever. This is the mechanism that keeps a still-correct old
        fact from being judged stale just because nobody re-read it."""
        fact.last_confirmed_at = utc_now()
        fact.confirmations += 1
        if confidence is not None:
            fact.confidence = max(fact.confidence, confidence)
        if source_url:
            fact.source_url = source_url
        return await self.save(fact)

    @staticmethod
    def is_stale(fact: KnowledgeFact, max_age_days: int) -> bool:
        age = datetime.now(timezone.utc) - fact.last_confirmed_at
        return age > timedelta(days=max_age_days)

    async def count(self) -> int:
        connection = self.database.require_connection()
        cursor = await connection.execute("SELECT COUNT(*) AS total FROM knowledge_facts")
        row = await cursor.fetchone()
        return int(row["total"])
