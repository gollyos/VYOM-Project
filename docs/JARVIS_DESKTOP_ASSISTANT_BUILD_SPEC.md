# JARVIS Desktop Assistant — Complete Implementation Spec
> Synthesized from 4 reference tutorials (Anubhav Chaturvedi's NetHyTech series, Sunfire Sensei's Real-Life Jarvis, Knowledge Doctor's NLP Jarvis, and the big compilation video). This is an ORIGINAL architecture spec — not copied code — for building a Python + Web-UI desktop assistant integrated into the VYOM project or as standalone.

## 0. Goal (one line)
Bana ek desktop-resident voice assistant jo: wake-word se activate ho, natural language commands sune, apps/websites open kare, WhatsApp calls/messages bheje, weather/news/wikipedia jaise real-time data de, chat history rakhe, aur ek animated web-based UI (Electron jaisa via `eel`/`pywebview`) me dikhe.

## 1. Tech Stack Decision
| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11 | project already Python-based (VYOM uses this) |
| Bridge (Py ↔ Web UI) | `eel` library | simplest 2-way binding: `eel.expose` (Py→JS) and `eel.exposed_js_fn()(...)` (JS→Py) |
| Frontend | HTML + CSS + Bootstrap 5 + vanilla JS + jQuery | no build step, fast to iterate |
| Voice input | `speech_recognition` + `pyaudio` (Google Speech API backend) | free, works offline-ish for wake-word via `pvporcupine`, online for full STT |
| Voice output | `pyttsx3` (offline, instant) as PRIMARY. `elevenlabs` API optional for realistic voice (has quota limits — don't rely on it) | reliability > realism |
| Wake word | `pvporcupine` (Picovoice) — built-in "jarvis"/"computer" keywords, free tier | far more reliable than custom STT-based wake detection |
| DB | SQLite (`sqlite3`, stdlib) | zero setup, file-based, good enough for contacts/commands/history |
| Process model | `multiprocessing` — one process for main UI/command loop, one for background wake-word listener | prevents wake-word listener from blocking the assistant |
| Automation | `os.system`/`subprocess` for apps, `webbrowser` for URLs, `pywhatkit` for WhatsApp+YouTube, `pyautogui` for keyboard/mouse macros | matches what all 4 videos converge on |
| NLU / Chat | Rule-based intent matching (regex + keyword) for COMMANDS (open/close/call/weather) + LLM fallback (use Hermes/local model via API, NOT a random free HF endpoint that expires) for GENERAL CONVERSATION | rule-based = deterministic & fast for actions; LLM = flexible for chit-chat |

**Do NOT use**: the `hugchat` unofficial HuggingFace scraping library shown in one video (cookie-based, breaks constantly, ToS-risky) or free rotating LLM APIs. Use a real API key you control (OpenAI/Anthropic/local Ollama) for the chatbot fallback.

## 2. Project Structure
```
jarvis/
├── main.py                    # entry: eel.init + eel.start, exposes start()
├── run.py                     # multiprocessing orchestrator (process 1: UI+brain, process 2: wake-word listener)
├── requirements.txt
├── .env                       # API keys (never commit)
├── .gitignore
├── backend/
│   ├── __init__.py
│   ├── db.py                  # sqlite init, contacts table, command_history table
│   ├── helper.py               # remove_words(), extract_yt_term(), text cleanup utils
│   ├── stt.py                  # speech_recognition wrapper: listen(), listen_once()
│   ├── tts.py                  # pyttsx3 wrapper: speak(text)
│   ├── wakeword.py             # pvporcupine loop -> triggers main listen cycle
│   ├── intents/
│   │   ├── __init__.py
│   │   ├── open_close.py       # open_command(query), close_command(query) — apps+websites, backed by SQLite path lookup
│   │   ├── search.py            # google_search(query), youtube_search(query), wikipedia_search(query)
│   │   ├── communication.py     # send_whatsapp_message(name, msg), make_call(name), video_call(name) via pywhatkit + pyautogui
│   │   ├── info.py              # get_weather(city), get_news(topic), get_time(), get_ip()
│   │   ├── system.py            # volume up/down, battery_status, internet_speed_test, lock/shutdown (guarded)
│   │   └── chat.py              # llm_fallback(query) — calls your real LLM API for anything unmatched
│   └── auth/                    # OPTIONAL face-auth module (see §7) — off by default
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── main.js                 # eel-exposed JS functions: displayMessage(), hideLoader(), showJarvisUI(), etc.
└── tests/
    └── test_intents.py         # pytest: mock each intent function, assert it fires on sample phrases
```

## 3. Module-by-Module Spec

### 3.1 `backend/db.py`
```python
import sqlite3
DB_PATH = "jarvis.db"

def get_conn():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS contacts(
        id INTEGER PRIMARY KEY, name TEXT, phone TEXT, email TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS app_paths(
        id INTEGER PRIMARY KEY, name TEXT UNIQUE, path TEXT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS command_history(
        id INTEGER PRIMARY KEY, ts TEXT, query TEXT, response TEXT)""")
    conn.commit(); conn.close()

def find_contact_number(name: str) -> str | None:
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT phone FROM contacts WHERE lower(name) LIKE ?", (f"%{name.lower()}%",))
    row = cur.fetchone(); conn.close()
    return row[0] if row else None
```
**Verification**: run `python -c "from backend.db import init_db; init_db()"` → confirm `jarvis.db` created with 3 tables via `sqlite3 jarvis.db ".tables"`.

### 3.2 `backend/tts.py`
```python
import pyttsx3
engine = pyttsx3.init()
voices = engine.getProperty('voices')
engine.setProperty('voice', voices[1].id if len(voices) > 1 else voices[0].id)  # try female voice
engine.setProperty('rate', 174)

def speak(text: str):
    if not text:
        return
    engine.say(text)
    engine.runAndWait()
```
Pitfall from videos: **never re-init `pyttsx3.init()` inside a loop or inside multiprocessing children that already have an engine running** — it throws `RuntimeError: run loop already started`. Keep ONE global engine per process.

### 3.3 `backend/stt.py`
```python
import speech_recognition as sr

def listen(timeout=8, phrase_time_limit=6) -> str:
    r = sr.Recognizer()
    r.pause_threshold = 1
    with sr.Microphone() as source:
        r.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
        except sr.WaitTimeoutError:
            return ""
    try:
        query = r.recognize_google(audio, language="en-in")
        return query.lower().strip()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        return "__NO_INTERNET__"
```
Return a sentinel `"__NO_INTERNET__"` instead of crashing — the calling code should `speak("Please check your internet connection")` and retry.

### 3.4 `backend/wakeword.py`
Use `pvporcupine` (needs a free `AccessKey` from console.picovoice.ai) instead of DIY audio-amplitude clap/hotword hacks shown in the videos — those are unreliable.
```python
import pvporcupine, pyaudio, struct, os

def listen_for_wakeword(on_wake_callback):
    access_key = os.getenv("PICOVOICE_ACCESS_KEY")
    porcupine = pvporcupine.create(access_key=access_key, keywords=["jarvis"])
    pa = pyaudio.PyAudio()
    stream = pa.open(rate=porcupine.sample_rate, channels=1, format=pyaudio.paInt16,
                      input=True, frames_per_buffer=porcupine.frame_length)
    try:
        while True:
            pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
            pcm = struct.unpack_from("h" * porcupine.frame_length, pcm)
            if porcupine.process(pcm) >= 0:
                on_wake_callback()
    finally:
        stream.close(); pa.terminate(); porcupine.delete()
```
If Picovoice key not available, fallback: global keyboard hotkey (`keyboard` lib) `ctrl+j` to trigger listen cycle — this is a legitimate, reliable, zero-dependency alternative used in one of the reference videos.

### 3.5 `backend/intents/open_close.py`
- SQLite-backed app path lookup (id, name, path) so users can register custom apps.
- Universal fallback: `os.startfile(path)` on Windows if found in DB; else try `os.system(f"start {query}")`; else try common website match (`webbrowser.open(f"https://{query}.com")`).
- Close: use `os.system(f"taskkill /f /im {process_name}.exe")` on Windows (guard with an allowlist so it can never kill unrelated critical processes — reject if name not in a known map).

### 3.6 `backend/intents/communication.py` (WhatsApp via pywhatkit)
```python
import pywhatkit, time, pyautogui
from backend.db import find_contact_number

def send_whatsapp_message(name: str, message: str) -> str:
    number = find_contact_number(name)
    if not number:
        return f"No contact found for {name}"
    try:
        pywhatkit.sendwhatmsg_instantly(number, message, wait_time=15, tab_close=True)
        return f"Message sent to {name}"
    except Exception as e:
        return f"Failed to send message: {e}"

def make_call(name: str, video=False) -> str:
    number = find_contact_number(name)
    if not number:
        return f"No contact found for {name}"
    import webbrowser
    webbrowser.open(f"https://web.whatsapp.com/send?phone={number}")
    time.sleep(8)
    pyautogui.hotkey('ctrl', 'f')  # WhatsApp Web search-in-chat, NOT reliable long-term
    # NOTE: WhatsApp Web changes its DOM/shortcuts periodically — this is inherently brittle.
    # PREFER: Twilio Voice/WhatsApp Business API for production reliability instead of UI automation.
    return f"Attempting {'video ' if video else ''}call to {name}"
```
**Honest caveat to carry forward**: UI-automation-based WhatsApp calling (keyboard shortcuts on web.whatsapp.com) is fragile — Meta changes the layout. For anything beyond a demo, use Twilio's WhatsApp/Voice API with real credentials. Document this tradeoff for the user rather than pretending it's rock solid.

### 3.7 `backend/intents/info.py`
- **Weather**: use OpenWeatherMap API (free tier, key required) — NOT scraping Google. Return temp/condition/humidity in one sentence.
- **News**: use NewsAPI.org free tier — return top 3 headlines with source.
- **Wikipedia**: `wikipedia` pip package, `wikipedia.summary(query, sentences=2)`.
- **IP/System**: `requests.get('https://api.ipify.org').text`, `psutil` for battery/CPU/disk.

### 3.8 `backend/intents/chat.py` (LLM fallback)
Only reached when no rule-based intent regex matches. Call a real, user-controlled LLM (OpenAI/Anthropic key from `.env`, or local Ollama endpoint) — never an unofficial scraped chat endpoint. Keep conversation short-context (last 4-6 turns) to control cost/latency.

## 4. Command Router (the brain)
`backend/router.py`:
```python
import re
from backend.intents import open_close, search, communication, info, chat

INTENT_TABLE = [
    (r"\b(open)\b", open_close.handle_open),
    (r"\b(close|exit|quit)\b", open_close.handle_close),
    (r"\b(search|google)\b", search.handle_search),
    (r"\b(play).*\b(on youtube|song|video)\b", search.handle_youtube),
    (r"\b(weather|temperature)\b", info.handle_weather),
    (r"\b(news|headlines)\b", info.handle_news),
    (r"\b(who is|what is|tell me about)\b", search.handle_wikipedia),
    (r"\b(send).*\b(message|whatsapp)\b", communication.handle_send_message),
    (r"\b(call|video call)\b", communication.handle_call),
    (r"\b(volume up|volume down|mute)\b", info.handle_volume),
    (r"\b(battery|internet speed)\b", info.handle_system_status),
]

def route(query: str) -> str:
    query = query.lower().strip()
    for pattern, handler in INTENT_TABLE:
        if re.search(pattern, query):
            return handler(query)
    return chat.llm_fallback(query)   # anything unmatched -> conversational LLM
```
This is cleaner than the videos' giant if/elif chain — table-driven, testable, extensible (add one tuple = add one command).

## 5. Frontend (eel-based UI)
- `index.html`: Bootstrap grid, a central animated orb (`#Oval`, CSS radial-gradient + `border-radius` keyframe animation exactly like the videos describe — 3 spans rotating at different speeds/durations), a chat panel (`#sMessage`/`#rMessage` styled bubbles), an input box + mic button that toggles based on text length (JS `keyup` listener), a hamburger → offcanvas sidebar for chat history (Bootstrap `offcanvas` component).
- `main.js` exposes via `eel.expose`:
  - `displayMessage(sender, text)` — appends bubble, auto-scrolls
  - `hideLoader()` / `showOrb()` — toggles the boot animation vs the main orb
  - Wires `mic button click` → `eel.start_listening()()`
  - Wires `Enter key` / `send button` → `eel.take_typed_command(text)()`
- `main.py`:
```python
import eel
from backend.db import init_db
from backend import router, stt, tts

eel.init("frontend")

@eel.expose
def start_listening():
    query = stt.listen()
    if query == "__NO_INTERNET__":
        tts.speak("Please check your internet connection")
        return
    if not query:
        return
    eel.displayMessage("user", query)
    response = router.route(query)
    eel.displayMessage("jarvis", response)
    tts.speak(response)

@eel.expose
def take_typed_command(text: str):
    eel.displayMessage("user", text)
    response = router.route(text)
    eel.displayMessage("jarvis", response)
    tts.speak(response)

if __name__ == "__main__":
    init_db()
    eel.start("index.html", size=(1000, 700), port=8000)
```

## 6. Process Orchestration (`run.py`)
```python
import multiprocessing as mp
from main import eel_process_target   # wraps eel.start in a function
from backend.wakeword import listen_for_wakeword

def start_ui():
    eel_process_target()

def start_wake_listener():
    listen_for_wakeword(on_wake_callback=lambda: print("wake detected — trigger UI listen"))
    # NOTE: cross-process callback needs a queue/pipe, not a bare lambda —
    # use multiprocessing.Queue to pass a "wake" event to the UI process,
    # which then calls eel's exposed listen function.

if __name__ == "__main__":
    p1 = mp.Process(target=start_ui)
    p2 = mp.Process(target=start_wake_listener)
    p1.start(); p2.start()
    p1.join()
    if p2.is_alive():
        p2.terminate()
```
Key fix over the reference videos: they pass a bare closure across processes and print a naive "hot word detected," which doesn't actually work cross-process in real multiprocessing (separate memory space). **Use `multiprocessing.Queue`**: wake-listener process puts `"WAKE"` on the queue; a lightweight poller thread inside the eel process reads the queue and calls the exposed listen function.

## 7. Face Authentication (OPTIONAL, off by default)
The Sunfire Sensei video uses raw OpenCV LBPH face recognizer (`cv2.face.LBPHFaceRecognizer_create()`), which needs `opencv-contrib-python` (not plain `opencv-python`). Steps: (1) capture ~50-100 grayscale face samples per user via Haar cascade, (2) train with `recognizer.train(faces, ids)`, (3) at runtime compare live frame confidence score against a threshold (~<70 = confident match). This is a real, working, well-known approach — **but treat it as a nice-to-have gate, not a security boundary** (LBPH is easily spoofed by a photo). If security actually matters, don't build this; if it's a fun demo trigger, it's fine.

## 8. requirements.txt
```
eel
speechrecognition
pyaudio
pyttsx3
pvporcupine
pywhatkit
pyautogui
wikipedia
requests
psutil
python-dotenv
keyboard
opencv-contrib-python   # only if doing face auth
numpy
```

## 9. Build Order (do this sequentially, verify each step before moving on)
1. Scaffold folder structure + `db.py` + confirm `jarvis.db` created with tables.
2. `tts.py` — get `speak("hello")` working standalone.
3. `stt.py` — get `listen()` returning recognized text standalone.
4. `router.py` with 2-3 dummy intents (`open notepad`, `what time is it`) — test via plain terminal loop (no UI yet) until routing logic is solid.
5. Build `frontend/` static UI, wire up `eel` with the terminal-tested router — confirm typed commands work end-to-end in the browser-based eel window.
6. Add voice (`start_listening`) on top of working typed flow.
7. Add wake-word (`pvporcupine` or keyboard-hotkey fallback) as the LAST piece, since it's the most failure-prone.
8. Add WhatsApp/communication intents — test with your own number first.
9. Add weather/news/wikipedia (need real API keys — get them, put in `.env`, never commit).
10. Optional: face auth, chat history sidebar, LLM fallback for open-ended chat.

## 10. What NOT to copy from the reference videos
- Unofficial scraped chatbot libraries (`hugchat` with browser cookies) — expires, ToS risk.
- Amplitude-threshold "clap detector" as a wake mechanism — use real wake-word engine or hotkey.
- Bare `os.system("start nortpad")` typo-prone hardcoded app names — use the DB-backed lookup table instead.
- Committing `cookies.json` / API keys to git — always `.gitignore` secrets, use `.env` + `python-dotenv`.
