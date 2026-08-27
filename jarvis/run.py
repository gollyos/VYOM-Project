"""Multiprocessing Orchestrator for JARVIS Desktop Assistant.

Coordinates:
  - Process 1: Eel UI & Command Dispatch loop with background queue poller.
  - Process 2: Wake-Word / Global Hotkey listener with IPC queue.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import sys
import threading
import time
from pathlib import Path

# Add project root to sys.path
current_dir = Path(__file__).resolve().parent
if str(current_dir) not in sys.path:
    sys.path.insert(0, str(current_dir))
root_dir = current_dir.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from jarvis.backend.wakeword import start_wake_process
from jarvis.main import eel_process_target, start_listening

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (%(name)s): %(message)s",
)
logger = logging.getLogger("jarvis.orchestrator")


def _wake_queue_listener_thread(wake_queue: mp.Queue, stop_event: threading.Event) -> None:
    """Daemon thread inside UI process that polls the wake queue and triggers voice listening."""
    logger.info("Wake queue poller thread active.")
    while not stop_event.is_set():
        try:
            if not wake_queue.empty():
                event = wake_queue.get_nowait()
                if event == "WAKE":
                    logger.info("Wake event received from background listener. Triggering start_listening()...")
                    start_listening()
        except Exception:
            pass
        time.sleep(0.1)


def run_ui_with_queue(wake_queue: mp.Queue) -> None:
    """Start Eel UI process with the IPC wake queue thread."""
    stop_event = threading.Event()
    poller = threading.Thread(target=_wake_queue_listener_thread, args=(wake_queue, stop_event), daemon=True)
    poller.start()

    try:
        eel_process_target()
    finally:
        stop_event.set()


def run_wake_listener(wake_queue: mp.Queue, stop_event: mp.Event) -> None:
    """Start background wake-word / hotkey process."""
    try:
        start_wake_process(wake_queue, stop_event=stop_event)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Wake listener stopped.")


def main() -> None:
    """Launch multiprocessing orchestrator."""
    # Ensure Windows multiprocessing spawn support
    mp.freeze_support()

    logger.info("Starting JARVIS Multi-Process Orchestrator...")
    wake_queue: mp.Queue = mp.Queue()
    stop_wake_event = mp.Event()

    # Process 1: Background Wake Listener
    p_wake = mp.Process(
        target=run_wake_listener,
        args=(wake_queue, stop_wake_event),
        name="JARVIS-WakeListener",
        daemon=True,
    )
    p_wake.start()
    logger.info("Spawned wake-listener process (PID: %d)", p_wake.pid)

    # Process 2: Main UI Loop (runs in current process or separate process)
    try:
        run_ui_with_queue(wake_queue)
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Shutting down...")
    finally:
        stop_wake_event.set()
        if p_wake.is_alive():
            logger.info("Terminating wake-listener process...")
            p_wake.terminate()
            p_wake.join(timeout=2)
        logger.info("JARVIS shutdown complete.")


if __name__ == "__main__":
    main()
