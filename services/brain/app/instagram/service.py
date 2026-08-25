from __future__ import annotations

from .provider import InstagramProvider
from .schemas import InstagramPostReceipt, InstagramPostRequest


class InstagramService:
    def __init__(self, provider: InstagramProvider) -> None:
        self.provider = provider

    async def post(self, request: InstagramPostRequest) -> InstagramPostReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Instagram provider unavailable")
        receipt = await self.provider.post(request)
        if not receipt.verified or not receipt.media_id:
            raise RuntimeError("Instagram did not return a verifiable media id")
        return receipt
