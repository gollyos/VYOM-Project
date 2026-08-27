"""Conversational LLM fallback and chat responses for JARVIS Desktop Assistant.

Handles general conversation and chitchat when no deterministic action intent matches.
Supports Gemini, OpenAI, Anthropic, Ollama, and local rule-based fallbacks.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Short-term conversational memory
_chat_history: list[dict[str, str]] = []
MAX_TURNS = 6

SYSTEM_PROMPT = (
    "You are JARVIS, an advanced personal AI desktop assistant. "
    "Respond concisely, politely, and intelligently. "
    "Keep responses within 1-3 sentences. "
    "You are helpful and address the user with respect ('sir' or polite tone). "
    "You understand both English and Hinglish naturally."
)


def _call_gemini(query: str, api_key: str) -> str | None:
    """Call Google Gemini API."""
    try:
        import requests

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        contents = []
        for msg in _chat_history[-MAX_TURNS:]:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        contents.append({"role": "user", "parts": [{"text": f"{SYSTEM_PROMPT}\nUser: {query}"}]})

        resp = requests.post(url, json={"contents": contents}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            return text.strip()
    except Exception as exc:
        logger.warning("Gemini LLM call failed: %s", exc)
    return None


def _call_openai(query: str, api_key: str) -> str | None:
    """Call OpenAI API."""
    try:
        import requests

        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        for msg in _chat_history[-MAX_TURNS:]:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": query})

        resp = requests.post(
            url,
            headers=headers,
            json={"model": "gpt-4o-mini", "messages": messages, "max_tokens": 150},
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        logger.warning("OpenAI LLM call failed: %s", exc)
    return None


def _call_ollama(query: str, host: str = "http://localhost:11434") -> str | None:
    """Call local Ollama instance."""
    try:
        import requests

        url = f"{host.rstrip('/')}/api/generate"
        prompt = f"{SYSTEM_PROMPT}\n\nUser: {query}\nJARVIS:"
        resp = requests.post(url, json={"model": "llama3.2", "prompt": prompt, "stream": False}, timeout=10)
        if resp.status_code == 200:
            return resp.json().get("response", "").strip()
    except Exception as exc:
        logger.warning("Ollama call failed: %s", exc)
    return None


def _rule_fallback(query: str) -> str:
    """Polite rule-based conversational replies when no external LLM is configured."""
    q = query.lower()
    if any(w in q for w in ["hello", "hi", "hey", "namaste", "good morning", "good evening"]):
        return "Hello sir! How may I assist you today?"
    if any(w in q for w in ["how are you", "kaise ho", "how's it going"]):
        return "I am operating at full capacity, sir. Systems are all green. How can I help you?"
    if any(w in q for w in ["who are you", "what is your name", "kya ho"]):
        return "I am JARVIS, your personal autonomous desktop assistant."
    if any(w in q for w in ["thank you", "thanks", "dhanyawad", "shukriya"]):
        return "Always at your service, sir."
    if any(w in q for w in ["bye", "goodbye", "alvida", "see you"]):
        return "Goodbye sir! Have a productive day ahead."
    return f"Understood, sir. I have processed '{query}'."


def llm_fallback(query: str) -> str:
    """Process open-ended query via available LLM provider or rule fallback."""
    clean_q = query.strip()
    if not clean_q:
        return "Yes sir, I am listening."

    gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")
    ollama_host = os.getenv("OLLAMA_HOST")

    reply = None
    if gemini_key:
        reply = _call_gemini(clean_q, gemini_key)
    elif openai_key:
        reply = _call_openai(clean_q, openai_key)
    elif ollama_host:
        reply = _call_ollama(clean_q, ollama_host)

    if not reply:
        reply = _rule_fallback(clean_q)

    # Record to local memory
    _chat_history.append({"role": "user", "content": clean_q})
    _chat_history.append({"role": "assistant", "content": reply})

    return reply
