from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

PARTY_SIZE_PATTERN = re.compile(r"for (\d+)\s+people", re.IGNORECASE)
TIME_PATTERN = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s?(am|pm)\b", re.IGNORECASE)
CLIENT_FOR_PATTERN = re.compile(r"\b(?:for|to) ([A-Z][A-Za-z0-9&.'-]*)")
CATEGORY_KEYWORDS = {
    "restaurant": "restaurant",
    "hotel": "hotel",
    "appointment": "appointment",
    "meeting room": "meeting",
}


def extract_party_size(text: str) -> int | None:
    match = PARTY_SIZE_PATTERN.search(text)
    return int(match.group(1)) if match else None


def extract_time(text: str) -> str | None:
    match = TIME_PATTERN.search(text)
    if not match:
        return None
    hour, minute, meridiem = match.groups()
    return f"{int(hour):02d}:{minute or '00'} {meridiem.upper()}"


def extract_date(text: str, *, now: datetime | None = None) -> str | None:
    reference = now or datetime.now(timezone.utc)
    lowered = text.lower()
    if "tomorrow" in lowered:
        return (reference + timedelta(days=1)).date().isoformat()
    if "today" in lowered:
        return reference.date().isoformat()
    return None


def extract_booking_category(text: str) -> str | None:
    lowered = text.lower()
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in lowered:
            return category
    return None


def extract_client_name(text: str) -> str | None:
    match = CLIENT_FOR_PATTERN.search(text)
    return match.group(1) if match else None


def extract_research_topic(text: str, trigger_phrases: tuple[str, ...]) -> str:
    remaining = text
    for phrase in trigger_phrases:
        index = remaining.lower().find(phrase)
        if index != -1:
            remaining = remaining[index + len(phrase):]
    return remaining.strip(" .?!:") or text.strip()
