# VYOM Autonomous Project Router

> Primary routing index. Canonical pointers to exact subsystems, schemas, policies, and runtimes.

## Quick Route Index

| Need | Canonical Destination | Description |
|---|---|---|
| **Architecture Blueprint** | [.project-os/architecture.md](file:///c:/VYOM%20Project/.project-os/architecture.md) | High-level system topology & contracts |
| **Runtime & Execution State** | [.project-os/runtime-state.md](file:///c:/VYOM%20Project/.project-os/runtime-state.md) | Active database, services, and ports |
| **Acceptance Criteria** | [.project-os/acceptance-criteria.md](file:///c:/VYOM%20Project/.project-os/acceptance-criteria.md) | Measurable system requirements |
| **Test Commands** | [.project-os/tests/commands.md](file:///c:/VYOM%20Project/.project-os/tests/commands.md) | Exact commands for unit, e2e, build |
| **Reality & Integrity Audits** | [.project-os/audits/](file:///c:/VYOM%20Project/.project-os/audits/) | Point-in-time audit ledgers |
| **Multi-Agent Coordination** | [AGENTS.md](file:///c:/VYOM%20Project/AGENTS.md) | Multi-agent lanes, rules, and boundaries |
| **Taskboard & Progress** | [TASKBOARD.md](file:///c:/VYOM%20Project/TASKBOARD.md) | Active backlog and claimed lanes |
| **Implementation Ledger** | [VYOM_IMPLEMENTATION_STATUS.md](file:///c:/VYOM%20Project/VYOM_IMPLEMENTATION_STATUS.md) | Detailed verification ledger & change logs |

---

## Subsystem Navigation

* **Brain Fast-API Backend**: [services/brain/app/main.py](file:///c:/VYOM%20Project/services/brain/app/main.py)
* **Built-in Tool Layer**: [services/brain/app/tools_builtin/](file:///c:/VYOM%20Project/services/brain/app/tools_builtin/) (27 tools: Wikipedia, News, WhatsApp, System, Video, Filesystem, Terminal, Browser, etc.)
* **Persistent Memory & Vault**: [services/brain/app/memory/](file:///c:/VYOM%20Project/services/brain/app/memory/) & [data/memory-vault/](file:///c:/VYOM%20Project/services/brain/data/memory-vault/)
* **Multi-Agent Orchestrator**: [services/brain/app/agents/multi_agent_orchestrator.py](file:///c:/VYOM%20Project/services/brain/app/agents/multi_agent_orchestrator.py)
* **Tauri Desktop Native Shell**: [src-tauri/](file:///c:/VYOM%20Project/src-tauri/) (Rust Tauri 2, NSIS installer, tray, global shortcuts)
* **Frontend 3D Biome & UI Composer**: [src/](file:///c:/VYOM%20Project/src/) (Three.js, React Three Fiber, Dynamic UI Composer)
* **MCP & Plugin Connectors**: [services/brain/app/mcp/](file:///c:/VYOM%20Project/services/brain/app/mcp/) & [config/tools.yaml](file:///c:/VYOM%20Project/config/tools.yaml)
