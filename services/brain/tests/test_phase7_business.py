from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.agency.schemas import LeadResearchRequest, OutreachRequest
from app.agency.service import AgencyService, DisconnectedLeadResearchProvider, MockLeadResearchProvider
from app.automation.scheduler import AutomationScheduler
from app.automation.schemas import Automation, AutomationCreate, AutomationStatus, AutomationType
from app.automation.store import AutomationStore
from app.briefing.engine import BusinessEngine
from app.briefing.service import BriefingService
from app.calendar.provider import DisconnectedCalendarProvider, MockCalendarProvider
from app.calendar.schemas import AvailabilityRequest, CalendarEvent, CreateEventRequest
from app.calendar.service import CalendarService
from app.contacts.resolver import ContactResolver
from app.contacts.schemas import Contact
from app.crm.models import Campaign, Client, Interaction, Lead, LeadState, Opportunity, Person, Project
from app.crm.store import CRMStore
from app.email.provider import DisconnectedEmailProvider, MockEmailProvider
from app.email.schemas import DraftRequest, DraftStatus, EmailAddress, EmailMessage
from app.email.service import EmailService
from app.integrations.registry import IntegrationRegistry
from app.integrations.schemas import IntegrationStatus
from app.integrations.secrets import InMemorySecretVault, WindowsDPAPISecretVault
from app.meetings.schemas import MeetingNotes
from app.meetings.service import MeetingService
from app.persistence.database import Database
from app.persistence.task_store import TaskStore
from app.runtime.task_classifier import TaskClassifier
from app.schemas.events import EventType
from app.schemas.tasks import Task, TaskCreate


async def build_services(tmp_path: Path, *, connected: bool = False):
    database = Database(tmp_path / "phase7.db")
    await database.connect()
    config = tmp_path / "integrations.yaml"
    config.write_text(
        """version: 1
integrations:
  - id: gmail
    name: Gmail
    provider: mock
    category: email
    enabled: true
    status: disconnected
    capabilities: [email.search, email.read, email.draft, email.send]
  - id: google-calendar
    name: Calendar
    provider: mock
    category: calendar
    enabled: true
    status: disconnected
    capabilities: [calendar.read, calendar.create]
  - id: lead-research
    name: Research
    provider: mock
    category: research
    enabled: true
    status: disconnected
    capabilities: [agency.lead_research]
""",
        encoding="utf-8",
    )
    registry = await IntegrationRegistry.from_yaml(config, database, InMemorySecretVault())
    now = datetime.now(timezone.utc)
    message = EmailMessage(
        id="message-1", thread_id="thread-1", sender=EmailAddress(address="sam@example.com", name="Sam"),
        to=[EmailAddress(address="gunjan@example.com")], subject="Growth review",
        body_text="Can we discuss the agency growth plan?", received_at=now, provider="mock-email",
    )
    email_provider = MockEmailProvider([message])
    event = CalendarEvent(
        id="event-1", title="Client review", start_at=now + timedelta(hours=2),
        end_at=now + timedelta(hours=3), attendees=["sam@example.com"], provider="mock-calendar",
    )
    calendar_provider = MockCalendarProvider([event])
    registry.register_provider("gmail", email_provider)
    registry.register_provider("google-calendar", calendar_provider)
    if connected:
        registry.get("gmail").status = IntegrationStatus.CONNECTED
        registry.get("google-calendar").status = IntegrationStatus.CONNECTED
    crm = CRMStore(database)
    email = EmailService(database, email_provider)
    calendar = CalendarService(calendar_provider)
    automations = AutomationStore(database)
    tasks = TaskStore(database)
    agency = AgencyService(crm, email, MockLeadResearchProvider())
    briefing = BriefingService(registry, crm, email, calendar, automations, tasks)
    engine = BusinessEngine(briefing, agency, crm, email, automations, registry)
    return database, registry, crm, email, calendar, automations, tasks, agency, briefing, engine


async def test_integration_registry_defaults_disconnected(tmp_path):
    database, registry, *_ = await build_services(tmp_path)
    assert {item.status for item in registry.list()} == {IntegrationStatus.DISCONNECTED}
    await database.close()


async def test_integration_health_updates_connected_mock(tmp_path):
    database, registry, *_ = await build_services(tmp_path)
    record = await registry.refresh_health("gmail")
    assert record.status == IntegrationStatus.CONNECTED
    await database.close()


async def test_oauth_state_rejects_forgery(tmp_path):
    database, registry, *_ = await build_services(tmp_path)
    with pytest.raises(ValueError, match="OAuth state"):
        await registry.complete_oauth("gmail", "code", "forged-state")
    await database.close()


async def test_mock_oauth_connect_stores_backend_secret_and_disconnects(tmp_path):
    database, registry, *_ = await build_services(tmp_path)
    start = await registry.begin_oauth("gmail")
    connected = await registry.complete_oauth("gmail", "mock-code", start.state)
    assert connected.status == IntegrationStatus.CONNECTED
    assert registry.vault.get("oauth:gmail") is not None
    disconnected = await registry.disconnect("gmail")
    assert disconnected.status == IntegrationStatus.DISCONNECTED
    assert registry.vault.get("oauth:gmail") is None
    await database.close()


def test_in_memory_secret_vault_round_trip():
    vault = InMemorySecretVault()
    vault.set("oauth:test", b"secret")
    assert vault.get("oauth:test") == b"secret"
    vault.delete("oauth:test")
    assert vault.get("oauth:test") is None


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI is the production V0 vault")
def test_windows_dpapi_vault_never_writes_plaintext(tmp_path):
    vault = WindowsDPAPISecretVault(tmp_path)
    vault.set("oauth:test", b"very-private-token")
    files = list(tmp_path.glob("*.dpapi"))
    assert len(files) == 1 and b"very-private-token" not in files[0].read_bytes()
    assert vault.get("oauth:test") == b"very-private-token"


async def test_email_search_uses_provider(tmp_path):
    database, _, _, email, *_ = await build_services(tmp_path)
    matches = await email.search("growth")
    assert [item.id for item in matches] == ["message-1"]
    await database.close()


async def test_email_thread_read(tmp_path):
    database, _, _, email, *_ = await build_services(tmp_path)
    thread = await email.read_thread("thread-1")
    assert thread.id == "thread-1" and len(thread.messages) == 1
    await database.close()


async def test_disconnected_email_reports_unavailable(tmp_path):
    database = Database(tmp_path / "email.db")
    await database.connect()
    service = EmailService(database, DisconnectedEmailProvider())
    with pytest.raises(RuntimeError, match="disconnected"):
        await service.search("")
    await database.close()


async def test_email_draft_persists(tmp_path):
    database, _, _, email, *_ = await build_services(tmp_path)
    draft = await email.create_draft(DraftRequest(to=[EmailAddress(address="a@example.com")], subject="Hello", body_text="Draft only"))
    assert (await email.get_draft(draft.id)).body_text == "Draft only"
    await database.close()


async def test_email_send_requires_approval(tmp_path):
    database, _, _, email, *_ = await build_services(tmp_path)
    draft = await email.create_draft(DraftRequest(to=[EmailAddress(address="a@example.com")], subject="Hello", body_text="Draft only"))
    await email.approve_draft(draft.id)
    with pytest.raises(PermissionError, match="L2"):
        await email.send_approved(draft.id, approval_granted=False)
    await database.close()


async def test_email_send_requires_approved_draft(tmp_path):
    database, _, _, email, *_ = await build_services(tmp_path)
    draft = await email.create_draft(DraftRequest(to=[EmailAddress(address="a@example.com")], subject="Hello", body_text="Draft only"))
    with pytest.raises(PermissionError, match="not been approved"):
        await email.send_approved(draft.id, approval_granted=True)
    await database.close()


async def test_email_send_verifies_provider_identifiers(tmp_path):
    database, _, _, email, *_ = await build_services(tmp_path)
    draft = await email.create_draft(DraftRequest(to=[EmailAddress(address="a@example.com")], subject="Hello", body_text="Approved"))
    await email.approve_draft(draft.id)
    receipt = await email.send_approved(draft.id, approval_granted=True)
    assert receipt.verified and receipt.message_id and receipt.thread_id
    assert (await email.get_draft(draft.id)).status == DraftStatus.SENT
    await database.close()


async def test_calendar_availability_excludes_busy_time(tmp_path):
    database, _, _, _, calendar, *_ = await build_services(tmp_path)
    now = datetime.now(timezone.utc)
    slots = await calendar.availability(AvailabilityRequest(start_at=now, end_at=now + timedelta(hours=4), duration_minutes=60))
    busy = calendar.provider.events[0]
    assert all(not (slot.start_at < busy.end_at and slot.end_at > busy.start_at) for slot in slots)
    await database.close()


async def test_calendar_create_requires_approval(tmp_path):
    database, _, _, _, calendar, *_ = await build_services(tmp_path)
    now = datetime.now(timezone.utc)
    with pytest.raises(PermissionError, match="L2"):
        await calendar.create(CreateEventRequest(title="Call", start_at=now, end_at=now + timedelta(hours=1)), approval_granted=False)
    await database.close()


async def test_calendar_create_rejects_invalid_range(tmp_path):
    database, _, _, _, calendar, *_ = await build_services(tmp_path)
    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="end after"):
        await calendar.create(CreateEventRequest(title="Call", start_at=now, end_at=now), approval_granted=True)
    await database.close()


async def test_calendar_create_verifies_event_id(tmp_path):
    database, _, _, _, calendar, *_ = await build_services(tmp_path)
    now = datetime.now(timezone.utc)
    receipt = await calendar.create(CreateEventRequest(title="Call", start_at=now, end_at=now + timedelta(hours=1)), approval_granted=True)
    assert receipt.verified and receipt.event_id.startswith("mock-event")
    await database.close()


def test_contact_unique_resolution():
    result = ContactResolver([Contact(id="1", display_name="Sam Lee", emails=["sam@example.com"])]).resolve("Sam Lee")
    assert result.status == "resolved" and result.contact.id == "1"


def test_contact_ambiguity_requires_confirmation():
    resolver = ContactResolver([Contact(id="1", display_name="Sam Lee"), Contact(id="2", display_name="Sam Patel")])
    result = resolver.resolve("Sam")
    assert result.status == "ambiguous" and len(result.candidates) == 2


def test_contact_not_found_is_explicit():
    assert ContactResolver([]).resolve("Nobody").status == "not_found"


async def test_crm_duplicate_prevention_by_domain(tmp_path):
    database, _, crm, *_ = await build_services(tmp_path)
    first, created = await crm.upsert(Lead(name="Acme", company="Acme", domain="acme.com"))
    second, created_again = await crm.upsert(Lead(name="Acme Inc", company="Acme Inc", domain="https://acme.com"))
    assert created and not created_again and first.id == second.id
    await database.close()


async def test_crm_persists_lead(tmp_path):
    database, _, crm, *_ = await build_services(tmp_path)
    lead, _ = await crm.upsert(Lead(name="Acme", company="Acme", domain="acme.com"))
    assert (await crm.get(lead.id)).name == "Acme"
    await database.close()


async def test_crm_lead_state_transition(tmp_path):
    database, _, crm, *_ = await build_services(tmp_path)
    lead, _ = await crm.upsert(Lead(name="Acme", company="Acme", domain="acme.com"))
    assert (await crm.transition_lead(lead.id, LeadState.QUALIFIED)).state == LeadState.QUALIFIED
    await database.close()


async def test_crm_persists_all_phase7_business_record_types(tmp_path):
    database, _, crm, *_ = await build_services(tmp_path)
    records = [
        Client(name="Client A"), Person(name="Person A", emails=["person@example.com"]),
        Opportunity(name="Opportunity A"), Project(name="Project A"),
        Interaction(name="Email interaction", subject_id="lead-x", channel="email", direction="outbound", summary="Drafted"),
        Campaign(name="Campaign A", channel="email"),
    ]
    for record in records:
        await crm.upsert(record)
    assert {item.record_type for item in await crm.list()} == {"client", "person", "opportunity", "project", "interaction", "campaign"}
    await database.close()


async def test_do_not_contact_blocks_outreach_state(tmp_path):
    database, _, crm, *_ = await build_services(tmp_path)
    lead, _ = await crm.upsert(Lead(name="Acme", company="Acme", domain="acme.com", do_not_contact=True))
    with pytest.raises(PermissionError, match="Do-not-contact"):
        await crm.transition_lead(lead.id, LeadState.CONTACTED)
    await database.close()


async def test_lead_research_stores_evidence(tmp_path):
    database, _, crm, _, _, _, _, agency, *_ = await build_services(tmp_path)
    results = await agency.research_leads(LeadResearchRequest(description="B2B SaaS", limit=5))
    assert len(results) == 5 and all(item.evidence for item in results)
    assert len(await crm.leads()) == 5
    await database.close()


async def test_disconnected_lead_research_is_truthful(tmp_path):
    database, _, crm, email, *_ = await build_services(tmp_path)
    agency = AgencyService(crm, email, DisconnectedLeadResearchProvider())
    with pytest.raises(RuntimeError, match="disconnected"):
        await agency.research_leads(LeadResearchRequest(description="B2B SaaS"))
    await database.close()


async def test_outreach_draft_uses_qualified_lead(tmp_path):
    database, _, crm, _, _, _, _, agency, *_ = await build_services(tmp_path)
    lead, _ = await crm.upsert(Lead(name="Acme", company="Acme", domain="acme.com", contact_email="sam@acme.com", state=LeadState.QUALIFIED, qualification_reason="Hiring sales"))
    draft = await agency.prepare_outreach(OutreachRequest(lead_id=lead.id))
    assert draft.status == DraftStatus.DRAFT and "Acme" in draft.subject
    await database.close()


async def test_outreach_draft_blocks_dnc(tmp_path):
    database, _, crm, _, _, _, _, agency, *_ = await build_services(tmp_path)
    lead, _ = await crm.upsert(Lead(name="Acme", company="Acme", domain="acme.com", contact_email="sam@acme.com", state=LeadState.DO_NOT_CONTACT, do_not_contact=True))
    with pytest.raises(PermissionError, match="do-not-contact"):
        await agency.prepare_outreach(OutreachRequest(lead_id=lead.id))
    await database.close()


async def test_reply_requires_provider_evidence(tmp_path):
    database, _, crm, _, _, _, _, agency, *_ = await build_services(tmp_path)
    lead, _ = await crm.upsert(Lead(name="Acme", company="Acme", domain="acme.com"))
    with pytest.raises(ValueError, match="provider message ID"):
        await agency.record_reply(lead.id, positive=True, provider_message_id="")
    await database.close()


async def test_meeting_notes_and_follow_up_persist(tmp_path):
    database, _, crm, _, calendar, *_ = await build_services(tmp_path)
    meetings = MeetingService(calendar, crm, ContactResolver(), database)
    await meetings.save_notes(MeetingNotes(event_id="event-1", notes="Agreed next step", action_items=["Send proposal"]))
    follow_up = await meetings.prepare_follow_up("event-1", ["sam@example.com"])
    assert "Send proposal" in follow_up.body and follow_up.recipients == ["sam@example.com"]
    await database.close()


def test_recurring_automation_requires_interval():
    with pytest.raises(ValueError, match="interval_minutes"):
        AutomationCreate(name="Bad", type=AutomationType.RECURRING, action="brief")


def test_consequential_automation_cannot_auto_enable():
    with pytest.raises(ValueError, match="per-run approval"):
        AutomationCreate(name="Send", type=AutomationType.RECURRING, action="send_email", interval_minutes=60, permission_level="L2")


def test_automation_timezone_is_validated():
    with pytest.raises(Exception):
        AutomationCreate(name="Bad tz", type=AutomationType.RECURRING, action="brief", interval_minutes=60, timezone="Mars/Olympus")


async def test_automation_persists(tmp_path):
    database, _, _, _, _, store, *_ = await build_services(tmp_path)
    automation = Automation.from_create(AutomationCreate(name="Brief", type=AutomationType.RECURRING, action="prepare_agency_briefing", interval_minutes=60))
    await store.save(automation)
    assert (await store.get(automation.id)).name == "Brief"
    await database.close()


async def test_automation_scheduler_is_idempotent(tmp_path):
    database, _, _, _, _, store, *_ = await build_services(tmp_path)
    now = datetime.now(timezone.utc)
    automation = Automation.from_create(AutomationCreate(name="Once", type=AutomationType.ONE_TIME, action="safe", run_at=now - timedelta(seconds=1)))
    await store.save(automation)
    calls = 0
    async def action(_):
        nonlocal calls
        calls += 1
        return {"ok": True}
    scheduler = AutomationScheduler(store, action)
    assert len(await scheduler.tick(now)) == 1
    assert len(await scheduler.tick(now)) == 0 and calls == 1
    await database.close()


async def test_automation_failure_pauses_runaway_work(tmp_path):
    database, _, _, _, _, store, *_ = await build_services(tmp_path)
    now = datetime.now(timezone.utc)
    automation = Automation.from_create(AutomationCreate(name="Fail", type=AutomationType.ONE_TIME, action="bad", run_at=now - timedelta(seconds=1)))
    await store.save(automation)
    async def action(_):
        raise RuntimeError("safe failure")
    runs = await AutomationScheduler(store, action).tick(now)
    assert runs[0].status == "failed"
    assert (await store.get(automation.id)).status == AutomationStatus.PAUSED
    await database.close()


async def test_briefing_marks_disconnected_sources_incomplete(tmp_path):
    database, *_, briefing, _ = await build_services(tmp_path, connected=False)
    result = await briefing.generate()
    assert result.incomplete and result.metrics["meetings"] is None
    assert "excluded" in result.summary
    await database.close()


async def test_briefing_uses_real_connected_calendar_count(tmp_path):
    database, *_, briefing, _ = await build_services(tmp_path, connected=True)
    result = await briefing.generate()
    assert result.metrics["meetings"] == 1 and not result.incomplete
    await database.close()


async def test_business_daily_status_composes_source_health(tmp_path):
    database, *_, engine = await build_services(tmp_path)
    events = []
    async def emit(*args): events.append(args)
    task = Task.from_create(TaskCreate(user_request="What is my status today?"))
    result = await engine.execute(task, TaskClassifier().classify(task.user_request), emit)
    types = {item["type"] for item in result.ui_composition["objects"]}
    assert "status-summary" in types and "verified-result" in types
    assert events[0][0] == "briefing_generated"
    await database.close()


async def test_business_agency_view_uses_persistent_crm(tmp_path):
    database, _, crm, *rest = await build_services(tmp_path)
    engine = rest[-1]
    await crm.upsert(Lead(name="Acme", company="Acme", domain="acme.com", state=LeadState.QUALIFIED))
    async def emit(*_): pass
    task = Task.from_create(TaskCreate(user_request="Show agency"))
    result = await engine.execute(task, TaskClassifier().classify(task.user_request), emit)
    assert result.structured_data["counts"]["qualified"] == 1
    await database.close()


async def test_business_disconnected_calendar_does_not_fake_meeting(tmp_path):
    database, *_, engine = await build_services(tmp_path)
    async def emit(*_): pass
    task = Task.from_create(TaskCreate(user_request="Show calendar status today"))
    result = await engine.execute(task, TaskClassifier().classify(task.user_request), emit)
    assert result.structured_data["available"] is False
    assert "no meeting was created" in result.response
    await database.close()


async def test_business_automation_command_prevents_duplicate(tmp_path):
    database, *_, automations, tasks, agency, briefing, engine = await build_services(tmp_path)
    async def emit(*_): pass
    profile = TaskClassifier().classify("Automate my agency briefing")
    first = Task.from_create(TaskCreate(user_request="Automate my agency briefing"))
    second = Task.from_create(TaskCreate(user_request="Automate my agency briefing"))
    await engine.execute(first, profile, emit)
    result = await engine.execute(second, profile, emit)
    assert len(await automations.list()) == 1
    assert result.evidence[-1] == "duplicate_prevented:True"
    await database.close()


def test_phase7_classifier_maps_business_commands():
    classifier = TaskClassifier()
    expected = {
        "What is my status today?": "daily_status",
        "Show agency": "show_agency",
        "Find 5 qualified companies": "lead_research",
        "Draft outreach for a lead": "draft_outreach",
        "Send approved outreach": "send_approved_outreach",
        "What needs approval?": "approval_query",
        "Automate my agency briefing": "create_automation",
    }
    assert {command: classifier.classify(command).intent for command in expected} == expected


def test_phase7_event_protocol_contains_operating_events():
    required = {"integration_connected", "email_sent", "email_verified", "crm_updated", "lead_qualified", "meeting_verified", "briefing_generated", "automation_failed"}
    assert required <= {item.value for item in EventType}
