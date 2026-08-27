"""Built-in Edge-TTS Voice Synthesis Tool for VYOM.

Provides high-quality, zero-API-key, in-process neural text-to-speech audio
generation using Microsoft Edge TTS (edge-tts). Supports natural Hindi, Hinglish,
and English voices without any shell or terminal popups.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult, ToolStatus

logger = logging.getLogger(__name__)

# Default natural voices for VYOM
DEFAULT_VOICES = {
    "hi": "hi-IN-SwaraNeural",        # Hindi / Hinglish female (natural, expressive)
    "hi-male": "hi-IN-MadhurNeural",   # Hindi / Hinglish male
    "en-in": "en-IN-NeerjaNeural",     # Indian English female
    "en-us": "en-US-AriaNeural",       # US English female
    "en-gb": "en-GB-SoniaNeural",      # British English female
}


def detect_voice_for_text(text: str, preferred_gender: str = "female") -> str:
    """Intelligently pick an appropriate voice for Hindi/Hinglish vs English."""
    # Check for Devanagari Unicode block
    has_devanagari = bool(re.search(r"[\u0900-\u097F]", text))
    
    # Check for common Hinglish keywords
    hinglish_words = {"karo", "karna", "hoga", "hain", "karo", "bhai", "namaste", "shukriya", "achha", "theek"}
    words = set(re.findall(r"\b\w+\b", text.lower()))
    is_hinglish = bool(words & hinglish_words)

    if has_devanagari or is_hinglish:
        return DEFAULT_VOICES["hi-male"] if preferred_gender == "male" else DEFAULT_VOICES["hi"]
    return DEFAULT_VOICES["en-in"]


class EdgeTTSTool(BaseTool):
    """Zero-key Neural Speech Synthesis tool."""

    metadata = ToolMetadata(
        name="edge_tts",
        description=(
            "Generate high-quality neural voice audio (MP3) from text using Edge-TTS. "
            "Supports Hindi, Hinglish, Indian English, and international voices without API keys. "
            "Actions: synthesize, speak, list_voices."
        ),
        category="media",
        required_permissions=[PermissionLevel.L0],
        risk_level="low",
    )

    def __init__(self, output_dir: Path | None = None) -> None:
        self.output_dir = output_dir or Path("services/brain/data/audio")
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L0

    async def execute(self, inputs: dict[str, Any], context: ToolContext | None = None) -> ToolResult:
        import edge_tts

        action = str(inputs.get("action", "synthesize")).strip().lower()
        text = str(inputs.get("text", "")).strip()

        if action in ("synthesize", "speak"):
            if not text:
                raise ToolValidationError("text is required for speech synthesis")

            gender = str(inputs.get("gender", "female")).strip().lower()
            voice = str(inputs.get("voice", "")).strip() or detect_voice_for_text(text, preferred_gender=gender)
            rate = str(inputs.get("rate", "+0%")).strip()
            pitch = str(inputs.get("pitch", "+0Hz")).strip()

            output_file = inputs.get("output_path")
            if output_file:
                target_path = Path(output_file).resolve()
            else:
                import hashlib
                import time
                digest = hashlib.sha256(f"{text}|{voice}|{time.time()}".encode()).hexdigest()[:12]
                target_path = (self.output_dir / f"vyom_speech_{digest}.mp3").resolve()

            target_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                communicate = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch)
                await communicate.save(str(target_path))
            except Exception as e:
                return ToolResult.failed(
                    f"Edge-TTS synthesis failed: {str(e)}",
                    error=str(e),
                )

            size_bytes = target_path.stat().st_size if target_path.exists() else 0
            summary = f"Synthesized {len(text)} characters to {target_path.name} using {voice}."
            evidence = EvidenceItem(
                type="tts_audio_generated",
                summary=summary,
                data={
                    "file_path": str(target_path),
                    "voice": voice,
                    "size_bytes": size_bytes,
                    "text_sample": text[:100],
                },
            )

            return ToolResult.completed(
                summary,
                output={
                    "path": str(target_path),
                    "voice": voice,
                    "size_bytes": size_bytes,
                    "duration_estimate_sec": max(1.0, round(len(text.split()) / 2.5, 1)),
                },
                evidence=[evidence],
            )

        elif action == "list_voices":
            voices = await edge_tts.list_voices()
            popular_voices = [
                {"Name": v["Name"], "ShortName": v["ShortName"], "Gender": v["Gender"], "Locale": v["Locale"]}
                for v in voices
                if v.get("Locale", "").startswith(("hi-", "en-IN", "en-US", "en-GB"))
            ]
            return ToolResult.completed(
                f"Found {len(popular_voices)} top voices.",
                output={"voices": popular_voices},
            )

        raise ToolValidationError(f"Unsupported action '{action}' for EdgeTTSTool")
