from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class InputVerificationReport:
    verified: bool
    reasons: list[str] = field(default_factory=list)


class InputActionVerifier:
    """A mouse click or keystroke is not evidence of success by itself.
    Compares an expected post-action condition (a value that changed, a
    window title now visible, a file that now exists) against an
    observed result the caller supplies -- act, then observe, then
    confirm."""

    def verify_value_changed(self, before: str, after: str) -> InputVerificationReport:
        if before == after:
            return InputVerificationReport(False, ["No observable change after the input action"])
        return InputVerificationReport(True)

    def verify_condition(self, description: str, condition: bool) -> InputVerificationReport:
        return InputVerificationReport(condition, [] if condition else [f"Expected condition not met: {description}"])
