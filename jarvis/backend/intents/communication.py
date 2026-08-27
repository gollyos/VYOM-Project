"""Communication intent handlers: WhatsApp messaging and calling.
"""

from __future__ import annotations

import logging
import re
import time
import urllib.parse
import webbrowser

from jarvis.backend.db import find_contact_number
from jarvis.backend.helper import extract_contact_and_message

logger = logging.getLogger(__name__)


def clean_phone_number(number: str) -> str:
    """Normalize phone number to international E.164 format if possible."""
    cleaned = re.sub(r"[^\d+]", "", number)
    # If 10-digit Indian number without country code, add +91
    if len(cleaned) == 10 and not cleaned.startswith("+"):
        cleaned = "+91" + cleaned
    elif len(cleaned) == 12 and cleaned.startswith("91") and not cleaned.startswith("+"):
        cleaned = "+" + cleaned
    elif not cleaned.startswith("+") and cleaned:
        cleaned = "+" + cleaned
    return cleaned


def send_whatsapp_message(name_or_number: str, message: str) -> str:
    """Send WhatsApp message using pywhatkit or WhatsApp Web URL."""
    if not name_or_number:
        return "Please specify a contact name or phone number, sir."
    if not message:
        return f"What message would you like me to send to {name_or_number}, sir?"

    # Check database for contact number
    phone = find_contact_number(name_or_number)
    if not phone:
        # Check if argument itself is a numeric phone number
        if re.search(r"\d{7,}", name_or_number):
            phone = name_or_number
        else:
            return f"I could not find a contact number for '{name_or_number}' in your contacts database."

    target_number = clean_phone_number(phone)
    logger.info("Sending WhatsApp message to %s (%s)", name_or_number, target_number)

    try:
        import pywhatkit

        pywhatkit.sendwhatmsg_instantly(
            phone_no=target_number,
            message=message,
            wait_time=12,
            tab_close=False,
            close_time=3,
        )
        return f"WhatsApp message sent to {name_or_number}."
    except Exception as exc:
        logger.warning("pywhatkit instant message failed, opening web URL directly: %s", exc)
        encoded_msg = urllib.parse.quote_plus(message)
        url = f"https://web.whatsapp.com/send?phone={target_number}&text={encoded_msg}"
        webbrowser.open(url)
        return f"Opening WhatsApp Web chat with {name_or_number}."


def make_call(name_or_number: str, video: bool = False) -> str:
    """Initiate a WhatsApp voice or video call."""
    if not name_or_number:
        return "Please specify who you would like to call, sir."

    phone = find_contact_number(name_or_number)
    if not phone:
        if re.search(r"\d{7,}", name_or_number):
            phone = name_or_number
        else:
            return f"I could not find a contact number for '{name_or_number}'."

    target_number = clean_phone_number(phone)
    call_type = "video call" if video else "voice call"

    url = f"https://web.whatsapp.com/send?phone={target_number}"
    try:
        webbrowser.open(url)
        return f"Opening WhatsApp {call_type} session for {name_or_number}."
    except Exception as exc:
        logger.error("Failed to initiate WhatsApp call: %s", exc)
        return f"Could not initiate call to {name_or_number}: {exc}"


def handle_send_message(query: str) -> str:
    """Parse message query and dispatch WhatsApp message."""
    name, msg = extract_contact_and_message(query)
    if not name:
        return "Who would you like to message, sir?"
    if not msg:
        return f"What message should I send to {name}, sir?"
    return send_whatsapp_message(name, msg)


def handle_call(query: str) -> str:
    """Parse call query and initiate WhatsApp call."""
    is_video = "video" in query.lower()
    cleaned = re.sub(r"\b(make a|make|start|place|video|voice|call|to|on whatsapp|whatsapp|jarvis)\b", " ", query, flags=re.IGNORECASE)
    name = re.sub(r"\s+", " ", cleaned).strip()
    return make_call(name, video=is_video)
