"""Tests for the video creation pipeline added this session: real
edge-tts narration, real ffmpeg assembly, real MP4 output. These
deliberately run the REAL pipeline (no mocking) for a couple of short
scenes — it is fast (a few seconds) and only real output proves the
pipeline actually works end to end, matching how this feature was
verified live this session.
"""
from __future__ import annotations

import shutil

import pytest

from app.video.builder import VideoBuilder, VideoBuildError
from app.video.schemas import VideoCreateRequest, VideoJob, VideoScene, VideoStatus
from app.video.service import VideoService
from app.video.slides import render_text_slide

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
pytestmark = pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="ffmpeg/ffprobe not on PATH")


def test_render_text_slide_produces_a_real_image(tmp_path):
    output = tmp_path / "slide.png"
    result = render_text_slide("Hello VYOM", output, resolution="640x360")
    assert result.exists()
    assert result.stat().st_size > 0
    from PIL import Image

    with Image.open(result) as image:
        assert image.size == (640, 360)


@pytest.mark.asyncio
async def test_full_pipeline_produces_a_real_playable_mp4(tmp_path):
    slide = tmp_path / "slide.png"
    render_text_slide("Test scene", slide, resolution="640x360")

    job = VideoJob(
        title="Pipeline test",
        scenes=[VideoScene(text="This is a short real test narration.", image_path=str(slide))],
        resolution="640x360",
    )
    builder = VideoBuilder(workdir=tmp_path / "jobs")
    result = await builder.build(job)

    assert result.status == VideoStatus.RENDERED
    assert result.output_path is not None
    from pathlib import Path

    output = Path(result.output_path)
    assert output.exists()
    assert output.stat().st_size > 1000  # a real MP4, not an empty/stub file
    assert result.duration_seconds is not None and result.duration_seconds > 0
    # Verify with ffprobe that this is genuinely a video+audio MP4, not
    # just a file with a .mp4 extension.
    import json
    import subprocess

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,codec_name", "-of", "json", str(output)],
        capture_output=True, text=True, timeout=15,
    )
    streams = json.loads(probe.stdout)["streams"]
    codec_types = {stream["codec_type"] for stream in streams}
    assert "video" in codec_types
    assert "audio" in codec_types
    video_codec = next(s["codec_name"] for s in streams if s["codec_type"] == "video")
    assert video_codec == "h264"


@pytest.mark.asyncio
async def test_builder_raises_honestly_when_scene_has_no_image(tmp_path):
    job = VideoJob(title="Bad job", scenes=[VideoScene(text="No image here")])
    builder = VideoBuilder(workdir=tmp_path / "jobs")
    with pytest.raises(VideoBuildError, match="no image_path"):
        await builder.build(job)
    assert job.status == VideoStatus.FAILED
    assert job.error is not None


@pytest.mark.asyncio
async def test_video_service_auto_generates_fallback_slides_for_scenes_without_images(tmp_path):
    service = VideoService(workdir=tmp_path / "jobs")
    request = VideoCreateRequest(
        title="Auto-slide test",
        scenes=[VideoScene(text="First scene with no image")],
        resolution="640x360",
    )
    job = await service.create_and_render(request)
    assert job.status == VideoStatus.RENDERED
    # The service must have filled in a real, existing image path.
    from pathlib import Path

    assert job.scenes[0].image_path is not None
    assert Path(job.scenes[0].image_path).exists()


@pytest.mark.asyncio
async def test_video_service_multi_scene_video_has_correct_total_duration(tmp_path):
    service = VideoService(workdir=tmp_path / "jobs")
    request = VideoCreateRequest(
        title="Multi-scene test",
        scenes=[
            VideoScene(text="First scene narration text here."),
            VideoScene(text="Second scene has different narration."),
        ],
        resolution="640x360",
    )
    job = await service.create_and_render(request)
    assert job.status == VideoStatus.RENDERED
    assert len(job.scenes) == 2
    # Every scene's real measured duration must sum to the job's total.
    scene_total = sum(scene.duration_seconds for scene in job.scenes)
    assert abs(job.duration_seconds - scene_total) < 0.5


def test_video_service_rejects_empty_scene_list(tmp_path):
    import asyncio

    service = VideoService(workdir=tmp_path / "jobs")
    request = VideoCreateRequest(title="Empty", scenes=[])
    with pytest.raises(ValueError, match="at least one scene"):
        asyncio.run(service.create_and_render(request))


@pytest.mark.asyncio
async def test_video_service_get_and_list_after_render(tmp_path):
    service = VideoService(workdir=tmp_path / "jobs")
    request = VideoCreateRequest(title="Listable", scenes=[VideoScene(text="One scene.")], resolution="640x360")
    job = await service.create_and_render(request)

    fetched = service.get(job.id)
    assert fetched.id == job.id

    listed = service.list()
    assert len(listed) == 1
    assert listed[0].id == job.id

    with pytest.raises(KeyError):
        service.get("nonexistent-job-id")
