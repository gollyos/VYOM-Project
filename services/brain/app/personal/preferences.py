from __future__ import annotations

import hashlib
import re

PREFERENCE_PATTERNS: list[tuple[re.Pattern, str, object]] = [
    (re.compile(r"avoid working after (\d{1,2})\s?(am|pm)?", re.IGNORECASE), "work_cutoff_hint", None),
    (re.compile(r"avoid working after midnight", re.IGNORECASE), "work_cutoff_time", "00:00"),
    (re.compile(r"mornings? work(s)? better", re.IGNORECASE), "energy_preference", "morning"),
    (re.compile(r"afternoons? work(s)? better", re.IGNORECASE), "energy_preference", "afternoon"),
    (re.compile(r"evenings? work(s)? better", re.IGNORECASE), "energy_preference", "evening"),
    (re.compile(r"prefer meetings? in the morning", re.IGNORECASE), "preferred_meeting_hours", "morning"),
    (re.compile(r"prefer meetings? in the afternoon", re.IGNORECASE), "preferred_meeting_hours", "afternoon"),
]


class PreferenceExtractor:
    """Deterministic, pattern-based extraction for common personal
    preference statements (rule 1/48) — no model call. Anything that
    doesn't match a known pattern is stored as a plain note rather than
    dropped, so the user's exact statement is never lost."""

    def extract(self, text: str) -> tuple[str, object]:
        for pattern, key, fixed_value in PREFERENCE_PATTERNS:
            match = pattern.search(text)
            if match:
                if key == "work_cutoff_hint":
                    hour = int(match.group(1))
                    meridiem = (match.group(2) or "").lower()
                    if meridiem == "pm" and hour != 12:
                        hour += 12
                    if meridiem == "am" and hour == 12:
                        hour = 0
                    return "work_cutoff_time", f"{hour:02d}:00"
                return key, fixed_value if fixed_value is not None else text.strip()
        slug = hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()[:10]
        return f"note:{slug}", text.strip()
