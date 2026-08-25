from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from app.video.schemas import VideoCreateRequest, VideoJob

router = APIRouter(prefix="/api/video", tags=["video"])


@router.post("/create", response_model=VideoJob)
async def create_video(payload: VideoCreateRequest, request: Request) -> VideoJob:
    """Runs the FULL real pipeline synchronously: TTS narration for every
    scene, real per-scene images (generated fallback slides for any scene
    without one supplied), ffmpeg assembly into an actual MP4. Can take
    tens of seconds for a multi-scene video — this is real rendering
    work, not a queued placeholder."""
    try:
        return await request.app.state.video_service.create_and_render(payload)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"Video rendering failed: {error}"[:500]) from error


@router.get("", response_model=list[VideoJob])
async def list_videos(request: Request) -> list[VideoJob]:
    return request.app.state.video_service.list()


@router.get("/{job_id}", response_model=VideoJob)
async def get_video(job_id: str, request: Request) -> VideoJob:
    try:
        return request.app.state.video_service.get(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Video job not found") from error


@router.get("/{job_id}/file")
async def download_video(job_id: str, request: Request) -> FileResponse:
    try:
        job = request.app.state.video_service.get(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Video job not found") from error
    if not job.output_path:
        raise HTTPException(status_code=409, detail=f"Video job status is '{job.status.value}', no output file yet")
    return FileResponse(job.output_path, media_type="video/mp4", filename=f"{job.title or job.id}.mp4")
