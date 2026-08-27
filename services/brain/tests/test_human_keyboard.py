"""Tests for HumanTypewriter and human-like typing simulation in KeyboardController."""
from __future__ import annotations

import pytest

from app.input_control.keyboard import HumanTypewriter, KeyboardController
from app.input_control.policy import InputSafetyPolicy, SensitiveInputBlockedError


class MockKeyboardBackend:
    def __init__(self):
        self.typed: list[tuple[str, bool]] = []
        self.pressed: list[str] = []
        self.hotkeys: list[tuple[str, ...]] = []

    def type_text(self, text: str, *, human_like: bool = True) -> None:
        self.typed.append((text, human_like))

    def press(self, key: str) -> None:
        self.pressed.append(key)

    def hotkey(self, *keys: str) -> None:
        self.hotkeys.append(keys)


def test_keystroke_delays_and_jitter():
    delay_char = HumanTypewriter.calculate_keystroke_delay("a")
    assert 0.02 <= delay_char <= 0.15

    delay_space = HumanTypewriter.calculate_keystroke_delay(" ")
    assert delay_space > delay_char

    delay_period = HumanTypewriter.calculate_keystroke_delay(".")
    assert delay_period > delay_char


def test_generate_keystroke_plan():
    plan = HumanTypewriter.generate_keystroke_plan("Hello world!", simulate_typos=False)
    assert len(plan) == len("Hello world!")
    for action, char, delay in plan:
        assert action == "type"
        assert delay > 0.02


def test_keyboard_controller_human_typing():
    backend = MockKeyboardBackend()
    policy = InputSafetyPolicy()
    controller = KeyboardController(backend, policy)

    controller.type_text("Haa bhai, kal milte hain", field_label="chat_input", context="whatsapp", human_like=True)
    assert len(backend.typed) == 1
    assert backend.typed[0] == ("Haa bhai, kal milte hain", True)


def test_keyboard_controller_sensitive_field_blocked():
    backend = MockKeyboardBackend()
    policy = InputSafetyPolicy()
    controller = KeyboardController(backend, policy)

    with pytest.raises(SensitiveInputBlockedError):
        controller.type_text("MySecret123", field_label="password", context="chrome")
