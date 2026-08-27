from __future__ import annotations

import random
import time
from typing import Protocol

from .policy import InputSafetyPolicy

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False


class KeyboardBackend(Protocol):
    def type_text(self, text: str, *, human_like: bool = True) -> None: ...
    def press(self, key: str) -> None: ...
    def hotkey(self, *keys: str) -> None: ...


class KeyboardAutomationUnavailableError(Exception):
    pass


class HumanTypewriter:
    """Simulates realistic human typing rhythms, Gaussian inter-keystroke intervals,
    punctuation micro-pauses, and natural typo self-corrections to prevent bot detection."""

    ADJACENT_KEYS: dict[str, list[str]] = {
        "a": ["q", "w", "s", "z"],
        "b": ["v", "g", "h", "n"],
        "c": ["x", "d", "f", "v"],
        "d": ["s", "e", "r", "f", "c", "x"],
        "e": ["w", "r", "d", "s"],
        "f": ["d", "r", "t", "g", "v", "c"],
        "g": ["f", "t", "y", "h", "b", "v"],
        "h": ["g", "y", "u", "j", "n", "b"],
        "i": ["u", "o", "k", "j"],
        "j": ["h", "u", "i", "k", "m", "n"],
        "k": ["j", "i", "o", "l", "m"],
        "l": ["k", "o", "p"],
        "m": ["n", "j", "k"],
        "n": ["b", "h", "j", "m"],
        "o": ["i", "p", "k", "l"],
        "p": ["o", "l"],
        "q": ["w", "a"],
        "r": ["e", "t", "f", "d"],
        "s": ["a", "w", "e", "d", "x", "z"],
        "t": ["r", "y", "g", "f"],
        "u": ["y", "i", "j", "h"],
        "v": ["c", "f", "g", "b"],
        "w": ["q", "e", "s", "a"],
        "x": ["z", "s", "d", "c"],
        "y": ["t", "u", "h", "g"],
        "z": ["a", "s", "x"],
    }

    @classmethod
    def calculate_keystroke_delay(cls, char: str, prev_char: str | None = None) -> float:
        # Base typing speed: 45ms to 85ms
        base_delay = random.uniform(0.045, 0.085)

        # Space/word boundary: micro-pause (110ms - 220ms)
        if char == " ":
            return random.uniform(0.11, 0.22)
        # Sentence/punctuation boundary: longer pause (180ms - 320ms)
        if char in {".", ",", "!", "?", ";", ":", "\n"}:
            return random.uniform(0.18, 0.32)
        # Shift / special character key
        if char.isupper() or char in {"@", "#", "$", "%", "&", "*", "(", ")", "_", "+", "{", "}"}:
            base_delay += random.uniform(0.04, 0.09)

        # Natural Gaussian rhythm fluctuation
        jitter = random.gauss(0, 0.015)
        return max(0.025, base_delay + jitter)

    @classmethod
    def generate_keystroke_plan(cls, text: str, *, simulate_typos: bool = True) -> list[tuple[str, str, float]]:
        """Generates a list of ('type' | 'press', char_or_key, delay_seconds)."""
        plan: list[tuple[str, str, float]] = []
        prev_char: str | None = None

        for idx, char in enumerate(text):
            delay = cls.calculate_keystroke_delay(char, prev_char)
            # Typo simulation: 1.5% chance on lowercase alpha if text is long enough
            if simulate_typos and char.lower() in cls.ADJACENT_KEYS and random.random() < 0.015 and idx > 3:
                wrong_char = random.choice(cls.ADJACENT_KEYS[char.lower()])
                # Type wrong character
                plan.append(("type", wrong_char, delay))
                # Reaction pause (120ms - 250ms)
                plan.append(("press", "backspace", random.uniform(0.12, 0.25)))
                # Type correct character
                plan.append(("type", char, random.uniform(0.06, 0.12)))
            else:
                plan.append(("type", char, delay))

            prev_char = char

        return plan


class PyAutoGuiKeyboardBackend:
    """Real desktop keyboard control with humanized anti-bot typing rhythms."""

    def __init__(self, human_typewriter: HumanTypewriter | None = None):
        if not PYAUTOGUI_AVAILABLE:
            raise KeyboardAutomationUnavailableError("Keyboard automation requires pyautogui")
        self.typewriter = human_typewriter or HumanTypewriter()

    def type_text(self, text: str, *, human_like: bool = True) -> None:
        if not human_like:
            pyautogui.typewrite(text, interval=0.01)
            return

        plan = self.typewriter.generate_keystroke_plan(text, simulate_typos=True)
        for action, key_or_char, delay in plan:
            if action == "type":
                pyautogui.write(key_or_char)
            elif action == "press":
                pyautogui.press(key_or_char)
            if delay > 0:
                time.sleep(delay)

    def press(self, key: str) -> None:
        pyautogui.press(key)

    def hotkey(self, *keys: str) -> None:
        pyautogui.hotkey(*keys)


class KeyboardController:
    """Controlled last-resort keyboard automation with human typing simulator.
    Never types or submits passwords, MFA codes, payment credentials, recovery phrases,
    or other sensitive authentication secrets -- `InputSafetyPolicy` blocks these."""

    def __init__(self, backend: KeyboardBackend, policy: InputSafetyPolicy):
        self.backend = backend
        self.policy = policy

    def type_text(self, text: str, *, field_label: str, context: str, human_like: bool = True) -> None:
        self.policy.require_safe_target(context)
        self.policy.require_not_sensitive(field_label, text)
        self.backend.type_text(text, human_like=human_like)
        self.policy.record("keyboard_type", field_label, context)

    def press(self, key: str, *, context: str) -> None:
        self.policy.require_safe_target(context)
        self.backend.press(key)
        self.policy.record("keyboard_press", key, context)

    def shortcut(self, *keys: str, context: str) -> None:
        self.policy.require_safe_target(context)
        self.backend.hotkey(*keys)
        self.policy.record("keyboard_shortcut", "+".join(keys), context)
