from __future__ import annotations

import asyncio

from .system_checks import CheckResult

# Connection-test outcomes. A provider is NEVER "connected" just
# because a key exists — only a real minimal interaction proves it.
OUTCOMES = ("connected", "authentication_failed", "rate_limited", "network_error", "unsupported_model", "unconfigured")


class ProviderChecks:
    def __init__(self, model_registry, providers):
        self.model_registry = model_registry
        self.providers = providers

    def configured_providers(self) -> list[str]:
        names = set()
        for model in self.model_registry.enabled():
            provider = self.providers.get(model.provider)
            if provider is not None and provider.configured:
                names.add(model.provider)
        return sorted(names)

    async def test_provider(self, provider_name: str) -> CheckResult:
        provider = self.providers.get(provider_name)
        if provider is None:
            return CheckResult(f"provider:{provider_name}", "FAIL", "Unknown provider in registry")
        if not provider.configured:
            return CheckResult(
                f"provider:{provider_name}", "WARNING",
                "No credential stored; provider remains disconnected (expected until setup)",
            )
        try:
            report = await asyncio.wait_for(provider.health_check(), timeout=10)
            healthy = bool(report.get("ok", report.get("status") == "ok"))
            detail = str(report.get("detail", report))[:200]
            if healthy:
                return CheckResult(f"provider:{provider_name}", "PASS", f"Health check passed: {detail}")
            if "auth" in detail.lower() or "401" in detail or "403" in detail:
                return CheckResult(f"provider:{provider_name}", "FAIL", f"Authentication failed: {detail}")
            if "429" in detail:
                return CheckResult(f"provider:{provider_name}", "WARNING", f"Rate limited during check: {detail}")
            return CheckResult(f"provider:{provider_name}", "WARNING", f"Health check reported an issue: {detail}")
        except TimeoutError:
            return CheckResult(f"provider:{provider_name}", "WARNING", "Health check timed out (network?)")
        except Exception as error:
            message = str(error).lower()
            if "auth" in message or "401" in message or "403" in message:
                return CheckResult(f"provider:{provider_name}", "FAIL", f"Authentication failed: {error}")
            return CheckResult(f"provider:{provider_name}", "WARNING", f"Network error: {error}")

    async def run_all(self) -> list[CheckResult]:
        results = []
        for model in self.model_registry.enabled()[:10]:
            provider = self.providers.get(model.provider)
            if provider is None:
                continue
            if provider.configured:
                results.append(await self.test_provider(model.provider))
            else:
                results.append(CheckResult(
                    f"provider:{model.provider}", "WARNING",
                    "Disconnected (no credential); optional provider",
                ))
        seen: set[str] = set()
        unique = []
        for result in results:
            if result.name in seen:
                continue
            seen.add(result.name)
            unique.append(result)
        return unique
