"""Command Router for JARVIS Desktop Assistant.

Table-driven regex intent classification and dispatch system.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from jarvis.backend.db import log_command
from jarvis.backend.intents import (
    chat,
    communication,
    info,
    open_close,
    search,
    system,
)

logger = logging.getLogger(__name__)

# Intent Table: (regex_pattern, handler_func)
# Specific queries (weather, time, battery, media, apps) have precedence over generic Q&A.
INTENT_TABLE: list[tuple[str, Callable[[str], str]]] = [
    # 1. YouTube & Media playback
    (r"\b(play)\b.*\b(on youtube|on yt|song|music|track|video)\b", lambda q: search.handle_youtube(q)),
    (r"^(play)\s+.+", lambda q: search.handle_youtube(q)),
    # 2. Weather & Temperature
    (r"\b(weather|temperature|forecast|mausam)\b", lambda q: info.handle_weather(q)),
    # 3. News & Headlines
    (r"\b(news|headlines|updates|samachar)\b", lambda q: info.handle_news(q)),
    # 4. Time & Date
    (r"\b(what is the time|current time|what time is it|tell me the time|today's date|current date|what date is it|what day is today|samay|tarikh)\b", lambda q: info.handle_time(q)),
    # 5. Battery & Hardware Status
    (r"\b(battery|cpu|ram|memory|system status|hardware status)\b", lambda q: system.handle_system_status(q)),
    # 6. System Volume & Audio
    (r"\b(volume up|volume down|mute|unmute|increase volume|decrease volume)\b", lambda q: system.handle_volume(q)),
    # 7. WhatsApp Communication & Calls
    (r"\b(send|whatsapp)\b.*\b(message|msg)\b", lambda q: communication.handle_send_message(q)),
    (r"^(whatsapp)\s+.+", lambda q: communication.handle_send_message(q)),
    (r"\b(video call|voice call|call)\b", lambda q: communication.handle_call(q)),
    # 8. Open / Launch Applications & Websites
    (r"\b(open|launch|start)\b", lambda q: open_close.handle_open(q)),
    # 9. Close / Terminate Applications
    (r"\b(close|terminate|kill|exit|quit)\b", lambda q: open_close.handle_close(q)),
    # 10. Public IP
    (r"\b(my ip|ip address|public ip)\b", lambda q: info.handle_ip(q)),
    # 11. Internet Speed & Latency
    (r"\b(internet speed|speed test|ping|connection speed)\b", lambda q: system.handle_speed_test(q)),
    # 12. Workstation Lock
    (r"\b(lock workstation|lock screen|lock pc|lock computer)\b", lambda q: system.handle_lock(q)),
    # 13. Google Search
    (r"\b(google search|search on google|search google for|search for|google)\b", lambda q: search.handle_search(q)),
    # 14. Wikipedia information
    (r"\b(who is|who was|what is|what was|tell me about|explain|information about|wikipedia)\b", lambda q: search.handle_wikipedia(q)),
]


def route(query: str, db_path: str | None = None) -> str:
    """Classify user query via regex intent table and dispatch to matching handler.

    If no regex pattern matches, falls back to the conversational LLM.
    Logs every interaction in the command history database.
    """
    if not query or not query.strip():
        return "I am ready for your command, sir."

    normalized = query.strip()
    response = ""

    for pattern, handler in INTENT_TABLE:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            logger.info("Matched intent pattern '%s' for query: '%s'", pattern, normalized)
            try:
                response = handler(normalized)
            except Exception as exc:
                logger.error("Intent handler execution error for '%s': %s", normalized, exc)
                response = f"An error occurred while executing your request: {exc}"
            break

    if not response:
        # LLM fallback for general conversation
        logger.info("No intent matched. Routing to LLM fallback for query: '%s'", normalized)
        try:
            response = chat.llm_fallback(normalized)
        except Exception as exc:
            logger.error("LLM fallback failed: %s", exc)
            response = "I am at your service, sir. How else may I assist you?"

    # Log command and response to SQLite
    try:
        log_command(normalized, response, db_path=db_path)
    except Exception as exc:
        logger.warning("Failed to log command history: %s", exc)

    return response
