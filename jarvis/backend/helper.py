"""Helper and text parsing utilities for JARVIS Desktop Assistant.
"""

from __future__ import annotations

import re


def clean_query(text: str) -> str:
    """Clean and normalize input text."""
    if not text:
        return ""
    # Strip whitespace, lower case, collapse multiple spaces
    cleaned = re.sub(r"\s+", " ", text).strip().lower()
    return cleaned


def remove_words(text: str, words: list[str] | set[str]) -> str:
    """Remove target filler or trigger words from string using regex boundaries."""
    if not text:
        return ""
    result = text
    for word in sorted(words, key=len, reverse=True):
        pattern = rf"\b{re.escape(word.strip().lower())}\b"
        result = re.sub(pattern, " ", result, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", result).strip()


def extract_yt_term(query: str) -> str:
    """Extract song/video title from YouTube play commands."""
    normalized = clean_query(query)
    # Remove phrases like "play ... on youtube", "jarvis play", "song", "video", "on yt"
    fillers = [
        "play on youtube",
        "on youtube",
        "on yt",
        "play song",
        "play video",
        "play track",
        "can you play",
        "please play",
        "play",
        "jarvis",
        "vyom",
    ]
    term = remove_words(normalized, fillers)
    return term or "lofi beats"


def extract_search_term(query: str) -> str:
    """Extract the core search term from a Google search query."""
    normalized = clean_query(query)
    fillers = [
        "google search",
        "search on google",
        "search for",
        "search google for",
        "search",
        "google",
        "find information on",
        "find",
        "look up",
        "jarvis",
    ]
    return remove_words(normalized, fillers)


def extract_wikipedia_query(query: str) -> str:
    """Extract Wikipedia subject from questions like 'who is X', 'what is Y'."""
    normalized = clean_query(query)
    fillers = [
        "tell me about",
        "who is",
        "who was",
        "what is",
        "what was",
        "where is",
        "explain",
        "information about",
        "wikipedia search",
        "search wikipedia for",
        "on wikipedia",
        "wikipedia",
        "jarvis",
    ]
    return remove_words(normalized, fillers)


def extract_app_name(query: str) -> str:
    """Extract application or website name from 'open X' or 'close X' commands."""
    normalized = clean_query(query)
    fillers = [
        "open the application",
        "open application",
        "open app",
        "open website",
        "open site",
        "open",
        "launch",
        "start",
        "close the application",
        "close application",
        "close app",
        "close",
        "kill",
        "terminate",
        "exit",
        "quit",
        "jarvis",
    ]
    return remove_words(normalized, fillers)


def extract_contact_and_message(query: str) -> tuple[str, str]:
    """Parse contact name and optional message from WhatsApp commands.

    Examples:
      'send whatsapp message to John hello how are you' -> ('John', 'hello how are you')
      'send message to mom I will be late' -> ('mom', 'I will be late')
      'whatsapp Rahul let us meet' -> ('Rahul', 'let us meet')
    """
    normalized = clean_query(query)
    # Remove leading trigger
    cleaned = re.sub(
        r"^(jarvis\s+)?(please\s+)?(send\s+)?(a\s+)?(whatsapp\s+message|whatsapp|message)\s+(to\s+)?",
        "",
        normalized,
        flags=re.IGNORECASE,
    ).strip()

    if not cleaned:
        return ("", "")

    # Check for "that", "saying", "message" or first delimiter
    match = re.search(r"^(.*?)\s+(?:saying|that|message|msg)\s+(.*)$", cleaned, re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        msg = match.group(2).strip()
        return (name, msg)

    # If format is "to <name> <msg>", split first token as name if multiple words
    parts = cleaned.split(" ", 1)
    if len(parts) == 2:
        return (parts[0].strip(), parts[1].strip())
    return (cleaned, "")
