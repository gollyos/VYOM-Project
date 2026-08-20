from __future__ import annotations

from app.desktop.window_manager import WindowManager

from .capture import CaptureRegion


class RegionSelectorError(Exception):
    pass


class RegionSelector:
    """Resolves an explicit region or a window title into a CaptureRegion
    so a caller can request 'just this window,' not the whole desktop."""

    def __init__(self, window_manager: WindowManager):
        self.window_manager = window_manager

    def from_window(self, title_contains: str) -> CaptureRegion:
        matches = [window for window in self.window_manager.list() if title_contains.lower() in window.title.lower()]
        if not matches:
            raise RegionSelectorError(f"No window found matching '{title_contains}'")
        window = matches[0]
        return CaptureRegion(x=window.x, y=window.y, width=window.width, height=window.height)

    @staticmethod
    def explicit(x: int, y: int, width: int, height: int) -> CaptureRegion:
        if width <= 0 or height <= 0:
            raise RegionSelectorError("Region width/height must be positive")
        return CaptureRegion(x=x, y=y, width=width, height=height)
