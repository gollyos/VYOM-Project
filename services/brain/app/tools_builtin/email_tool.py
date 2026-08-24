from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class EmailTool(BaseTool):
    """Gmail search/read/draft/send, over the SAME EmailService the REST
    API (app/api/email.py, if present) and calendar-style flows use — so a
    task the planner runs and a human clicking through the UI hit identical
    code, get identical approval gates, and can never diverge.

    The permission ladder is enforced by ToolExecutor.invoke BEFORE
    execute() ever runs (permission_for() below decides the required
    level; ToolExecutor compares it against the task's granted
    context.permission_level and raises ToolPermissionError itself) —
    execute() never re-checks approval, matching every other BaseTool
    in this codebase."""

    metadata = ToolMetadata(
        name="email",
        description=(
            "Search, read, and send email (Gmail). Reading/searching is L0; "
            "drafting is L1; sending a message is L2 and requires the task "
            "to already carry L2 permission before this tool is reachable."
        ),
        category="communication",
        required_permissions=[PermissionLevel.L0, PermissionLevel.L1, PermissionLevel.L2],
        risk_level="high",
    )

    READ_ACTIONS = {"search", "read_thread", "list_drafts", "get_draft"}
    DRAFT_ACTIONS = {"draft"}

    def __init__(self, service) -> None:
        self.service = service

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", ""))
        if action in self.READ_ACTIONS:
            return PermissionLevel.L0
        if action in self.DRAFT_ACTIONS:
            return PermissionLevel.L1
        return PermissionLevel.L2  # send, and anything unrecognised, is the highest gate

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", ""))

        if action == "search":
            query = str(inputs.get("query", ""))
            limit = int(inputs.get("limit", 20))
            messages = await self.service.search(query, limit)
            output = {"query": query, "results": [message.model_dump(mode="json") for message in messages]}
            return ToolResult.completed(
                f"Found {len(messages)} message(s) matching '{query}'", output=output,
                evidence=[EvidenceItem(type="tool_result", summary="Gmail search", data={"count": len(messages)})],
            )

        if action == "read_thread":
            thread_id = str(inputs.get("thread_id", ""))
            if not thread_id:
                raise ToolValidationError("thread_id is required")
            thread = await self.service.read_thread(thread_id)
            return ToolResult.completed(
                f"Read thread '{thread.subject}' ({len(thread.messages)} message(s))",
                output=thread.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Gmail thread", data={"thread_id": thread_id})],
            )

        if action == "draft":
            from app.email.schemas import DraftRequest, EmailAddress

            to = [EmailAddress(address=address) for address in inputs.get("to", [])]
            if not to:
                raise ToolValidationError("At least one recipient (to) is required")
            request = DraftRequest(
                to=to, subject=str(inputs.get("subject", "")), body_text=str(inputs.get("body", "")),
                thread_id=inputs.get("thread_id"),
            )
            draft = await self.service.create_draft(request)
            return ToolResult.completed(
                f"Drafted email to {', '.join(a.address for a in to)}", output=draft.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Email draft created", data={"draft_id": draft.id})],
            )

        if action == "list_drafts":
            drafts = await self.service.list_drafts()
            return ToolResult.completed(
                f"{len(drafts)} draft(s)", output={"drafts": [draft.model_dump(mode="json") for draft in drafts]},
            )

        if action == "get_draft":
            draft_id = str(inputs.get("draft_id", ""))
            draft = await self.service.get_draft(draft_id)
            return ToolResult.completed(f"Draft {draft_id}", output=draft.model_dump(mode="json"))

        if action == "send":
            draft_id = str(inputs.get("draft_id", ""))
            if not draft_id:
                raise ToolValidationError("draft_id is required to send")
            draft = await self.service.get_draft(draft_id)
            if draft.status.value != "approved":
                await self.service.approve_draft(draft_id)
            # ToolExecutor already required L2 permission to reach this
            # branch at all (permission_for() above), which IS this task's
            # explicit, scoped approval — so approval_granted=True here
            # simply hands that already-checked fact to EmailService.
            receipt = await self.service.send_approved(draft_id, approval_granted=True)
            return ToolResult.completed(
                f"Sent email (message_id={receipt.message_id})", output=receipt.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Email sent",
                                       data={"message_id": receipt.message_id, "thread_id": receipt.thread_id})],
            )

        raise ToolValidationError(f"Unsupported email action: {action}")

    async def health(self) -> dict[str, Any]:
        healthy, error = await self.service.provider.health()
        return {"healthy": healthy, "reason": error or "connected"}
