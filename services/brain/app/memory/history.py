from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone


# VYOM currently runs for the user in India.  Store timestamps remain UTC;
# spoken calendar dates are interpreted in the user's local day so a
# conversation just after midnight is not filed under the previous date.
USER_TIMEZONE = timezone(timedelta(hours=5, minutes=30))

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2,
    "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

_HISTORY_MARKERS = (
    "what did i tell you", "what did i say", "what have i told you",
    "do you remember what i told", "what did we discuss",
    "maine tumhe kya bataya", "maine tumko kya bataya", "maine kya bataya",
    "maine tumhe kya bola", "maine kya bola", "humne kya discuss",
    "humne kya baat", "yaad hai maine", "purani baat",
    "मैंने तुम्हें क्या बताया", "मैंने क्या बताया", "मैंने क्या कहा",
    "हमने क्या बात", "याद है मैंने",
)


@dataclass(frozen=True)
class HistoricalMemoryRequest:
    subject: str = ""
    created_after: datetime | None = None
    created_before: datetime | None = None
    local_date: date | None = None


def is_historical_recall(text: str) -> bool:
    lowered = (text or "").strip().lower()
    if any(marker in lowered for marker in _HISTORY_MARKERS):
        return True
    parsed = parse_historical_memory_request(text)
    return parsed.local_date is not None and any(
        marker in lowered
        for marker in ("remember", "memory", "tell", "told", "said", "bataya", "bola", "yaad", "बताया", "कहा", "याद")
    )


def _parse_explicit_date(text: str) -> tuple[date | None, tuple[int, int] | None]:
    # ISO is unambiguous and is the preferred form in the UI/API.
    match = re.search(r"\b(20\d{2}|19\d{2})[-/.](0?[1-9]|1[0-2])[-/.](0?[1-9]|[12]\d|3[01])\b", text)
    if match:
        try:
            return date(int(match.group(1)), int(match.group(2)), int(match.group(3))), match.span()
        except ValueError:
            return None, None

    # Spoken Indian dates are normally day-month-year.
    match = re.search(r"\b(0?[1-9]|[12]\d|3[01])[-/.](0?[1-9]|1[0-2])[-/.](20\d{2}|19\d{2})\b", text)
    if match:
        try:
            return date(int(match.group(3)), int(match.group(2)), int(match.group(1))), match.span()
        except ValueError:
            return None, None

    month_names = "|".join(sorted(_MONTHS, key=len, reverse=True))
    match = re.search(
        rf"\b(0?[1-9]|[12]\d|3[01])\s+({month_names})\s*,?\s*(20\d{{2}}|19\d{{2}})\b",
        text,
        re.IGNORECASE,
    )
    if match:
        try:
            return date(int(match.group(3)), _MONTHS[match.group(2).lower()], int(match.group(1))), match.span()
        except ValueError:
            return None, None

    match = re.search(
        rf"\b({month_names})\s+(0?[1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\s*,?\s*(20\d{{2}}|19\d{{2}})\b",
        text,
        re.IGNORECASE,
    )
    if match:
        try:
            return date(int(match.group(3)), _MONTHS[match.group(1).lower()], int(match.group(2))), match.span()
        except ValueError:
            return None, None
    return None, None


def _subject_from(text_without_date: str) -> str:
    cleaned = re.sub(r"[?।]", " ", text_without_date).strip()
    patterns = (
        r"\bclient\s+(.+?)\s+ke\s+ba(?:are|re)\s+(?:me|mein)\b",
        r"\bproject\s+(.+?)\s+ke\s+ba(?:are|re)\s+(?:me|mein)\b",
        r"\b(?:about|regarding)\s+(.+)$",
        r"(?:क्लाइंट|प्रोजेक्ट)\s+(.+?)\s+के\s+बारे\s+में",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            subject = match.group(1).strip(" ,.-")
            subject = re.sub(
                r"\s+(?:what did i tell you|kya bataya tha|kya bola tha|क्या बताया था).*$",
                "",
                subject,
                flags=re.IGNORECASE,
            ).strip(" ,.-")
            return subject[:160]
    return ""


def parse_historical_memory_request(
    text: str, *, now: datetime | None = None
) -> HistoricalMemoryRequest:
    original = text or ""
    lowered = original.lower()
    selected, span = _parse_explicit_date(original)
    reference_now = (now or datetime.now(USER_TIMEZONE)).astimezone(USER_TIMEZONE)

    if selected is None:
        if re.search(r"\b(yesterday|kal)\b|कल", lowered):
            selected = reference_now.date() - timedelta(days=1)
        elif re.search(r"\b(today|aaj)\b|आज", lowered):
            selected = reference_now.date()

    without_date = original
    if span:
        without_date = original[:span[0]] + " " + original[span[1]:]
    without_date = re.sub(r"\b(?:today|yesterday|aaj|kal)\b|आज|कल", " ", without_date, flags=re.IGNORECASE)
    subject = _subject_from(without_date)

    if selected is None:
        return HistoricalMemoryRequest(subject=subject)
    start_local = datetime.combine(selected, time.min, tzinfo=USER_TIMEZONE)
    end_local = start_local + timedelta(days=1)
    return HistoricalMemoryRequest(
        subject=subject,
        created_after=start_local.astimezone(timezone.utc),
        created_before=end_local.astimezone(timezone.utc),
        local_date=selected,
    )
