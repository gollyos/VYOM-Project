from __future__ import annotations

from .provider import YouTubeProvider
from .schemas import YouTubeUploadReceipt, YouTubeUploadRequest


class YouTubeService:
    def __init__(self, provider: YouTubeProvider) -> None:
        self.provider = provider

    async def upload(self, request: YouTubeUploadRequest) -> YouTubeUploadReceipt:
        healthy, error = await self.provider.health()
        if not healthy:
            raise RuntimeError(error or "YouTube provider unavailable")
        receipt = await self.provider.upload(request)
        if not receipt.verified or not receipt.video_id:
            raise RuntimeError("YouTube did not return a verifiable video id")
        return receipt
