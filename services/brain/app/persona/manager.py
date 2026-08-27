"""Persona Manager for VYOM.

Handles runtime switching, persistence, and dynamic prompting for active personas.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from .schemas import PERSONA_CATALOG, PersonaDefinition, PersonaId

logger = logging.getLogger(__name__)

DEFAULT_STATE_PATH = Path("services/brain/data/persona_state.json")


class PersonaManager:
    """Singleton/per-brain persona manager."""

    def __init__(self, state_path: Path | None = None) -> None:
        self.state_path = state_path or DEFAULT_STATE_PATH
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._active_id: PersonaId = PersonaId.ASSISTANT_JARVIS
        self._load()

    def _load(self) -> None:
        if self.state_path.exists():
            try:
                data = json.loads(self.state_path.read_text(encoding="utf-8"))
                saved_id = data.get("active_persona")
                if saved_id in PERSONA_CATALOG:
                    self._active_id = PersonaId(saved_id)
            except Exception as e:
                logger.warning(f"Could not load persona state: {e}")

    def _save(self) -> None:
        try:
            self.state_path.write_text(
                json.dumps({"active_persona": self._active_id.value}, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.warning(f"Could not persist persona state: {e}")

    @property
    def active_id(self) -> PersonaId:
        return self._active_id

    @property
    def active_persona(self) -> PersonaDefinition:
        return PERSONA_CATALOG[self._active_id]

    def set_persona(self, persona_id: PersonaId | str) -> PersonaDefinition:
        """Switch active persona."""
        if isinstance(persona_id, str):
            try:
                persona_id = PersonaId(persona_id)
            except ValueError:
                # Fuzzy fallback matching
                if "girl" in persona_id.lower() or "maya" in persona_id.lower() or "companion" in persona_id.lower():
                    persona_id = PersonaId.COMPANION_GIRLFRIEND
                else:
                    persona_id = PersonaId.ASSISTANT_JARVIS

        if persona_id not in PERSONA_CATALOG:
            raise ValueError(f"Unknown persona: {persona_id}")

        self._active_id = persona_id
        self._save()
        logger.info(f"Switched active persona to: {self.active_persona.name}")
        return self.active_persona

    def list_personas(self) -> list[dict[str, Any]]:
        """List all available personas and indicate which one is currently active."""
        return [
            {
                "id": p.id.value,
                "name": p.name,
                "tagline": p.tagline,
                "voice": p.voice,
                "gender": p.gender,
                "care_mode": p.care_mode,
                "is_active": p.id == self._active_id,
            }
            for p in PERSONA_CATALOG.values()
        ]

    def detect_switch_request(self, user_request: str) -> PersonaId | None:
        """Detect if the user prompt is asking to switch persona."""
        text = user_request.lower().strip()
        
        # Check girlfriend / Maya mode
        girlfriend_triggers = [
            r"girlfriend mode", r"companion mode", r"maya mode",
            r"girlfriend ban jao", r"maya ban jao", r"girlfriend ban jao",
            r"switch to girlfriend", r"switch to maya", r"companion ban jao",
            r"be my girlfriend",
        ]
        if any(re.search(pat, text) for pat in girlfriend_triggers):
            return PersonaId.COMPANION_GIRLFRIEND

        # Check assistant / jarvis mode
        jarvis_triggers = [
            r"assistant mode", r"jarvis mode", r"executive mode",
            r"chief of staff", r"jarvis ban jao", r"assistant ban jao",
            r"switch to jarvis", r"switch to assistant", r"professional mode",
        ]
        if any(re.search(pat, text) for pat in jarvis_triggers):
            return PersonaId.ASSISTANT_JARVIS

        return None


# Global singleton instance
_GLOBAL_MANAGER: PersonaManager | None = None


def get_persona_manager() -> PersonaManager:
    global _GLOBAL_MANAGER
    if _GLOBAL_MANAGER is None:
        _GLOBAL_MANAGER = PersonaManager()
    return _GLOBAL_MANAGER
