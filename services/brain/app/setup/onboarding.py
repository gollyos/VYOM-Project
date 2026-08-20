from __future__ import annotations

from datetime import datetime, timezone

from .schemas import REQUIRED_STEPS, SetupStepId, SetupStepStatus
from .setup_state import SetupStateStore


class OnboardingService:
    """Drives the first-run flow: only what is necessary, always over
    the VYOM identity (never a SaaS dashboard). Steps persist, resume
    after interruption, and new onboarding versions never force
    completed steps to repeat."""

    def __init__(self, store: SetupStateStore, *, doctor=None, authorization=None):
        self.store = store
        self.doctor = doctor
        self.authorization = authorization

    def current(self):
        return self.store.load()

    def status(self) -> dict:
        state = self.store.load()
        return {
            **SetupStateStore.completion_summary(state),
            "needs_onboarding": not state.finished,
            "next_step": self._next_step(state),
            # Full per-step detail (id/title/description/required/status) -
            # the frontend onboarding overlay renders this directly rather
            # than reconstructing titles/descriptions from the id lists
            # above. Additive: existing consumers of the summary fields
            # above are unaffected.
            "steps": [step.model_dump(mode="json") for step in state.steps],
        }

    @staticmethod
    def _next_step(state) -> str | None:
        for step in state.steps:
            if step.status == SetupStepStatus.PENDING:
                return step.id.value
        return None

    async def complete_step(self, step_id: SetupStepId, data: dict | None = None) -> dict:
        state = self.store.load()
        step = next((s for s in state.steps if s.id == step_id), None)
        if step is None:
            raise ValueError(f"Unknown onboarding step {step_id}")
        step.status = SetupStepStatus.COMPLETED
        if data:
            step.data = data
        if step_id == SetupStepId.PREFERENCES and data:
            state.user_preferences.update(data)
        if step_id == SetupStepId.PRIVACY and data:
            state.privacy_choices.update(data)
        if step_id == SetupStepId.AUTONOMY and data and self.authorization is not None:
            from ..security.authorization import AuthorizationService

            service = AuthorizationService(str(data.get("preset", "balanced")))
            self.authorization.preset = service.preset
            self.authorization.grant = service.grant
            state.autonomy_preset = service.preset
        if step_id == SetupStepId.DIAGNOSTICS and self.doctor is not None:
            report = await self.doctor.run()
            step.data = {"overall": report["overall"], "counts": report["counts"]}
        if all(
            s.status in (SetupStepStatus.COMPLETED, SetupStepStatus.SKIPPED)
            for s in state.steps
            if s.id in REQUIRED_STEPS
        ) and self._next_step(state) is None:
            state.completed_at = datetime.now(timezone.utc)
        self.store.save(state)
        return self.status()

    async def skip_step(self, step_id: SetupStepId) -> dict:
        state = self.store.load()
        SetupStateStore.validate_transition(state, step_id, SetupStepStatus.SKIPPED)
        step = next((s for s in state.steps if s.id == step_id), None)
        if step is not None:
            step.status = SetupStepStatus.SKIPPED
        if self._next_step(state) is None:
            state.completed_at = datetime.now(timezone.utc)
        self.store.save(state)
        return self.status()

    async def reset(self) -> dict:
        self.store.reset()
        return self.status()
