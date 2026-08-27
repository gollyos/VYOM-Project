"""
VYOM Ecosystem API Endpoints
============================
Exposes Second Brain Graph, Exam & Career Prep, Agency Content Ops,
CEO Org Chart, and Universal Fleet Execution to the Frontend UI.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.unified_os import get_unified_os

router = APIRouter(prefix="/api/ecosystem", tags=["Ecosystem"])


class StudyPlanRequest(BaseModel):
    subject: str
    target_exam: str = "General"
    days: int = 30


class MockTestRequest(BaseModel):
    subject: str
    num_questions: int = 10


class ResumeOptimizationRequest(BaseModel):
    resume_text: str
    target_role: str


class ContentPlanRequest(BaseModel):
    account_id: str


class FleetExecutionRequest(BaseModel):
    goal: str
    domain: str = "general"
    include_live_web: bool = False


class AccountCreateRequest(BaseModel):
    account_id: str = ""
    owner_name: str
    platform: str = "instagram"
    handle: str
    niche: str
    target_audience: str = ""
    tone: str = "Engaging, high-value, authentic"
    upload_time: str = "19:00 IST"
    posting_frequency: str = "1 post/day"
    preferred_hooks: list[str] = []
    hashtag_pool: list[str] = []
    cta_templates: list[str] = []
    brand_rules: list[str] = []


@router.get("/health")
async def get_ecosystem_health() -> dict[str, Any]:
    os = get_unified_os()
    health = await os.health_check()
    return {
        "status": "OK",
        "subsystems": [{"name": h.name, "status": h.status, "details": h.details} for h in health],
    }


@router.get("/agency/accounts")
async def list_agency_accounts(owner: str | None = None, platform: str | None = None) -> list[dict[str, Any]]:
    from dataclasses import asdict
    os = get_unified_os()
    accounts = os.viral_content.workspaces.list_accounts(owner_filter=owner, platform_filter=platform)
    return [asdict(a) for a in accounts]


@router.post("/agency/accounts")
async def create_agency_account(req: AccountCreateRequest) -> dict[str, Any]:
    from dataclasses import asdict
    from app.agency.content_ops import AccountProfile
    os = get_unified_os()
    prof = AccountProfile(**req.model_dump())
    saved = os.viral_content.workspaces.create_or_update_account(prof)
    return asdict(saved)


@router.get("/agency/accounts/{account_id}")
async def get_agency_account(account_id: str) -> dict[str, Any]:
    from dataclasses import asdict
    os = get_unified_os()
    acc = os.viral_content.workspaces.get_account(account_id)
    if not acc:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
    return asdict(acc)


@router.delete("/agency/accounts/{account_id}")
async def delete_agency_account(account_id: str) -> dict[str, Any]:
    os = get_unified_os()
    deleted = os.viral_content.workspaces.delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
    return {"status": "deleted", "account_id": account_id}


@router.get("/graph")
async def get_second_brain_graph() -> dict[str, Any]:
    os = get_unified_os()
    return os.get_second_brain_graph_data()


@router.get("/ceo/org-chart")
async def get_ceo_org_chart() -> dict[str, Any]:
    os = get_unified_os()
    return os.ceo_orchestrator.get_org_chart()


@router.post("/exam/study-plan")
async def create_study_plan(req: StudyPlanRequest) -> dict[str, Any]:
    os = get_unified_os()
    return os.generate_study_plan(req.subject, target_exam=req.target_exam, days=req.days)


@router.post("/exam/mock-test")
async def create_mock_test(req: MockTestRequest) -> dict[str, Any]:
    os = get_unified_os()
    return os.generate_mock_test(req.subject, num_questions=req.num_questions)


@router.post("/career/optimize-resume")
async def optimize_resume(req: ResumeOptimizationRequest) -> dict[str, Any]:
    os = get_unified_os()
    return os.optimize_resume(req.resume_text, req.target_role)


@router.post("/agency/content-plan")
async def create_content_plan(req: ContentPlanRequest) -> dict[str, Any]:
    os = get_unified_os()
    try:
        return os.generate_client_content_plan(req.account_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/fleet/execute")
async def execute_fleet_mission(req: FleetExecutionRequest) -> dict[str, Any]:
    os = get_unified_os()
    return await os.execute_universal_fleet(req.goal, domain=req.domain, include_live_web=req.include_live_web)
