from __future__ import annotations

from .schemas import DisplayInfo, WindowInfo

try:
    import pygetwindow as gw
    PYGETWINDOW_AVAILABLE = True
except ImportError:
    PYGETWINDOW_AVAILABLE = False

try:
    from screeninfo import get_monitors
    SCREENINFO_AVAILABLE = True
except ImportError:
    SCREENINFO_AVAILABLE = False


class WindowManagerUnavailableError(Exception):
    pass


class WindowNotFoundError(Exception):
    pass


class WindowManager:
    """window.list / focus / minimize / maximize / restore / move / resize
    through native OS window APIs (pygetwindow wraps Win32 on Windows).
    Never relies on mouse dragging."""

    def _require_backend(self) -> None:
        if not PYGETWINDOW_AVAILABLE:
            raise WindowManagerUnavailableError("Window management requires pygetwindow (Windows)")

    def list(self) -> list[WindowInfo]:
        self._require_backend()
        windows = []
        for index, window in enumerate(gw.getAllWindows()):
            if not window.title:
                continue
            windows.append(WindowInfo(
                window_id=index, title=window.title, x=window.left, y=window.top,
                width=window.width, height=window.height,
                minimized=window.isMinimized, maximized=window.isMaximized,
                focused=window.isActive,
            ))
        return windows

    def _find(self, title_contains: str):
        self._require_backend()
        matches = gw.getWindowsWithTitle(title_contains)
        if not matches:
            raise WindowNotFoundError(f"No window found matching '{title_contains}'")
        return matches[0]

    @staticmethod
    def _to_info(window, **overrides) -> WindowInfo:
        base = dict(
            window_id=0, title=window.title, x=window.left, y=window.top,
            width=window.width, height=window.height,
            minimized=window.isMinimized, maximized=window.isMaximized, focused=window.isActive,
        )
        base.update(overrides)
        return WindowInfo(**base)

    def focus(self, title_contains: str) -> WindowInfo:
        window = self._find(title_contains)
        try:
            window.activate()
        except Exception as error:  # pragma: no cover - platform-specific
            # pygetwindow raises even when Windows reports success (error
            # code 0) because SetForegroundWindow's return value is
            # unreliable when called from a background process. Only
            # surface genuine, non-zero Windows error codes.
            if "Windows: 0" not in str(error):
                raise
        return self._to_info(window, focused=True)

    def minimize(self, title_contains: str) -> WindowInfo:
        window = self._find(title_contains)
        window.minimize()
        return self._to_info(window, minimized=True)

    def maximize(self, title_contains: str) -> WindowInfo:
        window = self._find(title_contains)
        window.maximize()
        return self._to_info(window, maximized=True)

    def restore(self, title_contains: str) -> WindowInfo:
        window = self._find(title_contains)
        window.restore()
        return self._to_info(window)

    def move(self, title_contains: str, x: int, y: int) -> WindowInfo:
        window = self._find(title_contains)
        window.moveTo(x, y)
        return self._to_info(window, x=x, y=y)

    def resize(self, title_contains: str, width: int, height: int) -> WindowInfo:
        window = self._find(title_contains)
        window.resizeTo(width, height)
        return self._to_info(window, width=width, height=height)

    def displays(self) -> list[DisplayInfo]:
        if not SCREENINFO_AVAILABLE:
            raise WindowManagerUnavailableError("Display enumeration requires screeninfo")
        displays = []
        for index, monitor in enumerate(get_monitors()):
            displays.append(DisplayInfo(
                display_id=index,
                resolution=(monitor.width, monitor.height),
                position=(monitor.x, monitor.y),
                primary=bool(getattr(monitor, "is_primary", index == 0)),
            ))
        return displays
