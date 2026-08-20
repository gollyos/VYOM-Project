from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    from PIL import ImageGrab
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False


class ScreenCaptureUnavailableError(Exception):
    pass


@dataclass
class CaptureRegion:
    x: int
    y: int
    width: int
    height: int

    def bbox(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)


class ScreenCapture:
    """Capture only when needed: full screen, a specific monitor, a
    specific window's bounds, or an explicit region. There is no
    continuous recording -- every call is one deliberate capture, and
    every call site is expected to emit a `screen_captured` event."""

    def full_screen(self, path: Path) -> Path:
        return self._grab(path, bbox=None)

    def region(self, path: Path, region: CaptureRegion) -> Path:
        return self._grab(path, bbox=region.bbox())

    def monitor(self, path: Path, display) -> Path:
        x, y = display.position
        width, height = display.resolution
        return self._grab(path, bbox=(x, y, x + width, y + height))

    def window(self, path: Path, window_info) -> Path:
        bbox = (window_info.x, window_info.y, window_info.x + window_info.width, window_info.y + window_info.height)
        return self._grab(path, bbox=bbox)

    def _grab(self, path: Path, *, bbox: tuple[int, int, int, int] | None) -> Path:
        if not PIL_AVAILABLE:
            raise ScreenCaptureUnavailableError("Screen capture requires Pillow")
        path.parent.mkdir(parents=True, exist_ok=True)
        image = ImageGrab.grab(bbox=bbox)
        image.save(path)
        return path
