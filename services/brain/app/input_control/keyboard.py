from __future__ import annotations

from typing import Protocol

from .policy import InputSafetyPolicy

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


class KeyboardBackend(Protocol):
    def type_text(self, text: str) -> None: ...
    def press(self, key: str) -> None: ...
    def hotkey(self, *keys: str) -> None: ...


class KeyboardAutomationUnavailableError(Exception):
    pass


class PyAutoGuiKeyboardBackend:
    """Real desktop keyboard control -- the controlled fallback tier."""

    def __init__(self):
        if not PYAUTOGUI_AVAILABLE:
            raise KeyboardAutomationUnavailableError("Keyboard automation requires pyautogui")

    def type_text(self, text: str) -> None:
        pyautogui.typewrite(text, interval=0.01)

    def press(self, key: str) -> None:
        pyautogui.press(key)

    def hotkey(self, *keys: str) -> None:
        pyautogui.hotkey(*keys)


class KeyboardController:
    """Controlled last-resort keyboard automation. Never types or submits
    passwords, MFA codes, payment credentials, recovery phrases, or other
    sensitive authentication secrets -- `InputSafetyPolicy` blocks these
    by field label and the caller must pause for user action instead."""

    def __init__(self, backend: KeyboardBackend, policy: InputSafetyPolicy):
        self.backend = backend
        self.policy = policy

    def type_text(self, text: str, *, field_label: str, context: str) -> None:
        self.policy.require_safe_target(context)
        self.policy.require_not_sensitive(field_label, text)
        self.backend.type_text(text)
        self.policy.record("keyboard_type", field_label, context)

    def press(self, key: str, *, context: str) -> None:
        self.policy.require_safe_target(context)
        self.backend.press(key)
        self.policy.record("keyboard_press", key, context)

    def shortcut(self, *keys: str, context: str) -> None:
        self.policy.require_safe_target(context)
        self.backend.hotkey(*keys)
        self.policy.record("keyboard_shortcut", "+".join(keys), context)
