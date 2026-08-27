# VYOM Acceptance Criteria (AC)

## AC-01: Native Voice & Biome UI
* **AC-01.1**: The desktop shell boots cleanly in Tauri 2 without window decorations or black screens.
* **AC-01.2**: The 3D Neural Biome renders smoothly at 60fps across all 8 Core states.
* **AC-01.3**: Voice capture activates microphone input and streams audio without blocking the UI thread.

## AC-02: Universal Tool Execution & Desktop Control
* **AC-02.1**: All 27 built-in tools register cleanly on Brain boot without import or runtime errors.
* **AC-02.2**: L0 informational tools (Wikipedia, News, Weather, Crypto, Currency, Facts) execute keyless queries in <2s.
* **AC-02.3**: System control actions (Battery %, Volume up/down/mute, Screen Lock, Ping) execute natively without subprocess shell popups.
* **AC-02.4**: L2/L3 actions (WhatsApp, Email, Trading, External Social Media) strictly enforce Permission Engine approval gates.

## AC-03: Multi-Agent Parallel Execution
* **AC-03.1**: Complex multi-step requests are decomposed by `MultiAgentOrchestrator` into isolated sub-tasks.
* **AC-03.2**: Up to 10 role agents can execute in parallel with dependency resolution.
* **AC-03.3**: Every sub-task produces verifiable evidence before being marked complete.

## AC-04: Permanent Memory & Knowledge Vault
* **AC-04.1**: SQLite FTS5 search locates historical records in <10ms across 1,000+ entries.
* **AC-04.2**: Every substantive memory is mirrored to `data/memory-vault/` as standard Markdown with YAML frontmatter.
* **AC-04.3**: Deletions are treated as tombstones (preserving audit history without data loss).
* **AC-04.4**: App uninstall leaves user data and DPAPI encrypted secrets in `%APPDATA%/vyom` intact.

## AC-05: Multilingual Intent & Communication
* **AC-05.1**: LLM Triage parses user intent and extracts meaningful keywords, ignoring conversational filler words.
* **AC-05.2**: System instructions strictly mirror the user's native language and dialect without cross-language hallucinations.
