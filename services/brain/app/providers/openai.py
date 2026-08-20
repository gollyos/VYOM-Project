from .openai_compatible import OpenAICompatibleProvider


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(self, timeout_seconds: float):
        super().__init__(
            name="openai",
            api_key_env="OPENAI_API_KEY",
            base_url="https://api.openai.com/v1",
            timeout_seconds=timeout_seconds,
        )

