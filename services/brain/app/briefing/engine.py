from __future__ import annotations

from datetime import datetime, timezone
from typing import Awaitable, Callable

from app.agency.schemas import LeadResearchRequest, OutreachRequest
from app.agency.service import AgencyService
from app.automation.schemas import Automation, AutomationCreate, AutomationType
from app.automation.store import AutomationStore
from app.crm.models import LeadState
from app.crm.store import CRMStore
from app.email.schemas import DraftStatus
from app.email.service import EmailService
from app.integrations.registry import IntegrationRegistry
from app.schemas.results import ExecutionResult
from app.schemas.tasks import Task, TaskProfile

from .service import BriefingService


EventEmitter = Callable[[str, str, dict], Awaitable[None]]


def _frame(x: float, y: float, width: float) -> dict:
    return {"x": x, "y": y, "width": width}


def _composition(identifier: str, mode: str, label: str, summary: str, objects: list[dict]) -> dict:
    states = ["Planning", "Executing", "Verifying", "Completed"]
    sequence = []
    for index, item in enumerate(objects):
        sequence.append({"id": f"reveal-{index}", "label": item.get("eyebrow", item["title"]), "atMs": index * 320, "state": states[min(index, len(states) - 1)], "objectIds": [item["id"]]})
    return {
        "schemaVersion": 1, "id": identifier, "mode": mode, "label": label,
        "summary": summary, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "objects": objects, "sequence": sequence,
    }


class BusinessEngine:
    INTENTS = {
        "daily_status", "show_agency", "email_inbox", "lead_research", "draft_outreach",
        "send_approved_outreach", "calendar_status", "schedule_meeting", "crm_summary",
        "meeting_briefing", "create_automation", "approval_query",
    }

    def __init__(
        self,
        briefing: BriefingService,
        agency: AgencyService,
        crm: CRMStore,
        email: EmailService,
        automations: AutomationStore,
        integrations: IntegrationRegistry,
    ) -> None:
        self.briefing = briefing
        self.agency = agency
        self.crm = crm
        self.email = email
        self.automations = automations
        self.integrations = integrations

    def supports(self, intent: str) -> bool:
        return intent in self.INTENTS

    async def execute(self, task: Task, profile: TaskProfile, emit: EventEmitter) -> ExecutionResult:
        intent = profile.intent
        if intent == "daily_status":
            await emit("briefing_generated", "Aggregating only available briefing sources", {})
            briefing = await self.briefing.generate()
            source_evidence = [f"{item.source}: {item.status}" for item in briefing.sources]
            # ADAPTIVE STATS — a number is only shown when it EXISTS. The
            # user's complaint: the status screen displayed a permanent
            # agency dashboard (Leads: 0, Meetings: Unavailable) even when
            # no agency data has ever been recorded. Empty counters are
            # noise pretending to be information; they are omitted, and
            # the card itself disappears when nothing real exists.
            metrics = briefing.metrics
            stats: list[dict] = []
            if metrics.get("pending_tasks"):
                stats.append({"label": "Unfinished", "value": str(metrics["pending_tasks"]), "tone": "attention"})
            if metrics.get("pending_approvals"):
                stats.append({"label": "Approvals", "value": str(metrics["pending_approvals"]), "tone": "attention"})
            if metrics.get("meetings") is not None:
                stats.append({"label": "Meetings", "value": str(metrics["meetings"])})
            if metrics.get("leads"):
                stats.append({"label": "Leads", "value": str(metrics["leads"])})
            if metrics.get("drafts"):
                stats.append({"label": "Drafts", "value": str(metrics["drafts"])})
            objects: list[dict] = []
            if stats:
                objects.append({
                    "id": "briefing", "type": "status-summary", "title": "Today",
                    "eyebrow": "Verified briefing", "tone": "intelligence",
                    "frame": _frame(6, 14, 27), "focus": briefing.priorities[0],
                    "stats": stats,
                })
            objects.append({
                "id": "sources", "type": "verified-result", "title": "Source health",
                "eyebrow": "Completeness",
                "tone": "verified" if not briefing.incomplete else "attention",
                "frame": _frame(67, 15, 27), "statement": briefing.summary,
                "evidence": source_evidence, "timestamp": briefing.generated_at.isoformat(),
            })
            if briefing.approvals:
                first = briefing.approvals[0]
                objects.append({"id": "approval", "type": "approval-action", "title": "Needs decision", "eyebrow": "Scoped approval", "tone": "attention", "frame": _frame(7, 63, 28), "request": first["action"], "context": f"{first['level']} · task {first['task_id']}", "actionLabel": "Review in context", "urgency": "important"})
            composition = _composition(f"briefing-{task.id}", "daily-status", "Daily operating context", briefing.summary, objects)
            return ExecutionResult(response=briefing.summary, structured_data=briefing.model_dump(mode="json"), ui_composition=composition, evidence=source_evidence)

        if intent in {"show_agency", "crm_summary"}:
            counts = await self.crm.counts()
            leads = await self.crm.leads()
            await emit("crm_updated", "Loaded persistent CRM pipeline", {"lead_count": len(leads)})
            stages = [{"label": state.value.replace("_", " ").title(), "value": counts[state.value]} for state in (LeadState.NEW, LeadState.RESEARCHED, LeadState.QUALIFIED, LeadState.CONTACTED, LeadState.REPLIED, LeadState.MEETING, LeadState.WON)]
            objects = [
                {"id": "pipeline", "type": "pipeline-funnel", "title": "Agency pipeline", "eyebrow": "Persistent CRM", "tone": "intelligence", "frame": _frame(5, 14, 31), "stages": stages},
                {"id": "agency-health", "type": "verified-result", "title": "Operating truth", "eyebrow": "Source status", "tone": "verified", "frame": _frame(65, 15, 29), "statement": f"{len(leads)} locally persisted leads. External acquisition is not inferred.", "evidence": [f"crm_records:{len(leads)}", f"gmail:{self._status('gmail')}", f"calendar:{self._status('google-calendar')}"], "timestamp": datetime.now(timezone.utc).isoformat()},
            ]
            composition = _composition(f"agency-{task.id}", "agency", "Agency operating layer", "Agency view composed from persistent CRM and explicit integration health.", objects)
            return ExecutionResult(response="Agency view is based on persistent CRM data; disconnected sources are labeled.", structured_data={"counts": counts}, ui_composition=composition, evidence=[f"crm_leads:{len(leads)}"])

        if intent == "email_inbox":
            try:
                messages = await self.email.search("", 12)
                await emit("email_searched", "Searched connected inbox", {"count": len(messages)})
                objects = [{"id": "email-thread", "type": "email-thread", "title": "Inbox focus", "eyebrow": "Connected email", "tone": "intelligence", "frame": _frame(8, 15, 34), "provider": self.email.provider.id, "threadId": messages[0].thread_id if messages else None, "messages": [{"sender": item.sender.name or item.sender.address, "subject": item.subject, "preview": item.body_text[:120], "timestamp": item.received_at.isoformat()} for item in messages[:4]]}]
                response = f"Found {len(messages)} email message(s) from the connected provider."
                return ExecutionResult(response=response, structured_data={"count": len(messages)}, ui_composition=_composition(f"email-{task.id}", "brain-context", "Email context", response, objects), evidence=[f"provider:{self.email.provider.id}", f"message_count:{len(messages)}"])
            except RuntimeError as error:
                return self._unavailable(task, "Email", str(error), "gmail")

        if intent == "lead_research":
            await emit("lead_researched", "Checking lead research provider and evidence", {})
            try:
                results = await self.agency.research_leads(LeadResearchRequest(description=task.user_request, limit=5))
            except RuntimeError as error:
                return self._unavailable(task, "Lead research", str(error), "lead-research")
            await emit("lead_qualified", "Qualified researched companies using stored evidence", {"count": len(results)})
            leads = await self.crm.leads()
            selected = [lead for lead in leads if lead.id in {item.lead_id for item in results}]
            objects = [{"id": f"lead-{index}", "type": "lead-profile", "title": lead.company, "eyebrow": "Qualified lead" if lead.state == LeadState.QUALIFIED else "Research result", "tone": "verified" if lead.state == LeadState.QUALIFIED else "neutral", "frame": _frame(5 + (index % 3) * 31, 12 + (index // 3) * 43, 27), "domain": lead.domain, "state": lead.state.value, "score": lead.score, "reason": lead.qualification_reason, "evidence": lead.evidence} for index, lead in enumerate(selected[:5])]
            response = f"Stored {len(results)} evidence-backed research result(s) in the local CRM."
            return ExecutionResult(response=response, structured_data={"results": [item.model_dump(mode="json") for item in results]}, ui_composition=_composition(f"research-{task.id}", "agency", "Lead research", response, objects), evidence=[evidence for item in results for evidence in item.evidence])

        if intent == "draft_outreach":
            leads = [item for item in await self.crm.leads(LeadState.QUALIFIED) if item.contact_email and not item.do_not_contact]
            if not leads:
                return self._unavailable(task, "Outreach draft", "No qualified lead with a verified email is available", "crm")
            draft = await self.agency.prepare_outreach(OutreachRequest(lead_id=leads[0].id))
            await emit("outreach_drafted", "Prepared a local outreach draft; nothing was sent", {"draft_id": draft.id})
            obj = {"id": "outreach", "type": "outreach-message", "title": draft.subject, "eyebrow": "Draft · not sent", "tone": "attention", "frame": _frame(18, 15, 62), "draftId": draft.id, "recipients": [item.address for item in draft.to], "body": draft.body_text, "status": draft.status.value, "requiresApproval": True}
            return ExecutionResult(response="Outreach draft prepared locally. Sending still requires explicit L2 approval.", structured_data={"draft": draft.model_dump(mode="json")}, ui_composition=_composition(f"draft-{task.id}", "agency", "Outreach draft", "Draft prepared; no external action occurred.", [obj]), evidence=[f"draft_id:{draft.id}", "send_status:not_sent"])

        if intent == "send_approved_outreach":
            drafts = await self.email.list_drafts(DraftStatus.APPROVED)
            if not drafts:
                raise RuntimeError("No approved outreach draft is available")
            receipt = await self.email.send_approved(drafts[0].id, approval_granted=task.approval_granted)
            await emit("email_sent", "Email provider returned a send receipt", receipt.model_dump(mode="json"))
            await emit("email_verified", "Verified provider message and thread identifiers", {"message_id": receipt.message_id, "thread_id": receipt.thread_id})
            obj = {"id": "sent", "type": "verified-result", "title": "Outreach sent", "eyebrow": "External result", "tone": "verified", "frame": _frame(31, 20, 38), "statement": "Provider confirmed the approved email.", "evidence": receipt.evidence, "timestamp": receipt.sent_at.isoformat()}
            return ExecutionResult(response="Approved outreach was sent and verified by provider identifiers.", structured_data=receipt.model_dump(mode="json"), ui_composition=_composition(f"sent-{task.id}", "agency", "Verified outreach", "Approved outreach sent.", [obj]), evidence=receipt.evidence)

        if intent == "create_automation":
            matches = [item for item in await self.automations.list() if item.action == "prepare_agency_briefing" and item.status.value in {"active", "paused"}]
            automation = matches[0] if matches else Automation.from_create(AutomationCreate(name="Daily agency review", type=AutomationType.RECURRING, action="prepare_agency_briefing", interval_minutes=1440, timezone="Asia/Calcutta"))
            if not matches:
                await self.automations.save(automation)
                await emit("automation_created", "Stored a durable recurring automation", {"automation_id": automation.id})
            else:
                await emit("automation_scheduled", "Reused the existing durable agency briefing automation", {"automation_id": automation.id})
            obj = {"id": "automation", "type": "automation-status", "title": automation.name, "eyebrow": "Durable workflow", "tone": "intelligence", "frame": _frame(24, 17, 52), "automationId": automation.id, "schedule": "Every 1440 minutes", "timezone": automation.timezone, "status": automation.status.value, "nextRunAt": automation.next_run_at.isoformat() if automation.next_run_at else None, "lastResult": None}
            response = "Existing recurring agency briefing automation reused." if matches else "Recurring local briefing automation created with bounded free-tier execution."
            return ExecutionResult(response=response, structured_data=automation.model_dump(mode="json"), ui_composition=_composition(f"automation-{task.id}", "brain-context", "Automation", response, [obj]), evidence=[f"automation_id:{automation.id}", f"duplicate_prevented:{bool(matches)}"])

        if intent == "approval_query":
            briefing = await self.briefing.generate()
            objects = [{"id": f"approval-{index}", "type": "approval-action", "title": "Pending decision", "eyebrow": item["level"], "tone": "attention", "frame": _frame(8 + (index % 3) * 31, 16 + (index // 3) * 38, 27), "request": item["action"], "context": f"Task {item['task_id']}", "actionLabel": "Review", "urgency": "important"} for index, item in enumerate(briefing.approvals[:6])]
            if not objects:
                objects = [{"id": "clear", "type": "verified-result", "title": "Approvals", "eyebrow": "Current state", "tone": "verified", "frame": _frame(32, 20, 36), "statement": "No task is waiting for approval.", "evidence": ["task_store:0 pending"], "timestamp": datetime.now(timezone.utc).isoformat()}]
            return ExecutionResult(response=f"{len(briefing.approvals)} task(s) need approval.", structured_data={"approvals": briefing.approvals}, ui_composition=_composition(f"approvals-{task.id}", "brain-context", "Approvals", "Scoped pending decisions.", objects), evidence=[f"pending:{len(briefing.approvals)}"])

        if intent in {"calendar_status", "meeting_briefing", "schedule_meeting"}:
            return self._unavailable(task, "Calendar", "Calendar integration is disconnected; no meeting was created or inferred", "google-calendar")

        raise RuntimeError(f"Unsupported business intent: {intent}")

    def _status(self, integration_id: str) -> str:
        try:
            return self.integrations.get(integration_id).status.value
        except KeyError:
            return "unconfigured"

    def _unavailable(self, task: Task, title: str, detail: str, integration_id: str) -> ExecutionResult:
        status = self._status(integration_id)
        statement = f"{title} unavailable: {detail}."
        obj = {"id": "unavailable", "type": "verified-result", "title": title, "eyebrow": "Capability unavailable", "tone": "attention", "frame": _frame(26, 20, 48), "statement": statement, "evidence": [f"integration:{integration_id}", f"status:{status}", "external_action:none"], "timestamp": datetime.now(timezone.utc).isoformat()}
        return ExecutionResult(response=statement, structured_data={"available": False, "integration": integration_id, "status": status}, ui_composition=_composition(f"unavailable-{task.id}", "brain-context", title, statement, [obj]), evidence=[f"{integration_id}:{status}"])
