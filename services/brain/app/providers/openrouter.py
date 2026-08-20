from .openai_compatible import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, timeout_seconds: float):
        super().__init__(
            name="openrouter",
            api_key_env="OPENROUTER_API_KEY",
            base_url="https://openrouter.ai/api/v1",
            timeout_seconds=timeout_seconds,
            extra_headers={"X-Title": "VYOM Brain"},
        )

