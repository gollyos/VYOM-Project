"""Speech-to-Text (STT) module for JARVIS Desktop Assistant.

Uses SpeechRecognition with microphone ambient noise adjustment and
Google Speech Recognition API backend.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def listen(timeout: int = 8, phrase_time_limit: int = 6, language: str = "en-in") -> str:
    """Listen to microphone input and convert speech to lower-case text.

    Returns:
      - Transcribed text string on success.
      - "" on timeout, silence, or unrecognizable speech.
      - "__NO_INTERNET__" if Google API returns a connection/request error.
      - "__NO_MIC__" if microphone device cannot be opened.
    """
    try:
        import speech_recognition as sr
    except ImportError:
        logger.error("speech_recognition package is not installed.")
        return ""

    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.0
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = True

    try:
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            try:
                audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            except sr.WaitTimeoutError:
                return ""
    except (OSError, AttributeError, Exception) as exc:
        logger.warning("Microphone hardware or audio driver unavailable: %s", exc)
        return "__NO_MIC__"

    try:
        query = recognizer.recognize_google(audio, language=language)
        return query.lower().strip()
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        return "__NO_INTERNET__"
    except Exception as exc:
        logger.warning("STT transcription error: %s", exc)
        return ""


def listen_once(timeout: int = 4, phrase_time_limit: int = 4) -> str:
    """Quick single-phrase listener for confirmations or short inputs."""
    return listen(timeout=timeout, phrase_time_limit=phrase_time_limit)
