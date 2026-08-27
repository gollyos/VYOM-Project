"""Persona module for VYOM."""

from .manager import PersonaManager, get_persona_manager
from .schemas import (
    ASSISTANT_JARVIS_INSTRUCTION,
    COMPANION_GIRLFRIEND_INSTRUCTION,
    PERSONA_CATALOG,
    PersonaDefinition,
    PersonaId,
)

__all__ = [
    "PersonaId",
    "PersonaDefinition",
    "PERSONA_CATALOG",
    "PersonaManager",
    "get_persona_manager",
    "COMPANION_GIRLFRIEND_INSTRUCTION",
    "ASSISTANT_JARVIS_INSTRUCTION",
]
