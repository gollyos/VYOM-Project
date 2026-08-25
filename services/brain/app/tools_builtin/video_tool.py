from __future__ import annotations

from typing import Any

from app.schemas.approvals import PermissionLevel
from app.tools.base import BaseTool, ToolMetadata
from app.tools.context import ToolContext
from app.tools.errors import ToolValidationError
from app.tools.result import EvidenceItem, ToolResult


class VideoTool(BaseTool):
    """Real video creation: narration script -> TTS -> images -> ffmpeg ->
    an actual playable MP4 on disk. L1 (writes a real file, no external
    reach) — same tier as filesystem writes, not L2 (nothing is sent
    anywhere the way an email send or a social-media post would be)."""

    metadata = ToolMetadata(
        name="video",
        description=(
            "Create a real narrated video (MP4) from a script: a list of scenes, each with "
            "narration text (spoken via TTS) and an optional image_path. Scenes without an "
            "image get an auto-generated text slide. action='create' renders synchronously "
            "and returns the real output file path; action='get'/'list' inspect past jobs."
        ),
        category="content",
        required_permissions=[PermissionLevel.L1],
        risk_level="low",
    )

    def __init__(self, service) -> None:
        self.service = service

    def permission_for(self, inputs: dict[str, Any]) -> PermissionLevel:
        return PermissionLevel.L1

    async def execute(self, inputs: dict[str, Any], context: ToolContext) -> ToolResult:
        action = str(inputs.get("action", "create"))

        if action == "create":
            from app.video.schemas import VideoCreateRequest, VideoScene

            title = str(inputs.get("title", "")).strip()
            raw_scenes = inputs.get("scenes", [])
            if not title:
                raise ToolValidationError("title is required")
            if not raw_scenes:
                raise ToolValidationError("scenes is required (a list of {text, image_path?} objects)")
            scenes = []
            for raw in raw_scenes:
                if isinstance(raw, str):
                    scenes.append(VideoScene(text=raw))
                elif isinstance(raw, dict):
                    text = str(raw.get("text", "")).strip()
                    if not text:
                        raise ToolValidationError("Every scene needs non-empty narration 'text'")
                    scenes.append(VideoScene(text=text, image_path=raw.get("image_path")))
                else:
                    raise ToolValidationError("Each scene must be a string or an object with 'text'")
            request = VideoCreateRequest(
                title=title, scenes=scenes,
                voice=str(inputs.get("voice", "en-US-AriaNeural")),
                resolution=str(inputs.get("resolution", "1280x720")),
            )
            job = await self.service.create_and_render(request)
            return ToolResult.completed(
                f"Rendered video '{title}' ({job.duration_seconds:.1f}s, {len(job.scenes)} scene(s)) "
                f"to {job.output_path}",
                output=job.model_dump(mode="json"),
                evidence=[EvidenceItem(
                    type="tool_result", summary="Video rendered",
                    data={"job_id": job.id, "output_path": job.output_path, "duration_seconds": job.duration_seconds},
                )],
            )

        if action == "get":
            job_id = str(inputs.get("job_id", ""))
            if not job_id:
                raise ToolValidationError("job_id is required")
            try:
                job = self.service.get(job_id)
            except KeyError as error:
                raise ToolValidationError(f"No video job found with id {job_id}") from error
            return ToolResult.completed(
                f"Video job {job_id} is {job.status.value}", output=job.model_dump(mode="json"),
                evidence=[EvidenceItem(type="tool_result", summary="Video job status", data={"status": job.status.value})],
            )

        if action == "list":
            jobs = self.service.list()
            return ToolResult.completed(
                f"{len(jobs)} video job(s)", output={"jobs": [job.model_dump(mode="json") for job in jobs]},
                evidence=[EvidenceItem(type="tool_result", summary="Video jobs listed", data={"count": len(jobs)})],
            )

        raise ToolValidationError(f"Unsupported video action: {action}")

    async def health(self) -> dict[str, Any]:
        return {"healthy": True, "reason": "connected"}
