"""Search intent handlers: Google, YouTube, and Wikipedia.
"""

from __future__ import annotations

import logging
import urllib.parse
import webbrowser

from jarvis.backend.helper import (
    extract_search_term,
    extract_wikipedia_query,
    extract_yt_term,
)

logger = logging.getLogger(__name__)


def handle_search(query: str) -> str:
    """Perform Google Web Search."""
    term = extract_search_term(query).strip()
    if not term:
        return "What would you like me to search for, sir?"

    encoded = urllib.parse.quote_plus(term)
    url = f"https://www.google.com/search?q={encoded}"
    try:
        webbrowser.open(url)
        return f"Here are the Google search results for {term}, sir."
    except Exception as exc:
        logger.error("Failed to open Google search: %s", exc)
        return f"Error executing Google search for {term}."


def handle_youtube(query: str) -> str:
    """Search and play audio/video on YouTube."""
    term = extract_yt_term(query).strip()
    if not term:
        term = "relaxing music"

    try:
        import pywhatkit

        pywhatkit.playonyt(term)
        return f"Playing {term} on YouTube, sir."
    except Exception as exc:
        logger.warning("pywhatkit.playonyt failed, falling back to direct browser URL: %s", exc)
        encoded = urllib.parse.quote_plus(term)
        url = f"https://www.youtube.com/results?search_query={encoded}"
        webbrowser.open(url)
        return f"Opening YouTube search for {term}, sir."


def handle_wikipedia(query: str) -> str:
    """Fetch concise summary from Wikipedia."""
    subject = extract_wikipedia_query(query).strip()
    if not subject:
        return "What topic would you like me to look up on Wikipedia, sir?"

    try:
        import wikipedia

        wikipedia.set_lang("en")
        summary = wikipedia.summary(subject, sentences=2, auto_suggest=True)
        return f"According to Wikipedia: {summary}"
    except Exception as exc:
        # Handle PageError or DisambiguationError
        logger.warning("Wikipedia query failed for %s: %s", subject, exc)
        try:
            import wikipedia

            results = wikipedia.search(subject, results=3)
            if results:
                summary = wikipedia.summary(results[0], sentences=2, auto_suggest=False)
                return f"According to Wikipedia regarding {results[0]}: {summary}"
        except Exception:
            pass
        return f"I could not find a clear Wikipedia entry for {subject}, sir."
