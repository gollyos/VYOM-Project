# VYOM Baseline Reality & Context Audit (2026-08-27)

## 1. Baseline System Status

| Check | Result | Evidence |
|---|---|---|
| **Frontend Build (`npm run build`)** | `PASS` | `✓ built in 26.98s` (0 errors, TypeScript typecheck green) |
| **Brain Core Integration Tests** | `PASS` | `14 passed in 76.09s` (`test_pending_work_recall.py`, `test_phase18_local_alpha.py`) |
| **Native Tools Tests** | `PASS` | `13 passed in 5.27s` (`WikipediaTool`, `NewsTool`, `WhatsAppTool`, `SystemTool`) |
| **Git & Remote Tracking** | `PASS` | Remote `repair/soul-and-memory` synchronized with GitHub (0 secrets, backup files filtered) |
| **Database & Schema Integrity** | `PASS` | 58 tables in `vyom.db`, FTS5 virtual tables active, DPAPI secret vault active |

---

## 2. Context Classification Matrix

### A. Expertise Context (Always-Loaded / Lean)
* System Invariant: VYOM is a native Windows Tauri 2 + React + Three.js app with a FastAPI Brain runtime on `:7788`.
* Safety Invariant: L0/L1 automatic, L2/L3 strictly require user approval.

### B. Situational Context (Just-in-Time)
* Active session logs, live browser session tokens, ephemeral process IDs.

### C. Operational Memory (Durable Lessons)
* Windows temp directory locking requires `--basetemp="C:/Users/GunjanAdmin/.vyom-pytest-tmp/<lane>"`.
* Free-tier Gemini requires QuotaBudgeter RPM/RPD sliding window.
* Backup files (`.env.bak`, `.db.bak`) must never enter git tracking.

### D. Canonical Knowledge (Ground Truth)
* `config/tools.yaml`, `config/models.yaml`, `config/memory.yaml`, `config/agents.yaml`.

---

## 3. Routing & Index Integrity Audit

* **ROUTE-001 (Tool Registry)**: All 27 built-in tools in `services/brain/app/tools_builtin/` are registered in `main.py` and enabled in `config/tools.yaml`. [VERIFIED]
* **ROUTE-002 (Language Engine)**: `executor.py`, `planner.py`, `llm_triage.py` enforce strict language mirroring across all global languages. [VERIFIED]
* **ROUTE-003 (Memory Vault)**: SQLite FTS5 index mirrors to `data/memory-vault/` Markdown notes. [VERIFIED]
* **ROUTE-004 (Multi-Agent Dispatch)**: `MultiAgentOrchestrator` maps to 10 built-in role agents. [VERIFIED]

---

## 4. Issue Ledger

| ID | Title | Priority | Status | Root Cause & Resolution |
|---|---|---|---|---|
| **BUG-001** | Missing YouTubeTool import in main.py | HIGH | `FIXED` | Import statement was missing from `app.tools_builtin`; restored and verified with 14/14 tests. |
| **BUG-002** | GitHub Secret Scanning Push Block | CRITICAL | `FIXED` | Old backup files `.env.bak` & `.db.bak` in ancestor commit history contained keys; filtered via `git filter-branch` and pushed cleanly. |
| **BUG-003** | Monolingual/Hinglish Prompt Assumption | MEDIUM | `FIXED` | System instructions hardcoded Hinglish; upgraded with strict dynamic multilingual language mirroring. |
