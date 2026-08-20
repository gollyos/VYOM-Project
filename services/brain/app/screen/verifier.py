from __future__ import annotations

from dataclasses import dataclass, field

from .visual_context import ScreenObservation


@dataclass
class ScreenVerificationReport:
    verified: bool
    reasons: list[str] = field(default_factory=list)


class ScreenVerifier:
    """Mouse/keyboard/app actions are not evidence of success by
    themselves. Verifies an observed screen state matches an expected
    application/window after a desktop action (e.g. opening a project)."""

    def verify(
        self,
        observation: ScreenObservation,
        *,
        expected_application: str | None = None,
        expected_window_contains: str | None = None,
    ) -> ScreenVerificationReport:
        reasons: list[str] = []
        if expected_application and observation.active_application != expected_application:
            reasons.append(f"Expected application '{expected_application}', observed '{observation.active_application}'")
        if expected_window_contains and (
            not observation.active_window or expected_window_contains.lower() not in observation.active_window.lower()
        ):
            reasons.append(f"Expected window containing '{expected_window_contains}', observed '{observation.active_window}'")
        return ScreenVerificationReport(verified=not reasons, reasons=reasons)
