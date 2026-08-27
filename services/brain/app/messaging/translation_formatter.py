"""
Multilingual Translation & Message Formatter for VYOM.
Allows the owner (Gunjan) to dictate in Hindi/Hinglish and automatically
translates, polishes tone, and dispatches professional English messages
to WhatsApp, Email, Telegram, or LinkedIn.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class TranslatedMessage:
    original_text: str
    translated_text: str
    target_language: str = "en"
    tone: str = "professional"  # "professional" | "polite" | "casual"
    recipient: str | None = None
    platform: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class TranslationFormatterService:
    """Parses dictation, extracts platform and recipient, translates Hindi/Hinglish,
    and formats into polished English ready for dispatch."""

    # Common Hinglish/Hindi translation mappings & contextual phrase rules
    PHRASE_PATTERNS: list[tuple[re.Pattern, str]] = [
        (re.compile(r"meeting\s+(?:kal\s+)?(\d+)\s*(?:baje|pm|am)?\s*(?:pe\s+)?shift\s+ho\s+gayi\s+hai", re.I),
         r"The meeting has been rescheduled to tomorrow at \1:00 PM. Please let me know if this time works for you."),
        (re.compile(r"proposal\s+check\s+karke\s+(?:batao|bataiye)", re.I),
         "Please review the attached proposal and share your thoughts whenever convenient."),
        (re.compile(r"main\s+abhi\s+thoda\s+busy\s+hu\s+thodi\s+der\s+me\s+call\s+karta\s+hu", re.I),
         "I am currently tied up in a meeting. I will call you back shortly."),
        (re.compile(r"payment\s+confirm\s+ho\s+(?:gaya|gayi)\s+hai", re.I),
         "We have received and confirmed the payment. Thank you!"),
        (re.compile(r"design\s+file\s+share\s+kar\s+di\s+hai", re.I),
         "The updated design files have been shared for your review."),
        (re.compile(r"kal\s+milte\s+hain", re.I),
         "Let us connect tomorrow as scheduled."),
        (re.compile(r"details\s+bhej\s+di\s+hain", re.I),
         "I have forwarded the complete details to you."),
        (re.compile(r"kaam\s+complete\s+ho\s+gaya\s+hai", re.I),
         "The task has been completed successfully."),
    ]

    @classmethod
    def parse_dictation_request(cls, text: str) -> dict[str, Any]:
        """Extracts recipient, platform, and content from voice dictation."""
        platform = None
        recipient = None
        lower = text.lower()

        # 1. Identify platform
        if "whatsapp" in lower:
            platform = "whatsapp"
        elif "email" in lower or "mail" in lower:
            platform = "email"
        elif "telegram" in lower:
            platform = "telegram"
        elif "linkedin" in lower:
            platform = "linkedin"

        # 2. Extract recipient name
        recipient_match = re.search(r"(?:bhai\s+|^)([a-zA-Z]+)\s+ko\b", text, re.I)
        if recipient_match:
            candidate = recipient_match.group(1).capitalize()
            if candidate.lower() not in {"sab", "kisi", "isko", "usko", "mujhe", "tum"}:
                recipient = candidate

        # 3. Extract tone preference
        tone = "professional"
        if any(w in lower for w in ("casual", "friendly", "informal")):
            tone = "casual"
        elif any(w in lower for w in ("polite", "sweet", "respectful")):
            tone = "polite"

        return {
            "platform": platform or "whatsapp",
            "recipient": recipient or "there",
            "tone": tone,
            "raw_query": text,
        }

    @classmethod
    def translate_and_format(
        cls,
        text: str,
        *,
        recipient: str | None = None,
        tone: str = "professional",
        target_lang: str = "en",
    ) -> TranslatedMessage:
        """Translates Hindi/Hinglish text into structured, polished English."""
        cleaned = text.strip()
        translated = None

        # Check matched patterns
        for pattern, replacement in cls.PHRASE_PATTERNS:
            if pattern.search(cleaned):
                translated = pattern.sub(replacement, cleaned)
                break

        if not translated:
            # Fallback formatting: capitalize and polish
            translated = cleaned
            # Common word replacements
            replacements = {
                "bhai": "mate",
                "ho gaya": "completed",
                "kardo": "please do",
                "bhej do": "please send",
                "kal": "tomorrow",
                "aaj": "today",
            }
            for k, v in replacements.items():
                translated = re.sub(rf"\b{k}\b", v, translated, flags=re.I)

        # Add polite salutation if recipient is provided
        if recipient and recipient.lower() not in {"there", "someone"}:
            salutation = f"Hi {recipient}," if tone != "formal" else f"Dear {recipient},"
            if not translated.startswith(("Hi ", "Dear ", "Hello ")):
                translated = f"{salutation}\n\n{translated}"

        return TranslatedMessage(
            original_text=text,
            translated_text=translated,
            target_language=target_lang,
            tone=tone,
            recipient=recipient,
        )
