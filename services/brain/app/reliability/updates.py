from __future__ import annotations

from enum import Enum


class UpdateStatus(str, Enum):
    """Update lifecycle states. Phase 12 deliberately ships only this
    foundation: there is no silent forced update and no self-update of
    a production core. See docs/UPDATE_POLICY.md."""

    AVAILABLE = "available"
    DOWNLOADED = "downloaded"
    READY = "ready"
    INSTALLED = "installed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


ALLOWED_TRANSITIONS: dict[UpdateStatus, set[UpdateStatus]] = {
    UpdateStatus.AVAILABLE: {UpdateStatus.DOWNLOADED},
    UpdateStatus.DOWNLOADED: {UpdateStatus.READY, UpdateStatus.FAILED},
    UpdateStatus.READY: {UpdateStatus.INSTALLED, UpdateStatus.FAILED},
    UpdateStatus.INSTALLED: {UpdateStatus.ROLLED_BACK},
    UpdateStatus.FAILED: set(),
    UpdateStatus.ROLLED_BACK: set(),
}


class UpdateStateMachine:
    """Tracks an update candidate through its lifecycle with explicit,
    user-visible transitions only."""

    def __init__(self):
        self.state = UpdateStatus.AVAILABLE

    def transition(self, target: UpdateStatus) -> UpdateStatus:
        if target not in ALLOWED_TRANSITIONS[self.state]:
            raise ValueError(f"Illegal update transition {self.state.value} -> {target.value}")
        self.state = target
        return self.state
