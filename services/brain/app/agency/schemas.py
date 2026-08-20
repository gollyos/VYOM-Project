from __future__ import annotations

from pydantic import BaseModel, Field


class ResearchEvidence(BaseModel):
    source: str
    claim: str
    observed_at: str


class ResearchedCompany(BaseModel):
    name: str
    domain: str
    industry: str
    company_size: str
    signals: list[str] = Field(default_factory=list)
    evidence: list[ResearchEvidence] = Field(default_factory=list)


class LeadResearchRequest(BaseModel):
    description: str
    limit: int = Field(default=5, ge=1, le=25)
    minimum_score: int = Field(default=60, ge=0, le=100)


class OutreachRequest(BaseModel):
    lead_id: str
    sender_name: str = "Gunjan"
    objective: str = "Start a useful conversation"


class QualificationResult(BaseModel):
    lead_id: str
    score: int
    qualified: bool
    reasons: list[str]
    evidence: list[str]
