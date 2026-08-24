from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SpreadsheetRef(BaseModel):
    id: str
    title: str
    url: str
    provider: str


class RangeValues(BaseModel):
    range: str
    values: list[list[str]] = Field(default_factory=list)


class CreateSpreadsheetRequest(BaseModel):
    title: str
    sheet_name: str = "Sheet1"


class ReadRangeRequest(BaseModel):
    spreadsheet_id: str
    range: str


class WriteRangeRequest(BaseModel):
    spreadsheet_id: str
    range: str
    values: list[list[str]]


class AppendRowsRequest(BaseModel):
    spreadsheet_id: str
    range: str
    values: list[list[str]]


class WriteReceipt(BaseModel):
    provider: str
    spreadsheet_id: str
    range: str
    updated_cells: int
    verified: bool
