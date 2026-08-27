"""CRM Engine — high-level facade for the VYOM CRM subsystem.

Provides a single ``CRMEngine`` class that wires together ``CRMStore``
with a ``Database`` connection, exposing the common operations needed
by the runtime executor and any agent that manages contacts, leads, or
opportunities without needing to know internal storage details.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.persistence.database import Database

from .models import (
    ActivityRecord,
    Campaign,
    Client,
    CRMRecord,
    Interaction,
    Lead,
    LeadState,
    Opportunity,
    Person,
    Project,
)
from .store import CRMStore

if TYPE_CHECKING:
    pass


class CRMEngine:
    """Top-level CRM subsystem entry point.

    Usage::

        engine = CRMEngine(database)
        await engine.connect()
        lead = Lead(name="Acme Corp", domain="acme.com", state=LeadState.PROSPECT)
        lead, created = await engine.store.upsert(lead)
        await engine.close()
    """

    def __init__(self, database: Database, memory=None) -> None:
        self.database = database
        self.store = CRMStore(database, memory=memory)

    async def connect(self) -> None:
        """Ensure the database is connected."""
        if self.database.connection is None:
            await self.database.connect()

    async def close(self) -> None:
        """Close the underlying database connection."""
        await self.database.close()

    async def upsert(self, record: CRMRecord) -> tuple[CRMRecord, bool]:
        """Upsert any CRM record (Lead, Client, Person, etc.)."""
        return await self.store.upsert(record)

    async def get(self, record_id: str) -> CRMRecord | None:
        """Fetch a single CRM record by its primary ID."""
        try:
            return await self.store.get(record_id)
        except KeyError:
            return None

    async def list_leads(self, state: LeadState | None = None) -> list[Lead]:
        """Return all leads, optionally filtered by state."""
        return await self.store.leads(state=state)


__all__ = [
    "CRMEngine",
    "CRMStore",
    "CRMRecord",
    "Client",
    "Person",
    "Lead",
    "LeadState",
    "Opportunity",
    "Project",
    "Interaction",
    "Campaign",
    "ActivityRecord",
]
