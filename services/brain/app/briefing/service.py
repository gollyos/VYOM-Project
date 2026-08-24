from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.automation.store import AutomationStore
from app.calendar.service import CalendarService
from app.crm.store import CRMStore
from app.email.service import EmailService
from app.integrations.registry import IntegrationRegistry
from app.persistence.task_store import TaskStore
from app.schemas.tasks import TaskStatus

from .schemas import DailyBriefing, SourceSnapshot


class BriefingService:
    def __init__(
        self,
        integrations: IntegrationRegistry,
        crm: CRMStore,
        email: EmailService,
        calendar: CalendarService,
        automations: AutomationStore,
        tasks: TaskStore,
    ) -> None:
        self.integrations = integrations
        self.crm = crm
        self.email = email
        self.calendar = calendar
        self.automations = automations
        self.tasks = tasks

    async def generate(self) -> DailyBriefing:
        now = datetime.now(timezone.utc)
        leads = await self.crm.leads()
        drafts = await self.email.list_drafts()
        automations = await self.automations.list()
        approvals = await self.tasks.list_by_status({TaskStatus.NEEDS_APPROVAL})
        # Unfinished work carried over from before (failed/paused). This
        # leads the briefing: it is yesterday's promise, not new data.
        pending_tasks = await self.tasks.list_by_status({TaskStatus.FAILED, TaskStatus.PAUSED})
        sources: list[SourceSnapshot] = [
            SourceSnapshot(source="crm", status="available", detail=f"{len(leads)} locally stored leads", observed_at=now),
            SourceSnapshot(source="automations", status="available", detail=f"{len(automations)} durable definitions", observed_at=now),
        ]
        meetings: int | None = None
        email_connected = self.integrations.is_connected("gmail") if "gmail" in self.integrations.records else False
        calendar_connected = self.integrations.is_connected("google-calendar") if "google-calendar" in self.integrations.records else False
        sources.append(SourceSnapshot(source="email", status="connected" if email_connected else "disconnected", detail="Live inbox available" if email_connected else "Live inbox not included", observed_at=now))
        sources.append(SourceSnapshot(source="calendar", status="connected" if calendar_connected else "disconnected", detail="Live calendar available" if calendar_connected else "Live meetings not included", observed_at=now))
        if calendar_connected:
            try:
                meetings = len(await self.calendar.events(now, now + timedelta(days=1)))
            except RuntimeError:
                meetings = None
        priorities = []
        if pending_tasks:
            priorities.append(f"Resume {len(pending_tasks)} unfinished task(s) from before")
        if approvals:
            priorities.append(f"Review {len(approvals)} pending approval(s)")
        if drafts:
            priorities.append(f"Review {len(drafts)} local email draft(s)")
        qualified = sum(lead.state.value == "qualified" for lead in leads)
        if qualified:
            priorities.append(f"Prepare next steps for {qualified} qualified lead(s)")
        if not priorities:
            priorities.append("No locally verified urgent work is recorded")
        incomplete = not email_connected or not calendar_connected
        summary = "Briefing assembled from connected and local sources."
        if incomplete:
            summary = "Partial briefing: disconnected sources were excluded, not estimated."
        return DailyBriefing(
            generated_at=now,
            summary=summary,
            metrics={
                "leads": len(leads), "qualified_leads": qualified, "drafts": len(drafts),
                "meetings": meetings, "pending_approvals": len(approvals), "automations": len(automations),
                "pending_tasks": len(pending_tasks),
            },
            priorities=priorities,
            approvals=[{"task_id": item.id, "action": item.user_request, "level": item.permission_level.value} for item in approvals],
            sources=sources,
            incomplete=incomplete,
        )
