from __future__ import annotations

from typing import Any

import httpx

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult

COINGECKO_BASE = "https://api.coingecko.com/api/v3"


class CryptoTool(BaseTool):
    """Free, no-API-key crypto price lookups via the CoinGecko public API
    (no auth required for simple/price and search/trending). Read-only
    informational query, so every action is L0."""

    metadata = ToolMetadata(
        name="crypto",
        description=(
            "Look up current cryptocurrency prices or trending coins using the free, "
            "keyless CoinGecko public API. Actions: price, trending."
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
            raise ToolValidationError(f"Crypto lookup failed: could not reach CoinGecko ({exc})") from exc
        if response.status_code == 429:
            raise ToolValidationError("Crypto lookup failed: CoinGecko rate limit hit, try again shortly")
        if response.status_code >= 400:
            raise ToolValidationError(f"Crypto lookup failed: CoinGecko returned {response.status_code}")
        return response.json()

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", "price"))

        if action == "price":
            coins_raw = inputs.get("coin_ids") or inputs.get("coins") or inputs.get("coin_id") or "bitcoin"
            if isinstance(coins_raw, (list, tuple)):
                coin_ids = ",".join(str(c).strip().lower() for c in coins_raw)
            else:
                coin_ids = ",".join(part.strip().lower() for part in str(coins_raw).split(",") if part.strip())
            if not coin_ids:
                raise ToolValidationError("At least one coin_id is required (e.g. 'bitcoin')")

            currencies_raw = inputs.get("vs_currencies") or inputs.get("currency") or "usd"
            if isinstance(currencies_raw, (list, tuple)):
                vs_currencies = ",".join(str(c).strip().lower() for c in currencies_raw)
            else:
                vs_currencies = ",".join(part.strip().lower() for part in str(currencies_raw).split(",") if part.strip())

            data = await self._get_json(f"{COINGECKO_BASE}/simple/price", {
                "ids": coin_ids, "vs_currencies": vs_currencies,
                "include_24hr_change": "true",
            })
            if not data:
                raise ToolValidationError(f"No price data found for '{coin_ids}'")
            output = {"prices": data}
            parts = []
            for coin, values in data.items():
                for currency, price in values.items():
                    if currency.endswith("_24h_change"):
                        continue
                    change = values.get(f"{currency}_24h_change")
                    change_bit = f" ({change:+.2f}% 24h)" if isinstance(change, (int, float)) else ""
                    parts.append(f"{coin}: {price} {currency.upper()}{change_bit}")
            summary = "; ".join(parts) if parts else "No price data found"
        elif action == "trending":
            data = await self._get_json(f"{COINGECKO_BASE}/search/trending")
            coins = data.get("coins") or []
            trending = [
                {
                    "id": item.get("item", {}).get("id"),
                    "name": item.get("item", {}).get("name"),
                    "symbol": item.get("item", {}).get("symbol"),
                    "market_cap_rank": item.get("item", {}).get("market_cap_rank"),
                }
                for item in coins
            ]
            output = {"trending": trending}
            names = ", ".join(f"{c['name']} ({c['symbol']})" for c in trending[:7])
            summary = f"Trending on CoinGecko right now: {names}" if names else "No trending data available"
        else:
            raise ToolValidationError("Unsupported crypto action (use 'price' or 'trending')")

        evidence = EvidenceItem(type="tool_result", summary=f"Crypto {action}", data=output)
        return ToolResult.completed(summary, output=output, evidence=[evidence])