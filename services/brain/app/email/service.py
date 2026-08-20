from __future__ import annotations

from datetime import datetime, timezone

from app.persistence.database import Database

from .provider import EmailProvider
from .schemas import DraftRequest, DraftStatus, EmailDraft, EmailMessage, EmailThread, SendReceipt


class EmailService:
    def __init__(self, database: Database, provider: EmailProvider) -> None:
        self.database = database
        self.provider = provider

    async def search(self, query: str, limit: int = 20) -> list[EmailMessage]:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Email provider unavailable")
        return await self.provider.search(query, limit)

    async def read_thread(self, thread_id: str) -> EmailThread:
        return await self.provider.read_thread(thread_id)

    async def create_draft(self, request: DraftRequest) -> EmailDraft:
        draft = EmailDraft.model_validate(request.model_dump())
        await self._save_draft(draft)
        return draft

    async def get_draft(self, draft_id: str) -> EmailDraft:
        connection = self.database.require_connection()
        row = await (await connection.execute("SELECT draft_json FROM email_drafts WHERE id = ?", (draft_id,))).fetchone()
        if row is None:
            raise KeyError(draft_id)
        return EmailDraft.model_validate_json(row["draft_json"])

    async def list_drafts(self, status: DraftStatus | None = None) -> list[EmailDraft]:
        connection = self.database.require_connection()
        if status:
            rows = await (await connection.execute("SELECT draft_json FROM email_drafts WHERE status = ? ORDER BY updated_at DESC", (status.value,))).fetchall()
        else:
            rows = await (await connection.execute("SELECT draft_json FROM email_drafts ORDER BY updated_at DESC")).fetchall()
        return [EmailDraft.model_validate_json(row["draft_json"]) for row in rows]

    async def approve_draft(self, draft_id: str) -> EmailDraft:
        draft = await self.get_draft(draft_id)
        draft.status = DraftStatus.APPROVED
        draft.updated_at = datetime.now(timezone.utc)
        await self._save_draft(draft)
        return draft

    async def send_approved(self, draft_id: str, *, approval_granted: bool) -> SendReceipt:
        if not approval_granted:
            raise PermissionError("Sending email is L2 and requires explicit approval")
        draft = await self.get_draft(draft_id)
        if draft.status != DraftStatus.APPROVED:
            raise PermissionError("The selected draft has not been approved")
        receipt = await self.provider.send(draft)
        if not receipt.verified or not receipt.message_id or not receipt.thread_id:
            raise RuntimeError("Email provider did not return verifiable message and thread IDs")
        draft.status = DraftStatus.SENT
        draft.updated_at = datetime.now(timezone.utc)
        draft.metadata["receipt"] = receipt.model_dump(mode="json")
        await self._save_draft(draft)
        return receipt

    async def _save_draft(self, draft: EmailDraft) -> None:
        connection = self.database.require_connection()
        await connection.execute(
            """INSERT INTO email_drafts(id, thread_id, status, draft_json, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET thread_id=excluded.thread_id, status=excluded.status,
               draft_json=excluded.draft_json, updated_at=excluded.updated_at""",
            (draft.id, draft.thread_id, draft.status.value, draft.model_dump_json(), draft.created_at.isoformat(), draft.updated_at.isoformat()),
        )
        await connection.commit()
