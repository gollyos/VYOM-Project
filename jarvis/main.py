"""Main entry point for JARVIS Desktop Assistant.

Initializes the Eel web server, exposes bidirectional endpoints for
voice and text interaction, and launches the desktop interface.
"""

from __future__ import annotations

import logging
import os
import socket
import sys
from pathlib import Path

# Add project root to sys.path if not present
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
root_dir = current_dir.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import eel

from jarvis.backend import router, stt, tts
from jarvis.backend.db import (
    add_contact,
    get_all_contacts,
    get_recent_history,
    init_db,
    register_app_path,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s): %(message)s",
)
logger = logging.getLogger("jarvis.main")

# Initialize Eel with frontend web directory
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend")
eel.init(FRONTEND_DIR)


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a local TCP port is already in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


def find_free_port(starting_port: int = 8000, max_attempts: int = 20) -> int:
    """Find an available TCP port for the Eel web server."""
    for port in range(starting_port, starting_port + max_attempts):
        if not is_port_in_use(port):
            return port
    return starting_port


# ============================================================================
# Eel Exposed Python Functions (Callable from Frontend JavaScript)
# ============================================================================

@eel.expose
def start_listening() -> None:
    """Listen for audio from the microphone and process the spoken command."""
    logger.info("Starting voice listening cycle...")
    try:
        eel.setJarvisState("listening")()
    except Exception:
        pass

    query = stt.listen()

    if query == "__NO_MIC__":
        msg = "Microphone is unavailable or not detected on your device, sir."
        try:
            eel.displayMessage("jarvis", msg)()
            eel.setJarvisState("ready")()
        except Exception:
            pass
        tts.speak(msg)
        return

    if query == "__NO_INTERNET__":
        msg = "Please check your internet connection for speech recognition, sir."
        try:
            eel.displayMessage("jarvis", msg)()
            eel.setJarvisState("ready")()
        except Exception:
            pass
        tts.speak(msg)
        return

    if not query:
        logger.info("Voice input was silent or timed out.")
        try:
            eel.setJarvisState("ready")()
        except Exception:
            pass
        return

    logger.info("Recognized voice query: '%s'", query)
    try:
        eel.displayMessage("user", query)()
        eel.setJarvisState("thinking")()
    except Exception:
        pass

    # Execute command
    response = router.route(query)
    logger.info("JARVIS Response: '%s'", response)

    try:
        eel.displayMessage("jarvis", response)()
        eel.setJarvisState("speaking")()
    except Exception:
        pass

    tts.speak(response)

    try:
        eel.setJarvisState("ready")()
    except Exception:
        pass


@eel.expose
def take_typed_command(text: str) -> None:
    """Process a typed text command from the UI command bar."""
    if not text or not text.strip():
        return

    logger.info("Processing typed command: '%s'", text)
    try:
        eel.setJarvisState("thinking")()
    except Exception:
        pass

    response = router.route(text)
    logger.info("JARVIS Response: '%s'", response)

    try:
        eel.displayMessage("jarvis", response)()
        eel.setJarvisState("speaking")()
    except Exception:
        pass

    tts.speak(response)

    try:
        eel.setJarvisState("ready")()
    except Exception:
        pass


@eel.expose
def get_history(limit: int = 40) -> None:
    """Fetch command history and send to the UI history drawer."""
    records = get_recent_history(limit=limit)
    try:
        eel.updateCommandHistory(records)()
    except Exception as exc:
        logger.warning("Failed to push history to frontend: %s", exc)


@eel.expose
def get_contacts() -> None:
    """Fetch contacts database and send to the UI contacts drawer."""
    contacts = get_all_contacts()
    try:
        eel.updateContactsList(contacts)()
    except Exception as exc:
        logger.warning("Failed to push contacts to frontend: %s", exc)


@eel.expose
def save_contact(name: str, phone: str, email: str = "") -> bool:
    """Add a new contact to the SQLite contacts table."""
    try:
        add_contact(name, phone, email)
        get_contacts()
        return True
    except Exception as exc:
        logger.error("Failed to save contact: %s", exc)
        return False


@eel.expose
def register_custom_app(name: str, path: str) -> bool:
    """Register a custom app path."""
    try:
        register_app_path(name, path)
        return True
    except Exception as exc:
        logger.error("Failed to register app path: %s", exc)
        return False


def eel_process_target(port: int | None = None, block: bool = True) -> None:
    """Target function to launch Eel web server."""
    init_db()
    chosen_port = port if port is not None else find_free_port(8000)
    logger.info("Starting JARVIS UI on http://localhost:%d", chosen_port)

    # Options for Eel
    options = {
        "mode": "chrome",  # Attempts Chrome/Edge in app mode, fallback to default browser
        "host": "localhost",
        "port": chosen_port,
        "size": (1020, 740),
        "close_callback": lambda page, sockets: logger.info("JARVIS UI window closed."),
    }

    try:
        eel.start("index.html", **options)
    except (SystemExit, KeyboardInterrupt):
        logger.info("JARVIS Eel loop terminated.")
    except Exception as exc:
        logger.warning("Eel start with Chrome app mode failed (%s), falling back to browser window...", exc)
        options["mode"] = "default"
        eel.start("index.html", **options)


if __name__ == "__main__":
    eel_process_target()
