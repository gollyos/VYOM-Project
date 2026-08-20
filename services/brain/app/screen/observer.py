from __future__ import annotations

from pathlib import Path

from app.desktop.window_manager import WindowManager

from .capture import ScreenCapture
from .privacy_filter import PrivacyFilter
from .visual_context import ScreenObservation


class ScreenObserver:
    """capture -> privacy filter -> structured ScreenObservation. Populates
    what is deterministically knowable (active app/window, geometry)
    without inventing visible_text; a vision-capable model may separately
    enrich visible_text/interactive_elements/possible_actions and should
    receive only the captured screenshot/region, never the full desktop
    when a single window is sufficient."""

    def __init__(self, capture: ScreenCapture, window_manager: WindowManager, privacy_filter: PrivacyFilter | None = None):
        self.capture = capture
        self.window_manager = window_manager
        self.privacy_filter = privacy_filter or PrivacyFilter()

    def observe_active_window(self, screenshot_path: Path) -> ScreenObservation:
        windows = [window for window in self.window_manager.list() if window.focused]
        active = windows[0] if windows else None

        if active and self.privacy_filter.is_sensitive_window(active.title):
            return ScreenObservation(
                active_window="[sensitive window -- capture skipped]",
                layout_summary="Capture skipped: window matched a configured sensitive-content hint.",
                confidence=0.0,
            )

        if active:
            self.capture.window(screenshot_path, active)
        else:
            self.capture.full_screen(screenshot_path)

        return ScreenObservation(
            active_application=active.app_id if active else None,
            active_window=active.title if active else None,
            layout_summary=(f"Captured window: {active.title}" if active else "Captured full screen") + f" ({screenshot_path.name}).",
            screenshot_path=str(screenshot_path),
            confidence=0.6 if active else 0.3,
        )
