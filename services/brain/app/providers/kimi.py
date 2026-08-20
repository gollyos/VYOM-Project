from .openai_compatible import OpenAICompatibleProvider


class KimiProvider(OpenAICompatibleProvider):
    def __init__(self, timeout_seconds: float):
        super().__init__(
            name="kimi",
            api_key_env="KIMI_API_KEY",
            base_url="https://api.moonshot.ai/v1",
            timeout_seconds=timeout_seconds,
        )

