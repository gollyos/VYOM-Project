from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.youtube.schemas import YouTubeUploadReceipt, YouTubeUploadRequest

router = APIRouter(prefix="/api/youtube", tags=["youtube"])


@router.post("/upload", response_model=YouTubeUploadReceipt)
async def upload_video(payload: YouTubeUploadRequest, request: Request) -> YouTubeUploadReceipt:
    try:
        return await request.app.state.youtube_service.upload(payload)
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
