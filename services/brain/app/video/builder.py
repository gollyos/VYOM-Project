from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from uuid import uuid4

import edge_tts

from .schemas import VideoJob, VideoScene, VideoStatus


class VideoBuildError(RuntimeError):
    pass


class VideoBuilder:
    """Real, working video creation: narration text -> TTS audio (edge-tts,
    free, no API key) -> one still image per scene -> ffmpeg assembly into
    an actual playable MP4 with synced audio. No placeholder frames, no
    invented duration numbers — each scene's on-screen time is the REAL
    measured length of its own rendered narration clip (via ffprobe)."""

    def __init__(self, *, workdir: Path, ffmpeg_bin: str = "ffmpeg", ffprobe_bin: str = "ffprobe") -> None:
        self.workdir = workdir
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_bin = ffmpeg_bin
        self.ffprobe_bin = ffprobe_bin

    def job_dir(self, job_id: str) -> Path:
        directory = self.workdir / job_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    # -- narration -----------------------------------------------------------

    async def _synthesize_narration(self, text: str, voice: str, output_path: Path) -> None:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise VideoBuildError(f"TTS produced no audio for narration: {text[:80]!r}")

    async def _probe_duration_seconds(self, media_path: Path) -> float:
        process = await asyncio.create_subprocess_exec(
            self.ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
            "-of", "json", str(media_path),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise VideoBuildError(f"ffprobe failed on {media_path.name}: {stderr.decode(errors='replace')[:300]}")
        data = json.loads(stdout.decode())
        return float(data["format"]["duration"])

    # -- per-scene clip --------------------------------------------------

    async def _build_scene_clip(
        self, image_path: Path, audio_path: Path, duration: float, output_path: Path,
        *, resolution: str, fps: int,
    ) -> None:
        """One still image + its narration audio -> one MP4 segment, sized
        to the audio's REAL duration. A slow zoom (Ken Burns effect) keeps
        a still image from looking like a static slide."""
        width, height = (int(part) for part in resolution.split("x"))
        zoom_frames = max(int(duration * fps), 1)
        zoompan = (
            f"scale=8000:-1,zoompan=z='min(zoom+0.0015,1.5)':d={zoom_frames}:"
            f"s={width}x{height}:fps={fps}"
        )
        process = await asyncio.create_subprocess_exec(
            self.ffmpeg_bin, "-y",
            "-loop", "1", "-i", str(image_path),
            "-i", str(audio_path),
            "-vf", zoompan,
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-t", f"{duration:.3f}",
            "-shortest",
            str(output_path),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise VideoBuildError(f"ffmpeg failed building scene clip: {stderr.decode(errors='replace')[-500:]}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise VideoBuildError(f"ffmpeg reported success but produced no output for {output_path.name}")

    # -- concat ------------------------------------------------------------

    async def _concat_clips(self, clip_paths: list[Path], output_path: Path) -> None:
        concat_list = output_path.parent / "concat_list.txt"
        # ffmpeg's concat demuxer requires forward slashes even on
        # Windows, and paths containing a single quote must be escaped —
        # neither is likely in a generated job-id path, but escape anyway
        # rather than assume.
        lines = [f"file '{path.as_posix().replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'" for path in clip_paths]
        concat_list.write_text("\n".join(lines), encoding="utf-8")
        process = await asyncio.create_subprocess_exec(
            self.ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list), "-c", "copy", str(output_path),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise VideoBuildError(f"ffmpeg failed concatenating clips: {stderr.decode(errors='replace')[-500:]}")
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise VideoBuildError("ffmpeg concat reported success but produced no output")

    # -- orchestration ---------------------------------------------------

    async def build(self, job: VideoJob, *, on_progress=None) -> VideoJob:
        """Runs the FULL real pipeline for every scene in `job.scenes`:
        each scene MUST already carry a real `image_path` (the caller is
        responsible for having generated/supplied one — this builder does
        not invent images) — synthesizes real narration audio for it,
        measures the REAL resulting duration, renders a per-scene MP4
        segment, and concatenates all segments into one final video.
        Mutates and returns `job` with the real output path, real total
        duration, and per-scene real durations/audio paths filled in."""
        directory = self.job_dir(job.id)
        clip_paths: list[Path] = []
        try:
            job.status = VideoStatus.RENDERING
            for index, scene in enumerate(job.scenes):
                if not scene.image_path:
                    raise VideoBuildError(
                        f"Scene {index + 1} has no image_path — the video builder never "
                        "invents an image; supply one via image generation or a provided asset first."
                    )
                image_path = Path(scene.image_path)
                if not image_path.exists():
                    raise VideoBuildError(f"Scene {index + 1}'s image does not exist on disk: {image_path}")
                audio_path = directory / f"scene_{index:03d}_audio.mp3"
                await self._synthesize_narration(scene.text, job.voice, audio_path)
                duration = await self._probe_duration_seconds(audio_path)
                clip_path = directory / f"scene_{index:03d}_clip.mp4"
                await self._build_scene_clip(
                    image_path, audio_path, duration, clip_path,
                    resolution=job.resolution, fps=job.fps,
                )
                scene.audio_path = str(audio_path)
                scene.duration_seconds = duration
                clip_paths.append(clip_path)
                if on_progress is not None:
                    await on_progress(index + 1, len(job.scenes), scene)

            final_path = directory / f"{job.id}.mp4"
            await self._concat_clips(clip_paths, final_path)
            job.output_path = str(final_path)
            job.duration_seconds = sum(scene.duration_seconds or 0.0 for scene in job.scenes)
            job.status = VideoStatus.RENDERED
        except Exception as error:
            job.status = VideoStatus.FAILED
            job.error = str(error)[:500]
            raise
        return job



