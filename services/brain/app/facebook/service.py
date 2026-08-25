from __future__ import annotations

from .provider import FacebookProvider
from .schemas import FacebookPostReceipt, FacebookPostRequest


class FacebookService:
    def __init__(self, provider: FacebookProvider) -> None:
        self.provider = provider

    async def post(self, request: FacebookPostRequest) -> FacebookPostReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Facebook provider unavailable")
        receipt = await self.provider.post(request)
        if not receipt.verified or not receipt.post_id:
            raise RuntimeError("Facebook did not return a verifiable post id")
        return receipt
