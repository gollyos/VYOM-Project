"""Wake-word and hotkey activation engine for JARVIS Desktop Assistant.

Supports Picovoice Porcupine wake-word detection when PICOVOICE_ACCESS_KEY is set,
with automatic fallback to global keyboard hotkey (Ctrl+J) and queue-based IPC.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import struct
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


def listen_for_wakeword_porcupine(
    queue: multiprocessing.Queue,
    access_key: str | None = None,
    keyword: str = "jarvis",
    stop_event: Any = None,
) -> None:
    """Listen for wake-word using Picovoice Porcupine audio stream."""
    key = access_key or os.getenv("PICOVOICE_ACCESS_KEY", "")
    if not key:
        logger.info("No PICOVOICE_ACCESS_KEY found. Porcupine listener skipped.")
        return

    try:
        import pvporcupine
        import pyaudio

        porcupine = pvporcupine.create(access_key=key, keywords=[keyword])
        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=porcupine.sample_rate,
            channels=1,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=porcupine.frame_length,
        )
        logger.info("Porcupine wake-word listener started for keyword: %s", keyword)
        try:
            while stop_event is None or not stop_event.is_set():
                pcm = stream.read(porcupine.frame_length, exception_on_overflow=False)
                pcm_unpacked = struct.unpack_from("h" * porcupine.frame_length, pcm)
                result = porcupine.process(pcm_unpacked)
                if result >= 0:
                    logger.info("Wake-word '%s' detected!", keyword)
                    queue.put("WAKE")
        finally:
            stream.close()
            pa.terminate()
            porcupine.delete()
    except Exception as exc:
        logger.warning("Porcupine wake-word listener error: %s", exc)


def listen_for_hotkey(
    queue: multiprocessing.Queue,
    hotkey: str = "ctrl+j",
    stop_event: Any = None,
) -> None:
    """Listen for global keyboard hotkey trigger to activate JARVIS."""
    try:
        import keyboard

        def _on_hotkey():
            logger.info("Hotkey '%s' triggered WAKE event.", hotkey)
            queue.put("WAKE")

        keyboard.add_hotkey(hotkey, _on_hotkey)
        logger.info("Global hotkey listener registered for: %s", hotkey)
        while stop_event is None or not stop_event.is_set():
            time.sleep(0.5)
    except Exception as exc:
        logger.warning("Keyboard hotkey listener error (may require administrative privileges on Windows): %s", exc)


def start_wake_process(queue: multiprocessing.Queue, stop_event: Any = None) -> None:
    """Entry point for wake-word / hotkey background process."""
    access_key = os.getenv("PICOVOICE_ACCESS_KEY", "").strip()
    if access_key:
        listen_for_wakeword_porcupine(queue, access_key=access_key, stop_event=stop_event)
    else:
        logger.info("Using global hotkey (Ctrl+J) as primary activation trigger.")
        listen_for_hotkey(queue, hotkey="ctrl+j", stop_event=stop_event)
