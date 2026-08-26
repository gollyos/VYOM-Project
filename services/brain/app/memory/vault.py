"""Human-readable markdown mirror of the memory store (Obsidian vault).

The database is the authority; the vault is the HUMAN window into it -
openable in Obsidian, greppable, git-versionable, readable in ten years
by tools that no longer exist. Karpathy's "LLM Wiki" framing: the
context window is RAM, a markdown vault is the hard drive.

Layers (Zettelkasten-inspired):
- Raw/    episodic events, working notes, task results (the daily stream)
- Source/ consolidated domain records (projects, clients, people,
          semantic facts, performance)
- Wiki/   distilled knowledge (preferences, decisions, lessons,
          procedures, failures)

Write policy: every store save mirrors here AFTER the database commit,
so the vault can lag a moment but never contradicts the authority.
HIGHLY_SENSITIVE memories are never mirrored to plaintext files - the
database keeps them, the vault does not leak them.
"""
from __future__ import annotations

import re
from pathlib import Path

from .schemas import MemoryEntry, MemoryType, Sensitivity

_LAYER_FOR_TYPE: dict[MemoryType, str] = {
    MemoryType.EPISODIC: "Raw",
    MemoryType.WORKING: "Raw",
    MemoryType.SEMANTIC: "Source",
    MemoryType.PROJECT: "Source",
    MemoryType.CLIENT: "Source",
    MemoryType.PERSON: "Source",
    MemoryType.TOOL_PERFORMANCE: "Source",
    MemoryType.MODEL_PERFORMANCE: "Source",
    MemoryType.AGENT_PERFORMANCE: "Source",
    MemoryType.PREFERENCE: "Wiki",
    MemoryType.DECISION: "Wiki",
    MemoryType.LESSON: "Wiki",
    MemoryType.PROCEDURAL: "Wiki",
    MemoryType.FAILURE: "Wiki",
}

_SAFE_FILENAME = re.compile(r"[^a-z0-9\-_]+")


class MemoryVault:
    def __init__(self, root: Path | None):
        self.root = root

    @property
    def enabled(self) -> bool:
        return self.root is not None

    @staticmethod
    def layer_for(memory: MemoryEntry) -> str:
        return _LAYER_FOR_TYPE.get(memory.type, "Raw")

    @staticmethod
    def _filename(memory: MemoryEntry) -> str:
        slug = _SAFE_FILENAME.sub("-", memory.title.lower()).strip("-")[:80] or memory.id
        return f"{slug}--{memory.id}.md"

    def path_for(self, memory: MemoryEntry) -> Path | None:
        if self.root is None:
            return None
        return self.root / self.layer_for(memory) / memory.type.value / self._filename(memory)

    def write(self, memory: MemoryEntry, *, related: list[MemoryEntry] | None = None) -> None:
        """Mirror one memory to the vault. Failures are swallowed: the
        database commit already succeeded, and a broken mirror must never
        fail the write that produced it.

        `related` (optional) is the resolved set of memories this one
        has a real RELATED_TO relationship with (see
        app/memory/auto_linker.py + MemoryManager._auto_link) - when
        given, they render as an Obsidian-compatible [[wikilink]]
        section so the vault is an actual cross-linked knowledge graph,
        not a pile of isolated files."""
        if self.root is None or memory.sensitivity == Sensitivity.HIGHLY_SENSITIVE:
            return
        path = self.path_for(memory)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.render(memory, related=related), encoding="utf-8")
        except OSError:
            pass

    def discard(self, memory: MemoryEntry) -> None:
        """Remove a memory's mirror file (used only by true purge)."""
        path = self.path_for(memory)
        if path is None:
            return
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def render(memory: MemoryEntry, *, related: list[MemoryEntry] | None = None) -> str:
        frontmatter = [
            "---",
            f"id: {memory.id}",
            f"type: {memory.type.value}",
            f"title: {memory.title!r}",
            f"created: {memory.created_at.isoformat()}",
            f"updated: {memory.updated_at.isoformat()}",
            f"version: {memory.version}",
            f"confidence: {memory.confidence}",
            f"importance: {memory.importance}",
            f"verification: {memory.verification_state.value}",
            f"sensitivity: {memory.sensitivity.value}",
        ]
        if memory.tags:
            frontmatter.append("tags: [" + ", ".join(memory.tags) + "]")
        if memory.entities:
            frontmatter.append("entities: [" + ", ".join(memory.entities) + "]")
        if memory.project_id:
            frontmatter.append(f"project: {memory.project_id}")
        if memory.client_id:
            frontmatter.append(f"client: {memory.client_id}")
        if memory.supersedes:
            frontmatter.append(f"supersedes: {memory.supersedes}")
        if memory.deleted_at:
            frontmatter.append(f"deleted_at: {memory.deleted_at.isoformat()}")
        provenance_lines = "\n".join(
            f"- {entry.type.value}: {entry.reference or 'unreferenced'}"
            for entry in memory.provenance
        )
        body = [
            "---",
            "",
            f"# {memory.title}",
            "",
            memory.content,
            "",
            "## Provenance",
            "",
            provenance_lines or "- (none recorded)",
            "",
        ]
        if related:
            # Obsidian-standard [[target]] wikilink syntax, one per
            # line so both Obsidian's own graph view AND a plain grep
            # for "[[" find every cross-reference. The link target is
            # the SAME slug--id stem _filename() produces (without the
            # .md extension), which is what makes it resolve inside
            # Obsidian - a vault opened there will show this as a real
            # graph, not text that merely looks like Markdown.
            body.append("## Related")
            body.append("")
            for other in related:
                stem = MemoryVault._filename(other)[:-3]  # strip ".md"
                body.append(f"- [[{stem}|{other.title}]]")
            body.append("")
        body.append(f"*Summary: {memory.summary}*")
        body.append("")
        return "\n".join(frontmatter + body)
