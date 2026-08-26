from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/search")
async def search_knowledge(q: str, request: Request, limit: int = 20, domain: str | None = None) -> dict[str, Any]:
    """Recall facts VYOM already knows about `q` - the 'khud ka
    Wikipedia' lookup. Never triggers a browse/research pass itself;
    it just answers from what is already persisted (see
    KnowledgeService.recall). Pass `domain` (e.g. 'research', 'coding')
    to scope the recall to ONE agent's own wiki; omit it to search
    across all wikis globally."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")
    result = await request.app.state.knowledge_service.recall(
        q, limit=min(max(limit, 1), 100), domain=domain,
    )
    return result.model_dump(mode="json")


@router.get("/namespaces")
async def list_namespaces(request: Request) -> dict[str, Any]:
    """The distinct per-agent knowledge bases ('wikis') that currently
    hold facts, e.g. ['general', 'research']. Each is indepenently
    updated by its own agent; this lets the UI show a client which
    dedicated knowledge bases actually exist."""
    store = request.app.state.knowledge_service.store
    namespaces = await store.namespaces()
    return {"namespaces": namespaces, "count": len(namespaces)}


@router.get("/related")
async def related_facts(subject: str, request: Request, domain: str | None = None, limit: int = 20) -> dict[str, Any]:
    """Karpathy-style cross-reference: facts linked to `subject` by a
    shared subject token or the same predicate (the structured analogue of
    a [[wikilink]]). Pass `domain` to scope to one agent's wiki."""
    if not subject.strip():
        raise HTTPException(status_code=400, detail="subject is required")
    facts = await request.app.state.knowledge_service.related(
        subject, domain=domain, limit=min(max(limit, 1), 100),
    )
    return {"subject": subject, "domain": domain, "related": [f.model_dump(mode="json") for f in facts]}


@router.get("/lint")
async def lint_wiki(request: Request, domain: str | None = None, stale_days: int | None = None,
                    low_confidence: float = 0.4) -> dict[str, Any]:
    """Karpathy-style wiki audit/lint. Surfaces what a client should
    review instead of letting weak/conflicting facts harden into truth:
    contradicted facts, stale facts, low-confidence facts, and orphans
    (facts with no cross-reference). Pass `domain` for one agent's wiki,
    or omit to lint all."""
    return await request.app.state.knowledge_service.lint(
        domain=domain, stale_days=stale_days, low_confidence=low_confidence,
    )


@router.get("/audit-vault")
async def audit_vault(request: Request) -> dict[str, Any]:
    """Vault index-truth audit: confirms the on-disk markdown vault
    (the user's Obsidian window into memory) actually mirrors the
    database. Reports orphan vault files (claim a memory the store
    doesn't have) and broken [[wikilinks]] (graph edges to nowhere).
    Complements /api/knowledge/lint, which audits fact-level quality."""
    return await request.app.state.knowledge_service.audit_vault()


@router.get("/{topic}")
async def knowledge_for_topic(topic: str, request: Request, limit: int = 50, domain: str | None = None) -> dict[str, Any]:
    """All known facts on a topic (exact/substring subject match). Pass
    `domain` to scope to one agent's wiki."""
    result = await request.app.state.knowledge_service.recall(
        topic, limit=min(max(limit, 1), 200), domain=domain,
    )
    if not result.facts:
        raise HTTPException(status_code=404, detail=f"No knowledge recorded for '{topic}'")
    return result.model_dump(mode="json")
