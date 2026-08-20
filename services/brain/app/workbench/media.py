from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MediaResult:
    success: bool
    output: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    backend: str = ""


class FFmpegAdapter:
    """FFmpeg adapter only — no media frameworks bundled. All operations
    are subprocess-based, tool-gated by the caller, and VERIFIED via
    ffprobe (never just exit code 0)."""

    def __init__(self, ffmpeg_path: str | None = None, ffprobe_path: str | None = None):
        self.ffmpeg = ffmpeg_path or shutil.which("ffmpeg")
        self.ffprobe = ffprobe_path or shutil.which("ffprobe")

    @property
    def available(self) -> bool:
        return bool(self.ffmpeg and self.ffprobe)

    async def _run(self, args: list[str], timeout: float = 120.0) -> tuple[bool, str]:
        if not self.available:
            return False, "ffmpeg/ffprobe not installed"
        process = await asyncio.create_subprocess_exec(
            self.ffmpeg, *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            _stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError:
            process.kill()
            return False, "ffmpeg timed out"
        return process.returncode == 0, stderr.decode("utf-8", errors="ignore")[-500:]

    async def probe(self, path: Path) -> dict:
        if not self.available or not Path(path).exists():
            return {}
        process = await asyncio.create_subprocess_exec(
            self.ffprobe, "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        try:
            return json.loads(stdout.decode("utf-8", errors="ignore"))
        except json.JSONDecodeError:
            return {}

    async def inspect(self, path: Path) -> MediaResult:
        info = await self.probe(path)
        if not info:
            return MediaResult(False, warnings=["cannot probe (missing file or ffmpeg)"], backend="ffmpeg")
        fmt = info.get("format", {})
        streams = info.get("streams", [])
        return MediaResult(True, {
            "duration_seconds": float(fmt.get("duration", 0) or 0),
            "format": fmt.get("format_name"),
            "video": next(({"codec": s.get("codec_name"), "width": s.get("width"), "height": s.get("height")}
                           for s in streams if s.get("codec_type") == "video"), None),
            "audio": next(({"codec": s.get("codec_name"), "sample_rate": s.get("sample_rate")}
                           for s in streams if s.get("codec_type") == "audio"), None),
        }, backend="ffmpeg")

    async def _convert_generic(self, source: Path, target: Path, extra: list[str] | None = None,
                               expect_duration: bool = True) -> MediaResult:
        source, target = Path(source), Path(target)
        if not source.exists():
            return MediaResult(False, warnings=[f"input {source} not found"], backend="ffmpeg")
        ok, log = await self._run(["-y", "-i", str(source), *(extra or []), str(target)])
        if not ok:
            return MediaResult(False, warnings=[f"ffmpeg failed: {log[-160:]}"], backend="ffmpeg")
        # Verification: the output must exist AND probe to a sane duration.
        if not target.exists():
            return MediaResult(False, warnings=["output missing after ffmpeg"], backend="ffmpeg")
        probed = await self.probe(target)
        duration = float(probed.get("format", {}).get("duration", 0) or 0)
        if expect_duration and duration <= 0:
            return MediaResult(False, warnings=["output not readable by ffprobe (no duration)"], backend="ffmpeg")
        return MediaResult(True, {"output": str(target), "duration_seconds": round(duration, 3)}, backend="ffmpeg")

    async def trim(self, source: Path, target: Path, start: float, end: float) -> MediaResult:
        return await self._convert_generic(source, target, ["-ss", str(start), "-to", str(end), "-c", "copy"])

    async def convert(self, source: Path, target: Path) -> MediaResult:
        return await self._convert_generic(source, target)

    async def extract_audio(self, source: Path, target: Path) -> MediaResult:
        return await self._convert_generic(source, target, ["-vn", "-acodec", "libmp3lame" if target.suffix == ".mp3" else "aac"])

    async def normalize_audio(self, source: Path, target: Path) -> MediaResult:
        return await self._convert_generic(source, target, ["-af", "loudnorm"])

    async def merge_audio(self, sources: list[Path], target: Path) -> MediaResult:
        inputs = []
        for item in sources:
            inputs.extend(["-i", str(item)])
        return await self._convert_generic(sources[0], target, inputs[2:] + ["-filter_complex",
                          "".join(f"[{i}:a]" for i in range(len(sources))) + f"concat=n={len(sources)}:v=0:a=1[out]",
                          "-map", "[out]"])

    async def transcode_video(self, source: Path, target: Path, *, crf: int = 23) -> MediaResult:
        return await self._convert_generic(source, target, ["-c:v", "libx264", "-crf", str(crf), "-preset", "veryfast", "-c:a", "aac"])

    async def resize_video(self, source: Path, target: Path, width: int, height: int) -> MediaResult:
        return await self._convert_generic(source, target,
                                           ["-vf", f"scale={width}:{height}", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "copy"])

    async def extract_frames(self, source: Path, pattern: Path, fps: float = 1.0) -> MediaResult:
        pattern = Path(pattern)
        ok, log = await self._run(["-y", "-i", str(source), "-vf", f"fps={fps}", str(pattern)])
        if not ok:
            return MediaResult(False, warnings=[f"frame extraction failed: {log[-160:]}"], backend="ffmpeg")
        frames = sorted(pattern.parent.glob(pattern.name.replace("%03d" if "%03d" in pattern.name else "%d", "*") or "*"))
        frames = [item for item in pattern.parent.glob("*") if item.suffix in (".png", ".jpg")] if not frames else frames
        if not frames:
            return MediaResult(False, warnings=["no frames produced"], backend="ffmpeg")
        return MediaResult(True, {"frames": [str(item) for item in frames[:20]], "count": len(frames)}, backend="ffmpeg")

    async def replace_audio(self, video: Path, audio: Path, target: Path) -> MediaResult:
        return await self._convert_generic(video, target,
                                           ["-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-shortest"])


class PdfAdapter:
    """ONE PDF dependency: PyMuPDF (pymupdf). Inspect / text / page
    count / render / merge / split with verified outputs. Generation
    stays in the Artifact Engine."""

    def __init__(self):
        try:
            import pymupdf  # noqa: F401

            self.available = True
        except ImportError:
            self.available = False

    def _open(self, path: Path):
        import pymupdf

        return pymupdf.open(str(path))

    def inspect(self, path: Path) -> MediaResult:
        if not self.available:
            return MediaResult(False, warnings=["pymupdf not installed"], backend="pymupdf")
        if not Path(path).exists():
            return MediaResult(False, warnings=["pdf not found"], backend="pymupdf")
        document = self._open(path)
        try:
            page = document.load_page(0)
            return MediaResult(True, {
                "page_count": document.page_count,
                "metadata": {key: value for key, value in (document.metadata or {}).items() if value},
                "first_page_size": page.rect.width and (round(page.rect.width), round(page.rect.height)),
            }, backend="pymupdf")
        except Exception as error:
            return MediaResult(False, warnings=[f"cannot open pdf: {error}"], backend="pymupdf")
        finally:
            document.close()

    def extract_text(self, path: Path, pages: range | None = None) -> MediaResult:
        if not self.available:
            return MediaResult(False, warnings=["pymupdf not installed"], backend="pymupdf")
        document = self._open(path)
        try:
            indices = pages or range(document.page_count)
            text = "\n".join(document.load_page(index).get_text() for index in indices)
            return MediaResult(True, {"text": text, "pages": len(indices)}, backend="pymupdf")
        finally:
            document.close()

    def render_pages(self, path: Path, output_dir: Path, *, dpi: int = 110, max_pages: int = 5) -> MediaResult:
        if not self.available:
            return MediaResult(False, warnings=["pymupdf not installed"], backend="pymupdf")
        output_dir.mkdir(parents=True, exist_ok=True)
        document = self._open(path)
        try:
            rendered = []
            for index in range(min(document.page_count, max_pages)):
                pixmap = document.load_page(index).get_pixmap(dpi=dpi)
                target = output_dir / f"page-{index + 1}.png"
                pixmap.save(str(target))
                rendered.append(str(target))
            if not rendered:
                return MediaResult(False, warnings=["no pages rendered"], backend="pymupdf")
            return MediaResult(True, {"rendered": rendered}, backend="pymupdf")
        finally:
            document.close()

    def merge(self, sources: list[Path], target: Path) -> MediaResult:
        if not self.available:
            return MediaResult(False, warnings=["pymupdf not installed"], backend="pymupdf")
        import pymupdf

        output = pymupdf.open()
        try:
            total = 0
            for source in sources:
                with self._open(source) as part:
                    output.insert_pdf(part)
                    total += part.page_count
            output.save(str(target))
            # Verification: reopen and count pages.
            with self._open(target) as check:
                if check.page_count != total:
                    return MediaResult(False, warnings=["merged page count mismatch"], backend="pymupdf")
            return MediaResult(True, {"output": str(target), "pages": total}, backend="pymupdf")
        finally:
            output.close()

    def split(self, source: Path, output_dir: Path) -> MediaResult:
        if not self.available:
            return MediaResult(False, warnings=["pymupdf not installed"], backend="pymupdf")
        output_dir.mkdir(parents=True, exist_ok=True)
        with self._open(source) as document:
            if document.page_count < 1:
                return MediaResult(False, warnings=["nothing to split"], backend="pymupdf")
            written = []
            for index in range(document.page_count):
                import pymupdf

                single = pymupdf.open()
                single.insert_pdf(document, from_page=index, to_page=index)
                target = output_dir / f"{Path(source).stem}-page-{index + 1}.pdf"
                single.save(str(target))
                single.close()
                written.append(str(target))
        return MediaResult(True, {"pages": written}, backend="pymupdf")
