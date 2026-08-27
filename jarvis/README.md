# J.A.R.V.I.S — Desktop Assistant

A modern, autonomous Python + Eel desktop voice assistant.

## Features

- **Voice & Hotkey Activation**: Voice commands via SpeechRecognition, global `Ctrl + J` shortcut, and optional Picovoice wake-word (`jarvis`).
- **Interactive Cyber Web UI**: Eel-powered interface featuring an animated 3-ring glowing neural core orb, glassmorphism chat canvas, and offcanvas history & contacts management.
- **Smart Intent Router**: High-speed table-driven regex routing with LLM fallback (Gemini, OpenAI, Anthropic, Ollama, or local rules).
- **Desktop & System Automation**: App and website launch (`open Chrome`, `open Spotify`), guarded process close (`close Notepad`), volume adjustments, battery & CPU monitoring, screen lock.
- **Communication**: WhatsApp messaging and calls via `pywhatkit` with SQLite contact management.
- **Information & Search**: Live weather (OpenWeatherMap / Open-Meteo), top news, Wikipedia 2-sentence summaries, Google search, YouTube play, and IP lookups.
- **Persistent Memory**: SQLite database (`jarvis.db`) storing contacts, custom application paths, and command history.

## Getting Started

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure Environment (Optional)
Copy `.env.example` to `.env` and fill in any optional API keys:
```bash
cp .env.example .env
```

### 3. Run JARVIS
- **Standard UI Mode**:
  ```bash
  python main.py
  ```
- **Multiprocessing Mode (UI + Background Wake-Word/Hotkey Listener)**:
  ```bash
  python run.py
  ```

### 4. Run Tests
```bash
python -m pytest tests/ -v
```
