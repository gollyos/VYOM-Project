from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class SheetsTool(BaseTool):
    """Google Sheets create/read/write/append, over the SAME SheetsService
    the REST API uses. Writes are L1 (lower than email's L2 send) since
    nothing leaves VYOM's control boundary the way a sent email does —
    matching this repo's calendar-write precedent."""

    metadata = ToolMetadata(
        name="sheets",
        description="Create, read, write, and append rows in Google Sheets. Reads are L0; writes are L1.",
        category="productivity",
        required_permissions=[PermissionLevel.L0, PermissionLevel.L1],
        risk_level="medium",
    )

    READ_ACTIONS = {"read"}

    def __init__(self, service) -> None:
        self.service = service

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        action = str(inputs.get("action", ""))
        return PermissionLevel.L0 if action in self.READ_ACTIONS else PermissionLevel.L1

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", ""))

        if action == "create":
            from app.sheets.schemas import CreateSpreadsheetRequest

            title = str(inputs.get("title", "")).strip()
            if not title:
                raise ToolValidationError("title is required")
            request = CreateSpreadsheetRequest(title=title, sheet_name=str(inputs.get("sheet_name", "Sheet1")))
            ref = await self.service.create(request)
            return ToolResult.completed(
                f"Created spreadsheet '{title}' ({ref.id})", output=ref.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Spreadsheet created", data={"spreadsheet_id": ref.id})],
            )

        if action == "read":
            spreadsheet_id = str(inputs.get("spreadsheet_id", ""))
            cell_range = str(inputs.get("range", "Sheet1"))
            if not spreadsheet_id:
                raise ToolValidationError("spreadsheet_id is required")
            values = await self.service.read_range(spreadsheet_id, cell_range)
            return ToolResult.completed(
                f"Read {cell_range} from {spreadsheet_id} ({len(values.values)} row(s))",
                output=values.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Sheet read", data={"rows": len(values.values)})],
            )

        if action == "write":
            spreadsheet_id = str(inputs.get("spreadsheet_id", ""))
            cell_range = str(inputs.get("range", ""))
            values = inputs.get("values", [])
            if not spreadsheet_id or not cell_range:
                raise ToolValidationError("spreadsheet_id and range are required")
            receipt = await self.service.write_range(spreadsheet_id, cell_range, values)
            return ToolResult.completed(
                f"Wrote {receipt.updated_cells} cell(s) to {cell_range}", output=receipt.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Sheet write", data={"updated_cells": receipt.updated_cells})],
            )

        if action == "append":
            spreadsheet_id = str(inputs.get("spreadsheet_id", ""))
            cell_range = str(inputs.get("range", ""))
            values = inputs.get("values", [])
            if not spreadsheet_id or not cell_range:
                raise ToolValidationError("spreadsheet_id and range are required")
            receipt = await self.service.append_rows(spreadsheet_id, cell_range, values)
            return ToolResult.completed(
                f"Appended {receipt.updated_cells} cell(s) to {cell_range}", output=receipt.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Sheet append", data={"updated_cells": receipt.updated_cells})],
            )

        raise ToolValidationError(f"Unsupported sheets action: {action}")

    async def health(self) -> dict[str, Any]:
        healthy, error = await self.service.provider.health()
        return {"healthy": healthy, "reason": error or "connected"}
