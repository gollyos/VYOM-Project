from __future__ import annotations

from pathlib import Path

from .builder import VideoBuilder
from .schemas import VideoCreateRequest, VideoJob, VideoScene, VideoStatus
from .slides import render_text_slide


class VideoService:
    """Orchestrates end-to-end video creation. In-memory job store (a
    single-user desktop app's video jobs do not need SQLite durability
    the way tasks/knowledge do — the real, durable artifact IS the
    rendered MP4 file on disk, addressable by job.output_path)."""

    def __init__(self, *, workdir: Path) -> None:
        self.builder = VideoBuilder(workdir=workdir)
        self.jobs: dict[str, VideoJob] = {}

    def get(self, job_id: str) -> VideoJob:
        job = self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return job

    def list(self) -> list[VideoJob]:
        return sorted(self.jobs.values(), key=lambda job: job.created_at, reverse=True)

    async def create_and_render(self, request: VideoCreateRequest) -> VideoJob:
        if not request.scenes:
            raise ValueError("A video needs at least one scene (narration text)")
        job = VideoJob(
            title=request.title, scenes=list(request.scenes), voice=request.voice,
            resolution=request.resolution, fps=request.fps,
        )
        self.jobs[job.id] = job
        # Every scene MUST have a real image before the builder runs. A
        # scene arriving WITHOUT one gets a real, honestly-labeled
        # fallback slide rendered from its own narration text — never a
        # placeholder the builder silently skips, and never an invented
        # path that does not exist on disk.
        job_dir = self.builder.job_dir(job.id)
        for index, scene in enumerate(job.scenes):
            if not scene.image_path:
                slide_path = job_dir / f"scene_{index:03d}_fallback_slide.png"
                render_text_slide(scene.text, slide_path, index=index, resolution=job.resolution)
                scene.image_path = str(slide_path)
        return await self.builder.build(job)
