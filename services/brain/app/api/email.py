from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.email.schemas import DraftRequest, EmailDraft, EmailMessage, EmailThread, SendReceipt, SendRequest
from app.schemas.approvals import PermissionLevel


router = APIRouter(prefix="/api/email", tags=["email"])


@router.get("/search", response_model=list[EmailMessage])
async def search_email(request: Request, query: str = "", limit: int = 20) -> list[EmailMessage]:
    try:
        return await request.app.state.email_service.search(query, min(max(limit, 1), 100))
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/threads/{thread_id}", response_model=EmailThread)
async def read_thread(thread_id: str, request: Request) -> EmailThread:
    try:
        return await request.app.state.email_service.read_thread(thread_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Thread not found") from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/drafts", response_model=list[EmailDraft])
async def list_drafts(request: Request) -> list[EmailDraft]:
    return await request.app.state.email_service.list_drafts()


@router.post("/drafts", response_model=EmailDraft)
async def create_draft(payload: DraftRequest, request: Request) -> EmailDraft:
    return await request.app.state.email_service.create_draft(payload)


@router.post("/drafts/{draft_id}/approve", response_model=EmailDraft)
async def approve_draft(draft_id: str, request: Request) -> EmailDraft:
    try:
        return await request.app.state.email_service.approve_draft(draft_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Draft not found") from error


@router.post("/send", response_model=SendReceipt)
async def send_email(payload: SendRequest, request: Request) -> SendReceipt:
    if not payload.approval_task_id:
        raise HTTPException(status_code=403, detail="A scoped L2 approval task is required")
    task = await request.app.state.task_store.get(payload.approval_task_id)
    if task is None or not task.approval_granted or task.permission_level != PermissionLevel.L2 or payload.draft_id not in task.user_request:
        raise HTTPException(status_code=403, detail="Approval is missing or does not reference this draft")
    try:
        return await request.app.state.email_service.send_approved(payload.draft_id, approval_granted=True)
    except (KeyError, PermissionError) as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
