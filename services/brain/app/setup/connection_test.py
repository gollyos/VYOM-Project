from __future__ import annotations

import asyncio

OUTCOMES = ("connected", "authentication_failed", "rate_limited", "network_error", "unsupported_model", "unconfigured")


class ConnectionTest:
    """Performs a real minimal provider/integration health test. A
    stored credential never counts as connected by itself."""

    @staticmethod
    async def provider(providers_registry, provider_name: str, *, timeout: float = 10.0) -> dict:
        provider = providers_registry.get(provider_name)
        if provider is None:
            return {"outcome": "unsupported_model", "detail": f"unknown provider {provider_name}"}
        if not provider.configured:
            return {"outcome": "unconfigured", "detail": "no credential stored"}
        try:
            report = await asyncio.wait_for(provider.health_check(), timeout=timeout)
        except TimeoutError:
            return {"outcome": "network_error", "detail": "health check timed out"}
        except Exception as error:
            message = str(error)
            lowered = message.lower()
            if "auth" in lowered or "401" in lowered or "403" in lowered or "invalid api key" in lowered:
                return {"outcome": "authentication_failed", "detail": message[:200]}
            if "429" in message:
                return {"outcome": "rate_limited", "detail": message[:200]}
            return {"outcome": "network_error", "detail": message[:200]}
        healthy = bool(report.get("ok", report.get("status") == "ok"))
        if healthy:
            return {"outcome": "connected", "detail": str(report.get("detail", "health check passed"))[:200]}
        detail = str(report)[:200]
        if "429" in detail:
            return {"outcome": "rate_limited", "detail": detail}
        return {"outcome": "authentication_failed" if "auth" in detail.lower() else "network_error", "detail": detail}

    @staticmethod
    async def integration(integration_registry, integration_id: str) -> dict:
        try:
            healthy = await integration_registry.health_check(integration_id)
        except Exception as error:
            return {"outcome": "network_error", "detail": str(error)[:200]}
        if healthy:
            return {"outcome": "connected", "detail": "integration health check passed"}
        return {"outcome": "network_error", "detail": "integration health check failed"}
