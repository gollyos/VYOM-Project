from __future__ import annotations

from .provider import LinkedInProvider
from .schemas import LinkedInPostReceipt, LinkedInPostRequest


class LinkedInService:
    def __init__(self, provider: LinkedInProvider) -> None:
        self.provider = provider

    async def post(self, request: LinkedInPostRequest) -> LinkedInPostReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "LinkedIn provider unavailable")
        receipt = await self.provider.post(request)
        if not receipt.verified or not receipt.post_id:
            raise RuntimeError("LinkedIn did not return a verifiable post id")
        return receipt
