# VYOM System Architecture & Topology

## 1. System Topology Overview

VYOM is a native, voice-first, autonomous AI operating environment with a strict boundary:

```
[ Tauri 2 Native Desktop Window / Tray (Rust) ]
                     │ (WebSocket / IPC)
[ React 18 + Three.js 3D Neural Biome & Dynamic UI Composer ]
                     │ (HTTP / WebSocket :7788)
[ Local VYOM Brain Runtime (FastAPI / Python 3.12) ]
     ├── Model Router (Gemini / OpenAI / Anthropic / Local Triage)
     ├── Quota Budgeter & Response Cache (RPM/RPD Sliding Window)
     ├── Tool Registry (27 Built-in Tools + Dynamic MCP Adapters)
     ├── MultiAgentOrchestrator (10 Specialized Role Agents)
     ├── Dual-Layer Memory Store:
     │     ├── SQLite DB (`vyom.db` with FTS5 + Vector Embeddings)
     │     └── Markdown Memory Vault (`data/memory-vault/`)
     ├── EventBus & AutomationEngine (Scheduled Cron & Triggers)
     ├── Windows DPAPI Secret Vault (Hardware/OS Encrypted Tokens)
     └── Safe Desktop Execution Layer (Win32 COM + pywinauto + Playwright)
```

## 2. Core Subsystems

### A. Cognitive Brain Runtime (`services/brain/app/`)
* **Lifespan & Services**: [main.py](file:///c:/VYOM%20Project/services/brain/app/main.py)
* **Task Lifecycle & Intent Classification**: [task_runtime.py](file:///c:/VYOM%20Project/services/brain/app/runtime/task_runtime.py), [task_classifier.py](file:///c:/VYOM%20Project/services/brain/app/runtime/task_classifier.py), [llm_triage.py](file:///c:/VYOM%20Project/services/brain/app/runtime/llm_triage.py)
* **Execution & Safety**: [action_engine.py](file:///c:/VYOM%20Project/services/brain/app/execution/action_engine.py), [permission_engine.py](file:///c:/VYOM%20Project/services/brain/app/security/permission_engine.py)

### B. Tool Execution Protocol (`services/brain/app/tools/`, `tools_builtin/`)
* Standard Base Tool Contract: `ToolMetadata`, `PermissionLevel` (`L0` Read-only, `L1` Local Action, `L2` External Side-Effect, `L3` High-Risk/Financial).
* 27 Built-in tools including:
  * Information: `WikipediaTool`, `NewsTool`, `WeatherTool`, `CryptoTool`, `CurrencyTool`, `TriviaFactsTool`
  * System Control: `SystemTool` (Battery %, Volume up/down/mute, Screen Lock, Ping), `TerminalTool`, `FilesystemTool`, `GitTool`
  * Visual & Desktop: `ScreenObserveTool`, `ScreenshotTool`, `DesktopTool`, `InputControlTool`
  * Automation & Media: `BrowserTool`, `VideoTool` (MP4 ffmpeg render), `WhatsAppTool`, `EmailTool`, `LinkedInTool`, `TwitterTool`, `InstagramTool`, `FacebookTool`, `SheetsTool`, `TelegramTool`, `DiscordTool`, `YouTubeTool`

### C. Persistent Memory & Knowledge Graph (`services/brain/app/memory/`, `knowledge/`, `brain_graph/`)
* Dual-Layer Architecture: SQLite (`vyom.db` - 58 tables) + Obsidian-Style Markdown Vault (`data/memory-vault/`).
* 18 Entity Node Types in Knowledge Graph (Tasks, Memories, CRM Records, Artifacts, Goals, Milestones, Habits, Automations, Experiences, Adaptive Strategies, Devices, Skills, Agents, Capabilities, Tools, Models).

### D. Multi-Agent Ecosystem (`services/brain/app/agents/`)
* `MultiAgentOrchestrator` splits complex owner goals into sub-tasks.
* 10 Built-in Role Agents: Researcher, Coder, Analyst, Desktop Operator, Browser Operator, File Manager, Communicator, Monitor, Planner, QA Verifier.

### E. Frontend & Visual Experience (`src/`, `src-tauri/`)
* 3D Neural Biome (Three.js / React Three Fiber) with 8 Core States (`Idle`, `Listening`, `Understanding`, `Thinking`, `Speaking`, `Executing`, `Verifying`, `Interrupted`).
* Dynamic UI Composer renders structured surfaces (Funnel, Lead Profile, Email Thread, Tool Output, Evidence Card) around the Core.
