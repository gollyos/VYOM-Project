from __future__ import annotations

from app.personal.profile import PersonalProfileService
from app.personal.schemas import PreferenceSource


class NotificationPreferencesService:
    """User-authority commands always win (rule 70): "stop reminding me
    about this", "disable proactive suggestions". Backed by the same
    `PersonalProfile` field mechanism as every other personal preference,
    so it persists and supersedes correctly."""

    def __init__(self, profile_service: PersonalProfileService):
        self.profile_service = profile_service

    async def set_proactive_level(self, level: str) -> None:
        await self.profile_service.set_field("proactive_level", level, source=PreferenceSource.USER_STATEMENT)

    async def get_proactive_level(self, default: str = "balanced") -> str:
        return await self.profile_service.field_value("proactive_level", default)

    async def disable_suggestion_topic(self, topic: str) -> None:
        disabled = await self.profile_service.field_value("disabled_suggestion_topics", [])
        if topic not in disabled:
            disabled = [*disabled, topic]
        await self.profile_service.set_field("disabled_suggestion_topics", disabled, source=PreferenceSource.USER_STATEMENT)

    async def is_topic_disabled(self, topic: str) -> bool:
        disabled = await self.profile_service.field_value("disabled_suggestion_topics", [])
        return topic in disabled
