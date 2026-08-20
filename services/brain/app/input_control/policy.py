from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

SENSITIVE_FIELD_HINTS = (
    "password", "passwd", "mfa", "otp", "2fa", "verification code", "security code",
    "cvv", "card number", "credit card", "recovery phrase", "seed phrase", "private key", "pin",
)


class SensitiveInputBlockedError(Exception):
    """Raised when an input action would enter/submit a sensitive secret.
    The caller must pause and request user action instead of proceeding."""


class EmergencyPauseActiveError(Exception):
    """Raised when an input action is attempted while emergency pause is
    engaged. Safety stop always takes priority over normal execution."""


class EmergencyPauseState:
    """Global emergency-pause flag. A configured global shortcut, tray
    action, or the voice phrase 'VYOM stop' engages this; every bounded
    input action must check it before executing (see
    docs/DESKTOP_SECURITY.md)."""

    def __init__(self) -> None:
        self.paused = False

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def require_not_paused(self) -> None:
        if self.paused:
            raise EmergencyPauseActiveError("Desktop input automation is emergency-paused")


@dataclass
class InputActionLogEntry:
    action: str
    target: str
    context: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class InputSafetyPolicy:
    """Bounded, auditable, context-required input automation policy. Every
    mouse/keyboard fallback action passes through this policy first:
    known target required, sensitive fields blocked, every action logged,
    and the whole sequence duration/step-bounded."""

    def __init__(
        self,
        max_actions_per_sequence: int = 25,
        max_duration_seconds: float = 30.0,
        emergency_pause: EmergencyPauseState | None = None,
    ):
        self.max_actions_per_sequence = max_actions_per_sequence
        self.max_duration_seconds = max_duration_seconds
        self.emergency_pause = emergency_pause or EmergencyPauseState()
        self.log: list[InputActionLogEntry] = []

    @staticmethod
    def is_sensitive_field(field_label: str) -> bool:
        lowered = field_label.lower()
        return any(hint in lowered for hint in SENSITIVE_FIELD_HINTS)

    def require_safe_target(self, target: str) -> None:
        self.emergency_pause.require_not_paused()
        if not target or not target.strip():
            raise ValueError("Input automation requires a known target/context; refusing to act blindly")

    def require_not_sensitive(self, field_label: str, value: str) -> None:
        if self.is_sensitive_field(field_label):
            raise SensitiveInputBlockedError(
                f"'{field_label}' looks like a sensitive credential field; pausing for user action instead of auto-filling"
            )

    def check_sequence_bounds(self, planned_action_count: int) -> None:
        if planned_action_count > self.max_actions_per_sequence:
            raise ValueError(
                f"Planned input sequence ({planned_action_count} actions) exceeds the bounded maximum ({self.max_actions_per_sequence})"
            )

    def record(self, action: str, target: str, context: str) -> InputActionLogEntry:
        entry = InputActionLogEntry(action=action, target=target, context=context)
        self.log.append(entry)
        self.log = self.log[-500:]
        return entry
