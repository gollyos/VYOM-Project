"""
Social Media Incoming Message Interceptor & Stylized Auto-Responder.
Intercepts incoming messages from WhatsApp, Telegram, Instagram, Discord, LinkedIn, Email;
Provides proactive voice notification to the Boss in normal mode;
Respects Focus Mode by handling silently without audio interruptions;
Generates responses in Gunjan's authentic personal Hinglish style.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class SocialMessage:
    platform: str  # "whatsapp" | "telegram" | "instagram" | "discord" | "linkedin" | "email"
    sender_name: str
    sender_handle: str
    content: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SocialMessageDecision:
    action: str  # "ask_boss" | "auto_reply" | "quiet_queue" | "ignore"
    spoken_prompt: str | None
    suggested_reply: str
    is_focus_mode: bool
    platform: str
    sender_name: str


class SocialResponderService:
    def __init__(self, owner_name: str = "Gunjan"):
        self.owner_name = owner_name
        self.message_history: list[SocialMessage] = []
        self.queued_in_focus: list[SocialMessage] = []

    def get_short_preview(self, content: str, max_chars: int = 55) -> str:
        cleaned = " ".join(content.split())
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[:max_chars - 3] + "..."

    def generate_stylized_reply(
        self,
        message: SocialMessage,
        *,
        custom_instructions: str = "",
        in_focus_mode: bool = False,
    ) -> str:
        """Generates authentic stylized response matching Gunjan's personal tone."""
        if in_focus_mode:
            return f"Hey, abhi ek important focus session chal raha hai. Free hote hi connect karta hu!"

        text = message.content.lower().strip()

        # Common intent heuristics
        if any(w in text for w in ("kaha ho", "where are you", "avail")):
            return "Main abhi desk pe hu aur project pe kaam kar raha hu. Batao kya hua?"
        elif any(w in text for w in ("urgent", "call", "emergency")):
            return "Haan bolo bhai, sab theek hai na? Kya help chahiye?"
        elif any(w in text for w in ("price", "cost", "quote", "charges")):
            return "Hey! Scope details share kar do, main review karke best quote bhejta hu."
        elif any(w in text for w in ("meeting", "call fix", "schedule", "kal mile")):
            return "Sure! Kal afternoon 3 baje slot perfect rahega. Kya ye time suit karega?"
        elif any(w in text for w in ("hi", "hello", "hey", "hlo")):
            return f"Hey {message.sender_name.split()[0]}! Kaise ho bhai? Batao kaise help karu?"
        else:
            return f"Got it {message.sender_name.split()[0]}! Main isko check karke turant update deta hu."

    def process_incoming(
        self,
        message: SocialMessage,
        *,
        is_focus_mode: bool = False,
        auto_pilot: bool = False,
    ) -> SocialMessageDecision:
        """Processes incoming social message with Focus Mode awareness."""
        self.message_history.append(message)
        preview = self.get_short_preview(message.content)
        first_name = message.sender_name.split()[0] if message.sender_name else "Someone"

        # 1. If in Focus Mode -> Never speak or interrupt boss!
        if is_focus_mode:
            self.queued_in_focus.append(message)
            suggested = self.generate_stylized_reply(message, in_focus_mode=True)
            return SocialMessageDecision(
                action="quiet_queue" if not auto_pilot else "auto_reply",
                spoken_prompt=None,  # No voice interruption in focus mode!
                suggested_reply=suggested,
                is_focus_mode=True,
                platform=message.platform,
                sender_name=message.sender_name,
            )

        # 2. Normal Mode -> Voice Alert + Ask Boss permission
        suggested = self.generate_stylized_reply(message, in_focus_mode=False)
        spoken_prompt = f"Boss, {message.platform.capitalize()} pe {first_name} ka message aaya hai: '{preview}'. Kya main iska answer kar doon?"

        return SocialMessageDecision(
            action="ask_boss" if not auto_pilot else "auto_reply",
            spoken_prompt=spoken_prompt,
            suggested_reply=suggested,
            is_focus_mode=False,
            platform=message.platform,
            sender_name=message.sender_name,
        )
