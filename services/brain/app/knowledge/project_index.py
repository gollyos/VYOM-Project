"""
VYOM Project & Client File Knowledge Indexer
============================================
Maintains a live, searchable index of all workspace files, client deliverables,
generated spreadsheets, reports, and architecture modules so VYOM always knows:
- Kaha hai (File location)
- Kis kaam ki hai (Purpose & capabilities)
- Kyu banayi hai (Reason & origin goal)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

INDEX_STORAGE_PATH = Path("services/brain/data/project_file_index.json")


@dataclass
class FileKnowledgeRecord:
    path: str
    filename: str
    category: str  # 'client_deliverable', 'spreadsheet', 'report', 'core_engine', 'config'
    purpose: str   # Kis kaam ki hai
    why_created: str  # Kyu banayi hai
    size_bytes: int
    last_modified: str
    tags: list[str]


# Pre-mapped knowledge for core project architecture
CORE_ARCHITECTURE_KNOWLEDGE = [
    {
        "pattern": "app/automation/personal_os_engine.py",
        "category": "core_engine",
        "purpose": "Personal OS automation engine: Deep Research, bookings, client deliveries, tool discovery, custom Excel exports.",
        "why_created": "Owner ke automated multi-step research aur client workflow execution ke liye.",
        "tags": ["automation", "research", "delivery", "booking", "excel"],
    },
    {
        "pattern": "app/desktop/execution_engine.py",
        "category": "core_engine",
        "purpose": "Windows desktop controller: window management, app launcher, screen coordinates, native OS execution.",
        "why_created": "Owner ke computer par native apps aur windows ko direct control karne ke liye.",
        "tags": ["desktop", "windows", "screen", "apps"],
    },
    {
        "pattern": "app/finance/intelligence_engine.py",
        "category": "core_engine",
        "purpose": "Financial intelligence & live paper trading: real-time stock/crypto quotes, risk rules, order management.",
        "why_created": "Real-time market tracking aur risk-managed paper trading simulation ke liye.",
        "tags": ["finance", "trading", "stocks", "crypto", "paper_trading"],
    },
    {
        "pattern": "app/productivity/chief_of_staff_engine.py",
        "category": "core_engine",
        "purpose": "Chief of Staff & Life OS: Goals, habit streaks, focus sessions, morning briefings, evening reviews.",
        "why_created": "Owner ke daily schedule, health habits, aur personal business goals ko track karne ke liye.",
        "tags": ["productivity", "habits", "goals", "focus", "briefing"],
    },
    {
        "pattern": "app/diagnostics/observability_engine.py",
        "category": "core_engine",
        "purpose": "System diagnostics & cost tracking: VYOM Doctor, security posture audit, model cost analytics.",
        "why_created": "System ki health verify karne aur token/cost transparency maintain karne ke liye.",
        "tags": ["diagnostics", "security", "doctor", "cost"],
    },
    {
        "pattern": "app/sheets/local_excel.py",
        "category": "spreadsheet_engine",
        "purpose": "Zero-cloud local Excel (.xlsx) & CSV spreadsheet generator with customizable styling.",
        "why_created": "Owner ke kahe mutabiq exact columns ke sath clean data spreadsheets create karne ke liye.",
        "tags": ["excel", "csv", "sheets", "data", "export"],
    },
    {
        "pattern": "app/browser/browser_actions.py",
        "category": "browser_engine",
        "purpose": "Playwright web controller: page navigation, web scraping, coordinate clicking, YouTube ad skipping.",
        "why_created": "Direct browser scraping aur YouTube video automation bina paid API ke karne ke liye.",
        "tags": ["browser", "playwright", "youtube", "scraping", "ad_skip"],
    },
    {
        "pattern": "app/crm/engine.py",
        "category": "crm_engine",
        "purpose": "CRM & Lead Finder: company leads, contacts, status pipeline, opportunity scoring.",
        "why_created": "Business leads track karne aur client pipeline manage karne ke liye.",
        "tags": ["crm", "leads", "clients", "sales"],
    },
    {
        "pattern": "app/unified_os.py",
        "category": "orchestration",
        "purpose": "Central unified runtime coordinating all real domain engines under one personal operator authority.",
        "why_created": "Sabhi alag-alag modules ko ek single cohesive JARVIS OS me bind karne ke liye.",
        "tags": ["unified_os", "runtime", "jarvis", "coordinator"],
    },
]


class ProjectKnowledgeService:
    """Indexed registry for all files and deliverables across VYOM workspace."""

    def __init__(self, workspace_root: Path | None = None, storage_path: Path | None = None):
        self.workspace_root = workspace_root or Path("c:/VYOM Project")
        self.storage_path = storage_path or INDEX_STORAGE_PATH
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._records: dict[str, FileKnowledgeRecord] = {}
        self._load()

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
                for k, v in raw.items():
                    self._records[k] = FileKnowledgeRecord(**v)
            except Exception:
                self._records = {}

    def _save(self) -> None:
        try:
            dump = {k: asdict(v) for k, v in self._records.items()}
            self.storage_path.write_text(json.dumps(dump, indent=2), encoding="utf-8")
        except Exception:
            pass

    def register_file(
        self,
        file_path: Path | str,
        *,
        category: str = "general",
        purpose: str = "",
        why_created: str = "",
        tags: list[str] | None = None,
    ) -> FileKnowledgeRecord:
        """Register or update a file's knowledge record."""
        p = Path(file_path).resolve()
        rel_str = str(p)
        size = p.stat().st_size if p.exists() else 0
        mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat() if p.exists() else datetime.now(timezone.utc).isoformat()

        record = FileKnowledgeRecord(
            path=rel_str,
            filename=p.name,
            category=category,
            purpose=purpose or "Project resource / file",
            why_created=why_created or "Generated during task execution",
            size_bytes=size,
            last_modified=mtime,
            tags=tags or [],
        )
        self._records[rel_str] = record
        self._save()
        return record

    def index_workspace_artifacts(self) -> int:
        """Scan artifacts directory (reports, spreadsheets, audio) and index them."""
        artifacts_dir = Path("services/brain/data/artifacts")
        count = 0
        if artifacts_dir.exists():
            for f in artifacts_dir.rglob("*"):
                if f.is_file():
                    ext = f.suffix.lower()
                    if ext in (".xlsx", ".csv"):
                        self.register_file(
                            f,
                            category="spreadsheet",
                            purpose="Data export spreadsheet with formatted columns and rows.",
                            why_created="User data collection ya lead export request par banayi gayi.",
                            tags=["excel", "spreadsheet", "export", "data"],
                        )
                        count += 1
                    elif ext in (".md", ".txt", ".json"):
                        self.register_file(
                            f,
                            category="report",
                            purpose="Structured research/delivery document or analysis report.",
                            why_created="Client delivery ya deep research findings document karne ke liye.",
                            tags=["report", "document", "research"],
                        )
                        count += 1

        # Register core architecture knowledge
        for arch in CORE_ARCHITECTURE_KNOWLEDGE:
            arch_p = (self.workspace_root / "services/brain" / arch["pattern"]).resolve()
            if arch_p.exists():
                self.register_file(
                    arch_p,
                    category=arch["category"],
                    purpose=arch["purpose"],
                    why_created=arch["why_created"],
                    tags=arch["tags"],
                )
                count += 1

        return count

    def find_files(self, query: str) -> list[FileKnowledgeRecord]:
        """Search files by keyword in path, purpose, filename, or tags."""
        q = query.lower().strip()
        results = []
        for rec in self._records.values():
            score = 0
            if q in rec.filename.lower():
                score += 10
            if q in rec.path.lower():
                score += 5
            if q in rec.purpose.lower():
                score += 8
            if q in rec.why_created.lower():
                score += 6
            if any(q in t.lower() for t in rec.tags):
                score += 7
            if score > 0:
                results.append((score, rec))

        results.sort(key=lambda x: x[0], reverse=True)
        return [r[1] for r in results]

    def get_summary_report(self) -> dict[str, Any]:
        """Generate a complete summary of all indexed project & client files."""
        by_category: dict[str, list[dict[str, Any]]] = {}
        for rec in self._records.values():
            by_category.setdefault(rec.category, []).append({
                "filename": rec.filename,
                "path": rec.path,
                "purpose": rec.purpose,
                "why_created": rec.why_created,
                "size_kb": round(rec.size_bytes / 1024, 1),
            })
        return {
            "total_indexed_files": len(self._records),
            "categories": list(by_category.keys()),
            "files_by_category": by_category,
        }


_default_project_knowledge: ProjectKnowledgeService | None = None

def get_project_knowledge() -> ProjectKnowledgeService:
    global _default_project_knowledge
    if _default_project_knowledge is None:
        _default_project_knowledge = ProjectKnowledgeService()
        _default_project_knowledge.index_workspace_artifacts()
    return _default_project_knowledge
