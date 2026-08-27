# VYOM Runtime State & Environment

## 1. Active Ports & Services

| Service | Port | Host | Status | Primary Entrypoint |
|---|---|---|---|---|
| **VYOM Brain (FastAPI)** | `7788` | `127.0.0.1` | Standalone / Bundled | [services/brain/app/main.py](file:///c:/VYOM%20Project/services/brain/app/main.py) |
| **Vite Dev Server** | `1420` | `localhost` | Dev Mode | [vite.config.ts](file:///c:/VYOM%20Project/vite.config.ts) |
| **Tauri Desktop Shell** | Native | Windows Desktop | Release / Dev | [src-tauri/src/main.rs](file:///c:/VYOM%20Project/src-tauri/src/main.rs) |

## 2. Storage & Databases

* **Primary SQLite DB**: `services/brain/data/vyom.db` (58 tables with SQLite FTS5 virtual tables).
* **Obsidian-Style Markdown Memory Vault**: `services/brain/data/memory-vault/` (Organized into Raw, Source, and Wiki layers).
* **Windows DPAPI Secret Vault**: `services/brain/data/secrets/` (Protected by Windows user account DPAPI encryption).
* **Quota & Budget Ledger**: `services/brain/data/quota-usage.json` (RPM / RPD tracking).
* **Response Cache**: `services/brain/data/response-cache/` (Short-TTL disk cache).

## 3. Tool & Model Readiness

* **Registered Built-in Tools**: 27 tools registered in `ToolRegistry` on Brain boot.
* **Model Router**: Triple-model fallback (`gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-2.5-flash-lite`) with QuotaBudgeter.
* **Language Engine**: Dynamic Language Mirroring (Hinglish, Hindi, English, Spanish, French, German, Japanese, etc.).
