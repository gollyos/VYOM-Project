"""
Smart Professional Email Engine for VYOM.
Composes, customizes, and dispatches contextual business and personal emails
with structured greetings, clear value propositions, polite CTAs, and professional sign-offs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schemas import DraftRequest, EmailAddress


class SmartEmailComposer:
    def __init__(self, default_sender_name: str = "Gunjan", default_company: str = "VYOM"):
        self.default_sender_name = default_sender_name
        self.default_company = default_company

    def compose_email_content(
        self,
        recipient_name: str,
        context: str,
        *,
        tone: str = "professional",
        key_points: list[str] | None = None,
        cta: str = "",
        sender_name: str | None = None,
    ) -> str:
        sender = sender_name or self.default_sender_name
        first_name = recipient_name.split()[0] if recipient_name else "There"

        greeting = f"Dear {recipient_name}," if tone in {"professional", "proposal"} else f"Hi {first_name},"

        lines = [greeting, ""]

        if tone == "proposal":
            lines.append(f"Thank you for connecting regarding {context}. I am pleased to share our proposed solution outlined below:")
        elif tone == "followup":
            lines.append(f"I hope you are having a productive week. I am following up on our previous conversation regarding {context}.")
        elif tone == "urgent_update":
            lines.append(f"Please find below an urgent update regarding {context}:")
        elif tone == "casual_business":
            lines.append(f"Quick update on {context}:")
        else:  # professional
            lines.append(f"I am writing to update you regarding {context}.")

        lines.append("")

        if key_points:
            for pt in key_points:
                lines.append(f"• {pt}")
            lines.append("")

        if cta:
            lines.append(cta)
            lines.append("")
        else:
            lines.append("Please let me know if you have any questions or require any adjustments. Looking forward to your thoughts.")
            lines.append("")

        lines.append("Best regards,")
        lines.append(sender)
        if self.default_company:
            lines.append(self.default_company)

        return "\n".join(lines)

    def create_draft_request(
        self,
        to: list[str | EmailAddress],
        subject: str,
        recipient_name: str,
        context: str,
        *,
        tone: str = "professional",
        key_points: list[str] | None = None,
        cta: str = "",
        thread_id: str | None = None,
    ) -> DraftRequest:
        body = self.compose_email_content(
            recipient_name=recipient_name,
            context=context,
            tone=tone,
            key_points=key_points,
            cta=cta,
        )
        parsed_to = [
            item if isinstance(item, EmailAddress) else EmailAddress(address=str(item))
            for item in to
        ]
        return DraftRequest(
            to=parsed_to,
            subject=subject,
            body_text=body,
            thread_id=thread_id,
            metadata={"tone": tone, "generated_by": "SmartEmailComposer"},
        )
