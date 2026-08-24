from __future__ import annotations

from .provider import SheetsProvider
from .schemas import CreateSpreadsheetRequest, RangeValues, SpreadsheetRef, WriteReceipt


class SheetsService:
    """Thin service layer over SheetsProvider, matching this repo's
    EmailService/CalendarService pattern. Sheets writes are lower-risk than
    email sends (nothing leaves VYOM's control boundary to a third party
    the way a sent email does), so there is no draft/approval workflow here
    — every call reaches the provider directly, same as CalendarService."""

    def __init__(self, provider: SheetsProvider) -> None:
        self.provider = provider

    async def create(self, request: CreateSpreadsheetRequest) -> SpreadsheetRef:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Sheets provider unavailable")
        return await self.provider.create(request)

    async def read_range(self, spreadsheet_id: str, cell_range: str) -> RangeValues:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Sheets provider unavailable")
        return await self.provider.read_range(spreadsheet_id, cell_range)

    async def write_range(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Sheets provider unavailable")
        return await self.provider.write_range(spreadsheet_id, cell_range, values)

    async def append_rows(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Sheets provider unavailable")
        return await self.provider.append_rows(spreadsheet_id, cell_range, values)
