from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.calendar.service import CalendarService
from app.contacts.resolver import ContactResolver
from app.crm.store import CRMStore
from app.persistence.database import Database

from .schemas import FollowUpDraft, MeetingBriefing, MeetingNotes


class MeetingService:
    def __init__(self, calendar: CalendarService, crm: CRMStore, contacts: ContactResolver, database: Database) -> None:
        self.calendar = calendar
        self.crm = crm
        self.contacts = contacts
        self.database = database

    async def upcoming_briefings(self, hours: int = 24) -> list[MeetingBriefing]:
        now = datetime.now(timezone.utc)
        events = await self.calendar.events(now, now + timedelta(hours=hours))
        records = await self.crm.list()
        briefings: list[MeetingBriefing] = []
        for event in events:
            context = [record.name for record in records if any(attendee.casefold() in record.model_dump_json().casefold() for attendee in event.attendees)]
            briefings.append(MeetingBriefing(
                event_id=event.id, title=event.title, starts_at=event.start_at,
                attendees=event.attendees, context=context or ["No matching CRM context"],
                open_items=[], source_status={"calendar": "connected", "crm": "available"},
            ))
        return briefings

    async def save_notes(self, notes: MeetingNotes) -> MeetingNotes:
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO meeting_notes(event_id, notes_json, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(event_id) DO UPDATE SET notes_json=excluded.notes_json, updated_at=excluded.updated_at""",
            (notes.event_id, notes.model_dump_json(), datetime.now(timezone.utc).isoformat()),
        )
        await connection.commit()
        return notes

    async def prepare_follow_up(self, event_id: str, recipients: list[str]) -> FollowUpDraft:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT notes_json FROM meeting_notes WHERE event_id = ?", (event_id,))).fetchone()
        if row is None:
            raise KeyError(event_id)
        notes = MeetingNotes.model_validate_json(row["notes_json"])
        actions = "\n".join(f"- {item}" for item in notes.action_items) or "- No action items recorded"
        return FollowUpDraft(event_id=event_id, recipients=recipients, subject="Meeting follow-up", body=f"Thanks for the conversation.\n\nAction items:\n{actions}")
