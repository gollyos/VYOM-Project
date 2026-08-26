"""One-off (idempotent) backfill: create RELATED_TO relationships and
re-render vault [[wikilinks]] for memories that existed BEFORE
auto-linking was added (app/memory/auto_linker.py). Safe to re-run -
MemoryManager._auto_link already skips relationships that already
exist, so running this twice just does nothing extra the second time.

Usage (from services/brain):
    python -m app.memory.backfill_auto_links [--limit N] [--dry-run]
"""
from __future__ import annotations

import argparse
import asyncio

from app.core.config import Settings
from app.memory.embeddings import CachedEmbeddingProvider, LocalHashEmbeddingProvider
from app.memory.manager import MemoryManager
from app.memory.retrieval import MemoryRetriever
from app.memory.schemas import MemoryQuery
from app.memory.store import MemoryStore
from app.memory.vault import MemoryVault
from app.persistence.database import Database


async def backfill(*, limit: int | None = None, dry_run: bool = False) -> dict:
    settings = Settings()
    database = Database(settings.database_path)
    await database.connect()
    try:
        data_dir = settings.database_path.parent
        vault = MemoryVault(data_dir / "memory-vault")
        store = MemoryStore(database, vault=vault)
        embeddings = CachedEmbeddingProvider(database, LocalHashEmbeddingProvider())
        retriever = MemoryRetriever(store, embeddings)
        manager = MemoryManager(store, retriever)

        all_memories = await store.list(limit=limit or 100_000)
        linked_count = 0
        for memory in all_memories:
            if dry_run:
                candidates = await retriever.search(MemoryQuery(text=memory.title, limit=40))
                others = [hit.memory for hit in candidates if hit.memory.id != memory.id]
                from app.memory.auto_linker import find_link_candidates
                found = find_link_candidates(memory, others)
                linked_count += len(found)
            else:
                await manager._auto_link(memory)
                existing = await store.relationships(memory.id)
                linked_count += len(existing)
        return {"memories_processed": len(all_memories), "relationships_touched": linked_count, "dry_run": dry_run}
    finally:
        await database.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None, help="Cap how many memories to process")
    parser.add_argument("--dry-run", action="store_true", help="Report counts without writing anything")
    args = parser.parse_args()
    result = asyncio.run(backfill(limit=args.limit, dry_run=args.dry_run))
    print(result)


if __name__ == "__main__":
    main()
