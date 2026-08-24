from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.sheets.schemas import (
    AppendRowsRequest,
    CreateSpreadsheetRequest,
    RangeValues,
    SpreadsheetRef,
    WriteReceipt,
    WriteRangeRequest,
)

router = APIRouter(prefix="/api/sheets", tags=["sheets"])


@router.post("", response_model=SpreadsheetRef)
async def create_spreadsheet(payload: CreateSpreadsheetRequest, request: Request) -> SpreadsheetRef:
    try:
        return await request.app.state.sheets_service.create(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.get("/{spreadsheet_id}/values/{cell_range:path}", response_model=RangeValues)
async def read_range(spreadsheet_id: str, cell_range: str, request: Request) -> RangeValues:
    try:
        return await request.app.state.sheets_service.read_range(spreadsheet_id, cell_range)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.put("/{spreadsheet_id}/values", response_model=WriteReceipt)
async def write_range(spreadsheet_id: str, payload: WriteRangeRequest, request: Request) -> WriteReceipt:
    try:
        return await request.app.state.sheets_service.write_range(spreadsheet_id, payload.range, payload.values)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


@router.post("/{spreadsheet_id}/values:append", response_model=WriteReceipt)
async def append_rows(spreadsheet_id: str, payload: AppendRowsRequest, request: Request) -> WriteReceipt:
    try:
        return await request.app.state.sheets_service.append_rows(spreadsheet_id, payload.range, payload.values)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
