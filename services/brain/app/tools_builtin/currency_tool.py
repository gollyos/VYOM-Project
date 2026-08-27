from __future__ import annotations

from typing import Any

import httpx

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult

FRANKFURTER_BASE = "https://api.frankfurter.dev/v1"


class CurrencyTool(BaseTool):
    """Free, no-API-key currency conversion and FX rates via Frankfurter
    (ECB-backed, no auth). Read-only informational query, so every action
    is L0."""

    metadata = ToolMetadata(
        name="currency",
        description=(
            "Convert an amount between currencies or fetch latest FX rates using the "
            "free, keyless Frankfurter (ECB) API. Actions: convert, rates."
        ),
        category="research",
        required_permissions=[PermissionLevel.L0],
        risk_level="low",
    )

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L0

    async def _get_json(self, url: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            if self._client is not None:
                response = await self._client.get(url, params=params)
            else:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise ToolValidationError(f"Currency lookup failed: could not reach Frankfurter ({exc})") from exc
        if response.status_code >= 400:
            raise ToolValidationError(f"Currency lookup failed: Frankfurter returned {response.status_code}")
        return response.json()

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", "convert"))

        if action == "convert":
            from_currency = str(inputs.get("from_currency") or inputs.get("from") or "").strip().upper()
            to_currency = str(inputs.get("to_currency") or inputs.get("to") or "").strip().upper()
            if not from_currency or not to_currency:
                raise ToolValidationError("from_currency and to_currency are required")
            try:
                amount = float(inputs.get("amount", 1))
            except (TypeError, ValueError) as exc:
                raise ToolValidationError("amount must be a number") from exc
            data = await self._get_json(f"{FRANKFURTER_BASE}/latest", {
                "base": from_currency, "symbols": to_currency, "amount": amount,
            })
            rates = data.get("rates") or {}
            if to_currency not in rates:
                raise ToolValidationError(f"Could not convert {from_currency} to {to_currency}")
            converted = rates[to_currency]
            rate = converted / amount if amount else 0
            output = {
                "from_currency": from_currency, "to_currency": to_currency,
                "amount": amount, "converted_amount": converted, "rate": rate,
                "date": data.get("date"),
            }
            summary = (
                f"{amount:g} {from_currency} = {converted:g} {to_currency} "
                f"(rate {rate:.4f}, as of {data.get('date')})"
            )
        elif action == "rates":
            base = str(inputs.get("base_currency") or inputs.get("base") or "USD").strip().upper()
            data = await self._get_json(f"{FRANKFURTER_BASE}/latest", {"base": base})
            rates = data.get("rates") or {}
            output = {"base_currency": base, "rates": rates, "date": data.get("date")}
            preview = ", ".join(f"{code}={value:g}" for code, value in list(rates.items())[:5])
            summary = f"Latest rates for {base} (as of {data.get('date')}): {preview}"
        else:
            raise ToolValidationError("Unsupported currency action (use 'convert' or 'rates')")

        evidence = EvidenceItem(type="tool_result", summary=f"Currency {action}", data=output)
        return ToolResult.completed(summary, output=output, evidence=[evidence])