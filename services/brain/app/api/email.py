from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.email.schemas import DraftRequest, EmailDraft, EmailMessage, EmailThread, SendReceipt, SendRequest
from app.schemas.approvals import PermissionLevel


router = APIRouter(prefix="/api/email", tags=["email"])


class AppPasswordConnectRequest(BaseModel):
    address: str
    app_password: str


@router.post("/app-password/connect")
async def connect_app_password(payload: AppPasswordConnectRequest, request: Request) -> dict:
    """The simple Gmail connect path: paste the Gmail address + a
    16-character Google App Password (Google Account -> Security ->
    2-Step Verification -> App Passwords) — works immediately, no Cloud
    Console project, no OAuth consent screen. Verifies the credentials by
    actually logging into IMAP before reporting success, so a typo'd
    password is caught here, not on the first real send."""
    provider = request.app.state.gmail_app_password_provider
    try:
        provider.store_credentials(payload.address, payload.app_password)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    healthy, error = await provider.health()
    if not healthy:
        # Store the bad credentials removed — a failed connect attempt
        # must not leave a broken credential silently sitting in the
        # vault, where a later unrelated action could pick it up and fail
        # confusingly far from where the user typed the typo.
        await provider.disconnect()
        raise HTTPException(status_code=401, detail=error or "Gmail app-password login failed")
    return {"status": "connected", "address": payload.address, "provider": "gmail-app-password"}


@router.post("/app-password/disconnect")
async def disconnect_app_password(request: Request) -> dict:
    await request.app.state.gmail_app_password_provider.disconnect()
    return {"status": "disconnected"}


@router.get("/app-password/status")
async def app_password_status(request: Request) -> dict:
    healthy, error = await request.app.state.gmail_app_password_provider.health()
    return {"connected": healthy, "detail": error}


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
