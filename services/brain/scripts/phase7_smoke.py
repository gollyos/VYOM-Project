from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agency.schemas import LeadResearchRequest, OutreachRequest
from app.agency.service import AgencyService, MockLeadResearchProvider
from app.automation.scheduler import AutomationScheduler
from app.automation.schemas import Automation, AutomationCreate, AutomationType
from app.automation.store import AutomationStore
from app.briefing.service import BriefingService
from app.calendar.provider import MockCalendarProvider
from app.calendar.schemas import AvailabilityRequest, CalendarEvent, CreateEventRequest
from app.calendar.service import CalendarService
from app.crm.models import Lead, LeadState
from app.crm.store import CRMStore
from app.email.provider import MockEmailProvider
from app.email.schemas import DraftRequest, EmailAddress, EmailMessage
from app.email.service import EmailService
from app.integrations.registry import IntegrationRegistry
from app.integrations.schemas import IntegrationStatus
from app.integrations.secrets import InMemorySecretVault
from app.persistence.database import Database
from app.persistence.task_store import TaskStore


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="vyom-phase7-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        config = base / "integrations.yaml"
        config.write_text(
            """version: 1
integrations:
  - {id: gmail, name: Gmail fixture, provider: mock, category: email, enabled: true, status: disconnected, capabilities: [email.search, email.send]}
  - {id: google-calendar, name: Calendar fixture, provider: mock, category: calendar, enabled: true, status: disconnected, capabilities: [calendar.read, calendar.create]}
""",
            encoding="utf-8",
        )
        database = Database(base / "phase7-smoke.db")
        await database.connect()
        registry = await IntegrationRegistry.from_yaml(config, database, InMemorySecretVault())
        now = datetime.now(timezone.utc)
        email_provider = MockEmailProvider([EmailMessage(
            id="fixture-message", thread_id="fixture-thread",
            sender=EmailAddress(address="sam@example.com", name="Sam"),
            to=[EmailAddress(address="gunjan@example.com")], subject="Agency review",
            body_text="Please share the next steps.", received_at=now, provider="mock-email",
        )])
        calendar_provider = MockCalendarProvider([CalendarEvent(
            id="fixture-event", title="Client review", start_at=now + timedelta(hours=2),
            end_at=now + timedelta(hours=3), attendees=["sam@example.com"], provider="mock-calendar",
        )])
        registry.register_provider("gmail", email_provider)
        registry.register_provider("google-calendar", calendar_provider)
        crm = CRMStore(database)
        email = EmailService(database, email_provider)
        calendar = CalendarService(calendar_provider)
        automations = AutomationStore(database)
        tasks = TaskStore(database)
        agency = AgencyService(crm, email, MockLeadResearchProvider())

        messages = await email.search("agency")
        thread = await email.read_thread(messages[0].thread_id)
        draft = await email.create_draft(DraftRequest(to=[EmailAddress(address="sam@example.com")], subject="Re: Agency review", body_text="Draft response"))
        try:
            await email.send_approved(draft.id, approval_granted=False)
            raise AssertionError("Unapproved email unexpectedly sent")
        except PermissionError:
            pass
        await email.approve_draft(draft.id)
        email_receipt = await email.send_approved(draft.id, approval_granted=True)
        print(f"DEMO 1 email: {len(messages)} searched, thread {thread.id}, verified {email_receipt.message_id}")

        availability = await calendar.availability(AvailabilityRequest(start_at=now, end_at=now + timedelta(hours=5), duration_minutes=60))
        try:
            await calendar.create(CreateEventRequest(title="Approved client call", start_at=now + timedelta(hours=4), end_at=now + timedelta(hours=5)), approval_granted=False)
            raise AssertionError("Unapproved meeting unexpectedly created")
        except PermissionError:
            pass
        calendar_receipt = await calendar.create(CreateEventRequest(title="Approved client call", start_at=now + timedelta(hours=4), end_at=now + timedelta(hours=5)), approval_granted=True)
        print(f"DEMO 2 calendar: {len(availability)} free slots, verified {calendar_receipt.event_id}")

        results = await agency.research_leads(LeadResearchRequest(description="B2B SaaS", limit=5))
        duplicate, created = await crm.upsert(Lead(name="Fixture Company One", company="Fixture Company One", domain="https://fixture-1.example"))
        assert not created and len(await crm.leads()) == 5
        print(f"DEMO 3 CRM/research: {len(results)} evidence-backed leads, duplicate reused {duplicate.id}")

        qualified = (await crm.leads(LeadState.QUALIFIED))[0]
        qualified.contact_email = "lead@example.com"
        await crm.upsert(qualified)
        outreach = await agency.prepare_outreach(OutreachRequest(lead_id=qualified.id))
        qualified.do_not_contact = True
        qualified.state = LeadState.DO_NOT_CONTACT
        await crm.upsert(qualified)
        try:
            await agency.prepare_outreach(OutreachRequest(lead_id=qualified.id))
            raise AssertionError("DNC outreach unexpectedly drafted")
        except PermissionError:
            pass
        print(f"DEMO 4 outreach: local draft {outreach.id}; DNC block verified")

        automation = Automation.from_create(AutomationCreate(name="One-time briefing", type=AutomationType.ONE_TIME, action="prepare_agency_briefing", run_at=now - timedelta(seconds=1)))
        await automations.save(automation)
        async def action(_): return {"briefing": "ready"}
        scheduler = AutomationScheduler(automations, action)
        first_runs = await scheduler.tick(now)
        second_runs = await scheduler.tick(now)
        assert len(first_runs) == 1 and not second_runs
        print(f"DEMO 5 automation: run {first_runs[0].id} persisted; duplicate slot suppressed")

        briefing_service = BriefingService(registry, crm, email, calendar, automations, tasks)
        partial = await briefing_service.generate()
        assert partial.incomplete and partial.metrics["meetings"] is None
        registry.get("gmail").status = IntegrationStatus.CONNECTED
        registry.get("google-calendar").status = IntegrationStatus.CONNECTED
        complete = await briefing_service.generate()
        assert not complete.incomplete and complete.metrics["meetings"] == 2
        print("DEMO 6 briefing: disconnected sources excluded; connected fixture count verified")

        await database.close()
        print("PHASE 7 SMOKE PASSED - all external data above is explicitly test-fixture data")


if __name__ == "__main__":
    asyncio.run(main())
