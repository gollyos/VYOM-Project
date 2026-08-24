from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.integrations.provider import IntegrationProvider

from .schemas import CreateSpreadsheetRequest, RangeValues, SpreadsheetRef, WriteReceipt


class SheetsProvider(IntegrationProvider, ABC):
    @abstractmethod
    async def create(self, request: CreateSpreadsheetRequest) -> SpreadsheetRef: ...

    @abstractmethod
    async def read_range(self, spreadsheet_id: str, cell_range: str) -> RangeValues: ...

    @abstractmethod
    async def write_range(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt: ...

    @abstractmethod
    async def append_rows(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt: ...


class DisconnectedSheetsProvider(SheetsProvider):
    id = "sheets.disconnected"

    async def health(self) -> tuple[bool, str | None]:
        return False, "Google Sheets integration is disconnected"

    async def create(self, request: CreateSpreadsheetRequest) -> SpreadsheetRef:
        raise RuntimeError("Google Sheets integration is disconnected")

    async def read_range(self, spreadsheet_id: str, cell_range: str) -> RangeValues:
        raise RuntimeError("Google Sheets integration is disconnected")

    async def write_range(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt:
        raise RuntimeError("Google Sheets integration is disconnected")

    async def append_rows(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt:
        raise RuntimeError("Google Sheets integration is disconnected")


# Sheets needs its own scope, separate from Gmail's — a user connecting
# Sheets alone should never be asked to also grant mailbox access, and vice
# versa (each integration has its own GoogleOAuthClient instance/consent).
SHEETS_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)

_SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"


class GoogleSheetsProvider(DisconnectedSheetsProvider):
    """Real Google Sheets integration over the Sheets REST API v4. Same
    OAuth/token-vault pattern as GmailProvider (app/email/provider.py) —
    deliberately duplicated rather than shared, since the two providers'
    only common code is the OAuth exchange itself (GoogleOAuthClient)."""

    id = "google-sheets"

    def __init__(self, oauth_client, vault) -> None:
        self.oauth_client = oauth_client
        self.vault = vault
        self._client: httpx.AsyncClient | None = None
        self._pending_state: str | None = None

    # -- OAuth -------------------------------------------------------------

    async def begin_oauth(self, state: str) -> str:
        self._pending_state = state
        return self.oauth_client.authorization_url(state)

    async def complete_oauth(self, code: str) -> dict[str, Any]:
        state = self._pending_state or ""
        self._pending_state = None
        return await self.oauth_client.exchange_code(state, code)

    async def disconnect(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # -- token/session -------------------------------------------------------

    def _load_token(self) -> dict[str, Any] | None:
        raw = self.vault.get("oauth:google-sheets")
        if raw is None:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    async def _access_token(self) -> str:
        token = self._load_token()
        if token is None:
            raise RuntimeError("Google Sheets is not connected — complete OAuth first")
        access_token = token.get("access_token")
        refresh_token = token.get("refresh_token")
        if not access_token and refresh_token:
            return await self._refresh_and_retry()
        if not access_token:
            raise RuntimeError("Google Sheets token is missing an access_token — reconnect required")
        return access_token

    async def _refresh_and_retry(self) -> str:
        token = self._load_token() or {}
        refresh_token = token.get("refresh_token")
        if not refresh_token:
            raise RuntimeError("Google Sheets access expired and no refresh_token is stored — reconnect required")
        refreshed = await self.oauth_client.refresh(refresh_token)
        refreshed.setdefault("refresh_token", refresh_token)
        self.vault.set("oauth:google-sheets", json.dumps(refreshed).encode("utf-8"))
        return refreshed["access_token"]

    def _pooled(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=20.0)
        return self._client

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        access_token = await self._access_token()
        headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {access_token}"}
        response = await self._pooled().request(method, url, headers=headers, **kwargs)
        if response.status_code == 401:
            access_token = await self._refresh_and_retry()
            headers["Authorization"] = f"Bearer {access_token}"
            response = await self._pooled().request(method, url, headers=headers, **kwargs)
        return response

    # -- health --------------------------------------------------------------

    async def health(self) -> tuple[bool, str | None]:
        if self._load_token() is None:
            return False, "Google Sheets is not connected"
        return True, None  # Sheets has no cheap "whoami" endpoint; token presence is the health signal

    # -- operations ----------------------------------------------------------

    async def create(self, request: CreateSpreadsheetRequest) -> SpreadsheetRef:
        body = {
            "properties": {"title": request.title},
            "sheets": [{"properties": {"title": request.sheet_name}}],
        }
        response = await self._request("POST", _SHEETS_API, json=body)
        if response.status_code >= 400:
            raise RuntimeError(f"Sheets create failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        return SpreadsheetRef(
            id=data["spreadsheetId"], title=request.title,
            url=data.get("spreadsheetUrl", f"https://docs.google.com/spreadsheets/d/{data['spreadsheetId']}"),
            provider=self.id,
        )

    async def read_range(self, spreadsheet_id: str, cell_range: str) -> RangeValues:
        response = await self._request("GET", f"{_SHEETS_API}/{spreadsheet_id}/values/{cell_range}")
        if response.status_code >= 400:
            raise RuntimeError(f"Sheets read failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        return RangeValues(range=data.get("range", cell_range), values=data.get("values", []))

    async def write_range(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt:
        response = await self._request(
            "PUT", f"{_SHEETS_API}/{spreadsheet_id}/values/{cell_range}",
            params={"valueInputOption": "USER_ENTERED"},
            json={"range": cell_range, "values": values},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Sheets write failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        return WriteReceipt(
            provider=self.id, spreadsheet_id=spreadsheet_id, range=cell_range,
            updated_cells=data.get("updatedCells", 0), verified=True,
        )

    async def append_rows(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt:
        response = await self._request(
            "POST", f"{_SHEETS_API}/{spreadsheet_id}/values/{cell_range}:append",
            params={"valueInputOption": "USER_ENTERED", "insertDataOption": "INSERT_ROWS"},
            json={"range": cell_range, "values": values},
        )
        if response.status_code >= 400:
            raise RuntimeError(f"Sheets append failed: HTTP {response.status_code}: {response.text[:200]}")
        data = response.json()
        updates = data.get("updates", {})
        return WriteReceipt(
            provider=self.id, spreadsheet_id=spreadsheet_id, range=updates.get("updatedRange", cell_range),
            updated_cells=updates.get("updatedCells", 0), verified=True,
        )


class MockSheetsProvider(SheetsProvider):
    """Safe deterministic provider for tests and explicit demos only."""

    id = "mock-sheets"

    def __init__(self) -> None:
        self.sheets: dict[str, dict[str, list[list[str]]]] = {}
        self._counter = 0

    async def health(self) -> tuple[bool, str | None]:
        return True, None

    async def begin_oauth(self, state: str) -> str:
        return f"https://mock.invalid/oauth?state={state}"

    async def complete_oauth(self, code: str) -> dict:
        if code != "mock-code":
            raise RuntimeError("Mock OAuth code rejected")
        return {"access_token": "test-fixture-access", "refresh_token": "test-fixture-refresh", "token_type": "Bearer"}

    async def create(self, request: CreateSpreadsheetRequest) -> SpreadsheetRef:
        self._counter += 1
        sheet_id = f"mock-sheet-{self._counter}"
        self.sheets[sheet_id] = {request.sheet_name: []}
        return SpreadsheetRef(id=sheet_id, title=request.title, url=f"https://mock.invalid/sheets/{sheet_id}", provider=self.id)

    def _sheet_name(self, cell_range: str) -> str:
        return cell_range.split("!")[0] if "!" in cell_range else "Sheet1"

    async def read_range(self, spreadsheet_id: str, cell_range: str) -> RangeValues:
        rows = self.sheets.get(spreadsheet_id, {}).get(self._sheet_name(cell_range), [])
        return RangeValues(range=cell_range, values=rows)

    async def write_range(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt:
        self.sheets.setdefault(spreadsheet_id, {})[self._sheet_name(cell_range)] = values
        return WriteReceipt(provider=self.id, spreadsheet_id=spreadsheet_id, range=cell_range,
                            updated_cells=sum(len(row) for row in values), verified=True)

    async def append_rows(self, spreadsheet_id: str, cell_range: str, values: list[list[str]]) -> WriteReceipt:
        name = self._sheet_name(cell_range)
        self.sheets.setdefault(spreadsheet_id, {}).setdefault(name, []).extend(values)
        return WriteReceipt(provider=self.id, spreadsheet_id=spreadsheet_id, range=cell_range,
                            updated_cells=sum(len(row) for row in values), verified=True)
