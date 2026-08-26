"""Vault index-truth audit.

VYOM's Curator (app/adaptive/curator.py) already lints knowledge-base
FACTS for contradictions, staleness, low confidence, and orphans
(see app/knowledge/service.py's lint). What it never checked is whether
the on-disk Obsidian-style markdown VAULT actually mirrors the database
- i.e. the "knowledge graph window" the user opens in Obsidian is in
sync with the authoritative store. This module closes that gap:

  1. Orphan files: .md files under the vault root whose embedded memory
     id is NOT in the database (the vault claims a memory the store
     doesn't have - a dangling window).
  2. Broken wikilinks: every [[link]] inside a vault file whose target
     memory id is NOT in the database (cross-references that resolve to
     nothing - the graph has edges to nowhere).

HIGHLY_SENSITIVE memories are intentionally NEVER mirrored to the
vault (see MemoryVault.write), so they are correctly excluded from the
count comparison; only orphan files and broken wikilinks are treated as
real integrity problems.
"""

from __future__ import annotations

import re
from pathlib import Path

from .store import MemoryStore
from .vault import MemoryVault

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _id_from_vault_filename(filename: str) -> str:
    """A vault file is named '{slug}--{memory_id}.md'. The memory id is
    the portion after the LAST '--' (slug has had its own '--' collapsed
    to '-', so the final '--' is the separator MemoryVault inserts)."""
    stem = filename[:-3] if filename.endswith(".md") else filename
    return stem.rsplit("--", 1)[-1]


def _id_from_wikilink(link: str) -> str:
    """A wikilink is '[[{slug}--{memory_id}|title]]' or '[[{slug}--{memory_id}]]'.
    The id is the portion after the last '--'."""
    target = link.strip().split("|", 1)[0].strip()
    return target.rsplit("--", 1)[-1]


async def audit_vault(store: MemoryStore, vault: MemoryVault) -> dict:
    """Run the vault-versus-database consistency audit.

    Returns a dict:
      ok: bool - True when there are no orphan files and no broken links
      db_memory_count: int - memories in the store (informational)
      vault_file_count: int - .md files under vault.root (informational;
          lower than db_memory_count is EXPECTED because HIGHLY_SENSITIVE
          memories are never mirrored)
      orphan_files: list[str] - vault filenames with no matching DB memory
      broken_links: list[dict] - {link, file} wikilinks resolving nowhere
    """
    # 1. Gather all memory ids from the store.
    memories = await store.list(limit=1_000_000)
    db_ids: set[str] = {m.id for m in memories}
    db_memory_count = len(db_ids)

    vault_root = vault.root
    if vault_root is None or not Path(vault_root).exists():
        return {
            "ok": True,
            "db_memory_count": db_memory_count,
            "vault_file_count": 0,
            "orphan_files": [],
            "broken_links": [],
        }

    # 2. Walk the vault for every .md file.
    vault_files: list[Path] = list(Path(vault_root).rglob("*.md"))
    vault_file_count = len(vault_files)

    # 3. Orphan files: file exists but its embedded id is not in the DB.
    orphan_files: list[str] = []
    for path in vault_files:
        mid = _id_from_vault_filename(path.name)
        if mid and mid not in db_ids:
            orphan_files.append(path.name)

    # 4. Broken wikilinks: a [[link]] target id that is not in the DB.
    broken_links: list[dict] = []
    for path in vault_files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for m in _WIKILINK_RE.finditer(text):
            target_id = _id_from_wikilink(m.group(1))
            if target_id and target_id not in db_ids:
                broken_links.append({"link": m.group(1).strip(), "file": str(path)})

    ok = len(orphan_files) == 0 and len(broken_links) == 0
    return {
        "ok": ok,
        "db_memory_count": db_memory_count,
        "vault_file_count": vault_file_count,
        "orphan_files": orphan_files,
        "broken_links": broken_links,
    }
