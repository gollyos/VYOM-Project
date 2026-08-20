from __future__ import annotations

from typing import Protocol

from .schemas import StartupStatus


class StartupBackend(Protocol):
    def enable(self, name: str, command: str) -> None: ...
    def disable(self, name: str) -> None: ...
    def is_enabled(self, name: str) -> bool: ...


class WindowsRegistryStartupBackend:
    """Registers/removes a value under
    HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run. User-scoped,
    fully reversible, and requires no elevated/admin permission -- distinct
    from the L3 'admin/elevated action' boundary."""

    KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def enable(self, name: str, command: str) -> None:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)

    def disable(self, name: str) -> None:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass

    def is_enabled(self, name: str) -> bool:
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.KEY_PATH, 0, winreg.KEY_READ) as key:
                winreg.QueryValueEx(key, name)
                return True
        except FileNotFoundError:
            return False


class InMemoryStartupBackend:
    """Test-only backend. Never touches the real OS -- used so automated
    tests can verify enable/disable/status logic without altering the
    developer machine's real startup configuration."""

    def __init__(self):
        self._entries: dict[str, str] = {}

    def enable(self, name: str, command: str) -> None:
        self._entries[name] = command

    def disable(self, name: str) -> None:
        self._entries.pop(name, None)

    def is_enabled(self, name: str) -> bool:
        return name in self._entries


class StartupController:
    """startup.enable / startup.disable / startup.status. Default is
    disabled (config/desktop.yaml) and is never enabled automatically by
    code, dev runs, or tests -- only an explicit, permission-checked user
    request may call enable()."""

    ENTRY_NAME = "VYOM"

    def __init__(self, backend: StartupBackend, executable_path: str):
        self.backend = backend
        self.executable_path = executable_path

    def enable(self) -> StartupStatus:
        self.backend.enable(self.ENTRY_NAME, f'"{self.executable_path}"')
        return self.status()

    def disable(self) -> StartupStatus:
        self.backend.disable(self.ENTRY_NAME)
        return self.status()

    def status(self) -> StartupStatus:
        enabled = self.backend.is_enabled(self.ENTRY_NAME)
        return StartupStatus(
            enabled=enabled, method="windows_registry_run_key",
            detail=self.executable_path if enabled else "",
        )
