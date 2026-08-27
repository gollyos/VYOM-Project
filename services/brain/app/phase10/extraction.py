from __future__ import annotations

import re

COMMON_NAME_ALIASES = {
    "bitcoin": "BTC", "ethereum": "ETH", "apple": "AAPL", "nvidia": "NVDA",
    "tesla": "TSLA", "microsoft": "MSFT", "google": "GOOGL", "alphabet": "GOOGL",
    "amazon": "AMZN", "meta": "META", "netflix": "NFLX",
}
STOPWORDS = {
    "FOR", "ON", "MY", "THE", "A", "AN", "TO", "OF", "IN", "AT", "IT", "IS", "PAPER",
    # Assistant wake words / command scaffolding are not market symbols.
    # Without this guard, "VYOM, create ... for AAPL" queried Yahoo for
    # VYOM and the real voice-style workflow failed before risk checking.
    "VYOM", "HEY", "BRO", "CREATE", "MAKE", "SETUP", "TRADE", "BUY", "SELL",
}
TICKER_PATTERN = re.compile(r"\b[A-Z]{2,5}\b")
WATCHLIST_NAME_PATTERN = re.compile(r"\b([A-Za-z][A-Za-z0-9 _-]{1,30})\s+watchlist\b", re.IGNORECASE)


def extract_symbol(text: str) -> str | None:
    lowered = text.lower()
    for name, ticker in COMMON_NAME_ALIASES.items():
        if name in lowered:
            return ticker
    for token in TICKER_PATTERN.findall(text):
        if token not in STOPWORDS:
            return token
    return None


def extract_watchlist_name(text: str) -> str:
    match = WATCHLIST_NAME_PATTERN.search(text)
    if match:
        return match.group(1).strip().title() + " Watchlist" if "watchlist" not in match.group(1).lower() else match.group(1).strip().title()
    return "Default"


def extract_percentage(text: str, *, default: float) -> float:
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(?:%|percent(?:age)?|per\s*cent)\b",
        text,
        re.IGNORECASE,
    )
    return float(match.group(1)) if match else default
