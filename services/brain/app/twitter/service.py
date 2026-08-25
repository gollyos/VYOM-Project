from __future__ import annotations

from .provider import TwitterProvider
from .schemas import TwitterPostReceipt, TwitterPostRequest


class TwitterService:
    def __init__(self, provider: TwitterProvider) -> None:
        self.provider = provider

    async def post(self, request: TwitterPostRequest) -> TwitterPostReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "Twitter provider unavailable")
        receipt = await self.provider.post(request)
        if not receipt.verified or not receipt.tweet_id:
            raise RuntimeError("Twitter did not return a verifiable tweet id")
        return receipt
