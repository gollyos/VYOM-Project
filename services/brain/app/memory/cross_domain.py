"""Cross-domain memory mirroring — the fix for VYOM's siloed personal
stores (goals, habits, personal profile, CRM, finance): each domain has
its OWN SQL table (see e.g. app/goals/store.py), but until this module
existed those tables never wrote into the shared MemoryStore, so
`memory_search("fitness goal")` could never surface a habit or CRM
contact even though they are obviously related in a human's life.

This is Karpathy's LLM-wiki cross-reference idea applied ACROSS VYOM's
domain stores instead of only inside app/knowledge/ (which already does
this for researched facts). A domain store calls `mirror()` once after
every save() with a few fields; this module does the rest:
  - writes/updates a MemoryEntry tagged with the domain's
    CognitiveNamespace so a later `memory_search` or `related()` finds
    it regardless of which store originally owned the record
  - stores the domain's own record id in metadata so a hit can be
    resolved back to the authoritative row (this mirror is a search
    index, never the source of truth — the domain table stays that)
  - reconciles on repeat saves (edit a goal twice -> one memory entry,
    updated in place) via a deterministic `mem_id = domain:record_id`
    metadata key, not a fresh entry every time

This does NOT change any domain schema or table. It is purely additive:
existing code that never calls mirror() keeps working exactly as before.
"""
from __future__ import annotations

from .manager import MemoryManager
from .namespaces import CognitiveNamespace
from .schemas import MemoryEntry, MemoryProvenance, MemoryType, ProvenanceType


async def mirror(
    memory: MemoryManager,
    *,
    namespace: CognitiveNamespace,
    domain_store: str,
    record_id: str,
    title: str,
    content: str,
    entities: list[str] | None = None,
    extra_tags: list[str] | None = None,
    importance: float = 0.5,
) -> str:
    """Mirror one domain record (a Goal, Habit, PersonalProfile field,
    CRM contact, Portfolio, ...) into the shared memory store so it is
    findable via memory_search/related() regardless of which domain
    table it actually lives in.

    Idempotent by construction: the memory id is deterministically
    derived from (domain_store, record_id), and MemoryStore.save() is
    an upsert (ON CONFLICT DO UPDATE, with the outgoing version
    snapshotted to memory_history first) — so calling this again for
    the same domain record updates the existing mirror in place rather
    than creating a duplicate. A store should call this after every
    save(), not just on create.
    """
    ns_tag = f"ns:{namespace.value}"
    entry = MemoryEntry(
        id=f"mem_{domain_store}_{record_id}",
        type=MemoryType.SEMANTIC,
        title=title[:240],
        content=content[:40_000],
        summary=content[:500],
        entities=entities or [],
        tags=[ns_tag, namespace.value, f"domain:{domain_store}", *(extra_tags or [])],
        provenance=[MemoryProvenance(
            type=ProvenanceType.AGENT_OBSERVATION,
            reference=f"{domain_store} record {record_id}",
        )],
        importance=importance,
        metadata={"mirror_source": f"{domain_store}:{record_id}", "domain_store": domain_store, "domain_record_id": record_id},
    )
    stored = await memory.remember(entry)
    return stored.id
