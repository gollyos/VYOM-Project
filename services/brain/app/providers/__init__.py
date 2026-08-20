from __future__ import annotations

from app.core.config import Settings

from .anthropic import AnthropicProvider
from .base import ProviderRegistry
from .deepseek import DeepSeekProvider
from .google import GoogleProvider
from .kimi import KimiProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider


def create_provider_registry(settings: Settings) -> ProviderRegistry:
    """Production provider registry.

    DeterministicProvider is intentionally NOT registered here. It reports
    `configured = True` unconditionally and returns canned text, so in the
    real application it silently answered every request the rule-based
    classifier did not recognise. Tests that need a offline provider
    construct DeterministicProvider directly (see tests/helpers.py)."""
    return ProviderRegistry(
        [
            GoogleProvider(settings.provider_timeout_seconds),
            OpenAIProvider(settings.provider_timeout_seconds),
            AnthropicProvider(settings.provider_timeout_seconds),
            OpenRouterProvider(settings.provider_timeout_seconds),
            DeepSeekProvider(settings.provider_timeout_seconds),
            KimiProvider(settings.provider_timeout_seconds),
        ]
    )


__all__ = ["ProviderRegistry", "create_provider_registry"]

