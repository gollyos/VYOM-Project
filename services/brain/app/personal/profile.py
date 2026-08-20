from __future__ import annotations

from datetime import datetime, timezone

import yaml

from .schemas import PersonalProfile, PersonalProfileField, PreferenceSource
from .store import PersonalProfileStore


class PersonalProfileService:
    """Structured personal-profile state (rule 1). No field is required;
    VYOM learns fields gradually from explicit statements and verified
    behavior, and every field carries `last_confirmed`/`confidence`/
    `expires_at` so a stale observation is never treated as current
    without revalidation (rule 47)."""

    def __init__(self, store: PersonalProfileStore, config: dict):
        self.store = store
        self.config = config
        self.field_expiry_days = int(config.get("privacy", {}).get("profile_field_expiry_days", 120))

    @staticmethod
    def load_config(path) -> dict:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    async def get(self) -> PersonalProfile:
        return await self.store.get()

    async def set_field(self, key: str, value, *, source: PreferenceSource = PreferenceSource.USER_STATEMENT, confidence: float = 1.0) -> PersonalProfile:
        profile = await self.store.get()
        profile.set(key, value, source=source, confidence=confidence, expiry_days=self.field_expiry_days)
        return await self.store.save(profile)

    async def field_value(self, key: str, default=None):
        profile = await self.store.get()
        field = profile.get(key)
        if field is None:
            return default
        return field.value

    async def timezone_name(self) -> str:
        return await self.field_value("timezone", self.config.get("defaults", {}).get("timezone", "UTC"))

    async def working_hours(self) -> dict:
        return await self.field_value("working_hours", self.config.get("defaults", {}).get("working_hours", {"start": "09:00", "end": "18:00"}))

    async def quiet_hours(self) -> dict:
        return await self.field_value("quiet_hours", self.config.get("defaults", {}).get("quiet_hours", {"start": "23:00", "end": "07:00"}))

    async def stale_fields(self) -> list[tuple[str, PersonalProfileField]]:
        """Fields due for revalidation — never silently dropped, only
        flagged so a caller can ask the user to reconfirm."""
        profile = await self.store.get()
        now = datetime.now(timezone.utc)
        return [(key, field) for key, field in profile.fields.items() if field.is_stale(now=now)]
