from __future__ import annotations

import json
from pathlib import Path

from .schemas import REQUIRED_STEPS, SKIPPABLE_STEPS, SetupState, SetupStep, SetupStepId, SetupStepStatus

STEP_TITLES: dict[SetupStepId, tuple[str, str, bool]] = {
    SetupStepId.INTRO: ("Welcome. I'm VYOM.", "A short introduction to your environment.", True),
    SetupStepId.PREFERENCES: ("Who am I working with?", "Your name and basic preferences.", False),
    SetupStepId.VOICE_TEST: ("Voice test", "Speak a short phrase to verify voice.", False),
    SetupStepId.MICROPHONE: ("Microphone permission", "Grant microphone access for voice.", False),
    SetupStepId.PRIVACY: ("Privacy choices", "How VYOM may use external models and your data.", True),
    SetupStepId.PROVIDER: ("AI provider", "Connect a model provider (optional).", False),
    SetupStepId.WORKSPACE: ("Your workspace", "Register project folders VYOM may access.", False),
    SetupStepId.INTEGRATIONS: ("Gmail / Calendar", "Optional Google integrations.", False),
    SetupStepId.AUTONOMY: ("Autonomy level", "How much VYOM may do without asking.", False),
    SetupStepId.NOTIFICATIONS: ("Notifications", "When VYOM should reach you.", False),
    SetupStepId.STARTUP: ("Start with Windows", "Optional launch-at-login (off by default).", False),
    SetupStepId.DIAGNOSTICS: ("System diagnostics", "A quick health check.", False),
    SetupStepId.READY: ("Ready", "Your VYOM environment is set up.", True),
}


class SetupStateStore:
    """Durable setup/onboarding state: version, completed and skipped
    steps, timestamps. Onboarding versioning means existing users are
    never forced through everything again when the flow changes.
    Credentials already stored in the SecretStore are untouched by
    resume/reset."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def fresh_state(self) -> SetupState:
        state = SetupState()
        state.steps = [
            SetupStep(id=step_id, title=STEP_TITLES[step_id][0], description=STEP_TITLES[step_id][1], required=step_id in REQUIRED_STEPS)
            for step_id in SetupStepId
        ]
        return state

    def load(self) -> SetupState:
        if not self.path.exists():
            return self.fresh_state()
        try:
            state = SetupState.model_validate_json(self.path.read_text(encoding="utf-8"))
        except Exception:
            return self.fresh_state()
        # A newer onboarding version adds new steps without forcing
        # completed ones to repeat.
        known = {step.id for step in state.steps}
        for step_id in SetupStepId:
            if step_id not in known:
                state.steps.append(SetupStep(
                    id=step_id, title=STEP_TITLES[step_id][0],
                    description=STEP_TITLES[step_id][1], required=step_id in REQUIRED_STEPS,
                ))
        return state

    def save(self, state: SetupState) -> None:
        from datetime import datetime, timezone

        state.last_updated = datetime.now(timezone.utc)
        self.path.write_text(state.model_dump_json(), encoding="utf-8")

    def reset(self, *, keep_secrets: bool = True) -> SetupState:
        """Reset onboarding/setup configuration only. Memories,
        projects, and secrets are never erased unless the user takes
        those explicit separate actions."""
        state = self.fresh_state()
        self.save(state)
        return state

    @staticmethod
    def validate_transition(state: SetupState, step_id: SetupStepId, new_status: SetupStepStatus) -> None:
        step = next((s for s in state.steps if s.id == step_id), None)
        if step is None:
            raise ValueError(f"Unknown step {step_id}")
        if new_status == SetupStepStatus.SKIPPED and step.id in SKIPPABLE_STEPS and step.id not in REQUIRED_STEPS:
            return
        if new_status == SetupStepStatus.SKIPPED:
            raise ValueError(f"Required step {step_id.value} cannot be skipped")

    @staticmethod
    def completion_summary(state: SetupState) -> dict:
        return {
            "finished": state.finished,
            "onboarding_version": state.onboarding_version,
            "completed": [s.id.value for s in state.steps if s.status == SetupStepStatus.COMPLETED],
            "skipped": [s.id.value for s in state.steps if s.status == SetupStepStatus.SKIPPED],
            "pending": [s.id.value for s in state.steps if s.status == SetupStepStatus.PENDING],
        }
