from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from app.crm.models import Lead, LeadState
from app.crm.store import CRMStore
from app.email.schemas import DraftRequest, EmailAddress, EmailDraft
from app.email.service import EmailService

from .schemas import LeadResearchRequest, OutreachRequest, QualificationResult, ResearchedCompany, ResearchEvidence


class LeadResearchProvider(ABC):
    @abstractmethod
    async def health(self) -> tuple[bool, str | None]: ...

    @abstractmethod
    async def research(self, request: LeadResearchRequest) -> list[ResearchedCompany]: ...


class DisconnectedLeadResearchProvider(LeadResearchProvider):
    async def health(self) -> tuple[bool, str | None]:
        return False, "Lead-research integration is disconnected"

    async def research(self, request: LeadResearchRequest) -> list[ResearchedCompany]:
        raise RuntimeError("Lead-research integration is disconnected")


class MockLeadResearchProvider(LeadResearchProvider):
    """Explicit fixture provider. Its evidence labels always say test-fixture."""

    def __init__(self, companies: list[ResearchedCompany] | None = None) -> None:
        self.companies = companies or [
            ResearchedCompany(
                name=f"Fixture Company {index}", domain=f"fixture-{index}.example",
                industry="B2B SaaS", company_size="11-50",
                signals=["public hiring signal", "active product site"],
                evidence=[ResearchEvidence(source="test-fixture", claim="Synthetic company used only in deterministic tests", observed_at="2026-08-15T00:00:00Z")],
            ) for index in range(1, 8)
        ]

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    async def research(self, request: LeadResearchRequest) -> list[ResearchedCompany]:
        return self.companies[: request.limit]


class AgencyService:
    def __init__(self, crm: CRMStore, email: EmailService, research_provider: LeadResearchProvider | None = None) -> None:
        self.crm = crm
        self.email = email
        self.research_provider = research_provider or DisconnectedLeadResearchProvider()

    async def research_leads(self, request: LeadResearchRequest) -> list[QualificationResult]:
        healthy, error = await self.research_provider.health()
        if not healthy:
            raise RuntimeError(error or "Lead research unavailable")
        companies = await self.research_provider.research(request)
        results: list[QualificationResult] = []
        for company in companies:
            score = min(100, 35 + len(company.signals) * 15 + len(company.evidence) * 10)
            reasons = [*company.signals, f"Evidence records: {len(company.evidence)}"]
            lead = Lead(
                name=company.name,
                company=company.name,
                domain=company.domain,
                state=LeadState.QUALIFIED if score >= request.minimum_score else LeadState.RESEARCHED,
                score=score,
                qualification_reason="; ".join(reasons),
                evidence=[f"{item.source}: {item.claim}" for item in company.evidence],
            )
            saved, _ = await self.crm.upsert(lead)
            results.append(QualificationResult(
                lead_id=saved.id, score=score, qualified=score >= request.minimum_score,
                reasons=reasons, evidence=lead.evidence,
            ))
        return results

    async def prepare_outreach(self, request: OutreachRequest) -> EmailDraft:
        record = await self.crm.get(request.lead_id)
        lead = Lead.model_validate(record.model_dump())
        if lead.do_not_contact or lead.state == LeadState.DO_NOT_CONTACT:
            raise PermissionError("Lead is marked do-not-contact")
        if not lead.contact_email:
            raise ValueError("Lead has no verified contact email")
        body = (
            f"Hi {lead.contact_name or lead.company} team,\n\n"
            f"I noticed {lead.qualification_reason or 'a relevant growth signal'}. "
            f"{request.objective}.\n\nBest,\n{request.sender_name}"
        )
        return await self.email.create_draft(DraftRequest(
            to=[EmailAddress(address=lead.contact_email, name=lead.contact_name)],
            subject=f"Idea for {lead.company}", body_text=body,
            metadata={"lead_id": lead.id, "generated_from": "crm-evidence"},
        ))

    async def record_reply(self, lead_id: str, *, positive: bool, provider_message_id: str) -> Lead:
        if not provider_message_id:
            raise ValueError("Reply evidence requires a provider message ID")
        state = LeadState.REPLIED if positive else LeadState.LOST
        return await self.crm.transition_lead(lead_id, state)

    async def follow_up_due(self) -> list[Lead]:
        return [lead for lead in await self.crm.leads(LeadState.CONTACTED) if not lead.do_not_contact]
