from __future__ import annotations

import re
from datetime import datetime, timezone

from app.persistence.database import Database

from .models import ActivityRecord, Campaign, Client, CRMRecord, Interaction, Lead, LeadState, Opportunity, Person, Project


def normalize_key(value: str) -> str:
    normalized = re.sub(r"^https?://", "", value.strip().casefold())
    normalized = re.sub(r"^www\.", "", normalized)
    return re.sub(r"[^a-z0-9]+", "", normalized)


class CRMStore:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def upsert(self, record: CRMRecord) -> tuple[CRMRecord, bool]:
        key_source = record.normalized_key or getattr(record, "domain", "") or record.name
        record.normalized_key = normalize_key(key_source)
        connection = self.database.require_connection()
        existing = await (await connection.execute(
            "SELECT id, record_json FROM crm_records WHERE record_type = ? AND normalized_key = ?",
            (record.record_type, record.normalized_key),
        )).fetchone()
        created = existing is None
        if existing:
            current = self._decode(existing["record_json"])
            record.id = current.id
            record.created_at = current.created_at
        record.updated_at = datetime.now(timezone.utc)
        await connection.execute(
            """INSERT INTO crm_records(id, record_type, normalized_key, record_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(record_type, normalized_key) DO UPDATE SET
               record_json=excluded.record_json, updated_at=excluded.updated_at""",
            (record.id, record.record_type, record.normalized_key, record.model_dump_json(), record.created_at.isoformat(), record.updated_at.isoformat()),
        )
        await connection.commit()
        return record, created

    async def get(self, record_id: str) -> CRMRecord:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT record_json FROM crm_records WHERE id = ?", (record_id,))).fetchone()
        if row is None:
            raise KeyError(record_id)
        return self._decode(row["record_json"])

    async def list(self, record_type: str | None = None) -> list[CRMRecord]:
        connection = self.database.require_connection()
        if record_type:
            rows = await (await connection.execute("SELECT record_json FROM crm_records WHERE record_type = ? ORDER BY updated_at DESC", (record_type,))).fetchall()
        else:
            rows = await (await connection.execute("SELECT record_json FROM crm_records ORDER BY updated_at DESC")).fetchall()
        return [self._decode(row["record_json"]) for row in rows]

    async def leads(self, state: LeadState | None = None) -> list[Lead]:
        records = await self.list("lead")
        leads = [Lead.model_validate(record.model_dump()) for record in records]
        return [lead for lead in leads if state is None or lead.state == state]

    async def transition_lead(self, lead_id: str, state: LeadState) -> Lead:
        record = await self.get(lead_id)
        lead = Lead.model_validate(record.model_dump())
        if lead.do_not_contact and state in {LeadState.CONTACTED, LeadState.REPLIED}:
            raise PermissionError("Do-not-contact leads cannot enter outreach states")
        lead.state = state
        saved, _ = await self.upsert(lead)
        return Lead.model_validate(saved.model_dump())

    async def counts(self) -> dict[str, int]:
        leads = await self.leads()
        return {state.value: sum(lead.state == state for lead in leads) for state in LeadState}

    @staticmethod
    def _decode(value: str) -> CRMRecord:
        record = CRMRecord.model_validate_json(value)
        schemas = {
            "lead": Lead, "client": Client, "person": Person,
            "opportunity": Opportunity, "project": Project,
            "interaction": Interaction, "campaign": Campaign, "activity": ActivityRecord,
        }
        if record.record_type in schemas:
            return schemas[record.record_type].model_validate_json(value)
        return record
