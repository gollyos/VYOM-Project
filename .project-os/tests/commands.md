# VYOM Test & Verification Commands

## 1. Fast Unit & Subsystem Tests (Pytest)

> **Important**: Always specify `--basetemp="C:/Users/GunjanAdmin/.vyom-pytest-tmp/<lane>"` on Windows to avoid OS temp file locking issues.

```bash
# New Builtin Tools (Wikipedia, News, WhatsApp, System)
python -m pytest services/brain/tests/test_wikipedia_tool.py services/brain/tests/test_news_tool.py services/brain/tests/test_whatsapp_tool.py services/brain/tests/test_system_tool_extended.py -v --basetemp="C:/Users/GunjanAdmin/.vyom-pytest-tmp/verify"

# Phase 18 Local Alpha & Pending Work Recall Tests
python -m pytest services/brain/tests/test_pending_work_recall.py services/brain/tests/test_phase18_local_alpha.py -v --basetemp="C:/Users/GunjanAdmin/.vyom-pytest-tmp/verify"

# Full Brain Pytest Suite
python -m pytest services/brain/tests/ -q --basetemp="C:/Users/GunjanAdmin/.vyom-pytest-tmp/verify"
```

## 2. Frontend Build & Typecheck

```bash
# TypeScript Typecheck + Vite Production Bundle
npm run build

# Start Local Vite Dev Server
npm run dev
```

## 3. Desktop Tauri Build (Windows NSIS)

```bash
# Compile and Build Native Windows Desktop App (.exe / NSIS Installer)
npm run desktop:build
```
