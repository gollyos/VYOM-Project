"""Text-to-Speech (TTS) engine for JARVIS Desktop Assistant.

Uses pyttsx3 with single-instance lifecycle management, rate tuning,
and graceful fallback for headless/audio-disabled test environments.
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

_engine = None
_engine_lock = threading.Lock()
_engine_initialized = False


def _get_engine():
    """Lazily initialize a single pyttsx3 engine instance."""
    global _engine, _engine_initialized
    with _engine_lock:
        if _engine is not None:
            return _engine
        if _engine_initialized:
            return None
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.setProperty("rate", 174)
            voices = engine.getProperty("voices")
            if voices:
                # Select female or secondary voice if available, else first
                target_idx = 1 if len(voices) > 1 else 0
                engine.setProperty("voice", voices[target_idx].id)
            _engine = engine
            _engine_initialized = True
            return _engine
        except Exception as exc:
            logger.warning("pyttsx3 engine initialization failed or not supported in this environment: %s", exc)
            _engine_initialized = True
            _engine = None
            return None


def speak(text: str) -> bool:
    """Speak text using pyttsx3 text-to-speech.

    Returns True if spoken via engine, False if engine unavailable.
    Does not crash if audio hardware is busy or unsupported.
    """
    if not text or not str(text).strip():
        return False

    clean_text = str(text).strip()
    engine = _get_engine()
    if engine is None:
        logger.info("[JARVIS SPEAK FALLBACK]: %s", clean_text)
        return False

    try:
        with _engine_lock:
            engine.say(clean_text)
            engine.runAndWait()
        return True
    except Exception as exc:
        logger.warning("TTS speech execution error: %s", exc)
        return False
