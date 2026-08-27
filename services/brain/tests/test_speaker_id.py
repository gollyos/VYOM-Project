"""Tests for VoiceEnrollmentService (M6 Voice enrollment / Speaker ID).
Validates feature extraction, profile enrollment, speaker identification,
and owner verification.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path
import pytest

from app.voice.speaker_id import VoiceEnrollmentService


def _generate_pcm(freq: float, duration_s: float = 1.0, sample_rate: int = 16000) -> bytes:
    sample_count = int(sample_rate * duration_s)
    buffer = bytearray()
    for i in range(sample_count):
        t = i / sample_rate
        val = int(32767.0 * 0.8 * math.sin(2 * math.pi * freq * t))
        buffer.extend(struct.pack("<h", max(-32768, min(32767, val))))
    return bytes(buffer)


def test_feature_extraction():
    pcm1 = _generate_pcm(440.0)
    features = VoiceEnrollmentService.extract_features(pcm1)
    assert len(features) == 16
    assert any(f > 0 for f in features)


def test_enrollment_and_identification(tmp_path: Path):
    storage = tmp_path / "speakers.json"
    service = VoiceEnrollmentService(storage)

    owner_audio = [_generate_pcm(300.0), _generate_pcm(305.0)]
    guest_audio = [_generate_pcm(800.0), _generate_pcm(810.0)]

    service.enroll("owner_1", "Gunjan", "owner", owner_audio, threshold=0.75)
    service.enroll("guest_1", "Guest User", "guest", guest_audio, threshold=0.75)

    assert "owner_1" in service.profiles
    assert "guest_1" in service.profiles

    # Test identifying owner
    test_owner_voice = _generate_pcm(302.0)
    profile, score = service.identify(test_owner_voice)
    assert profile is not None
    assert profile.speaker_id == "owner_1"
    assert profile.role == "owner"
    assert score >= 0.75

    # Test verifying owner
    assert service.verify_owner(test_owner_voice) is True

    # Test identifying guest
    test_guest_voice = _generate_pcm(805.0)
    profile, score = service.identify(test_guest_voice)
    assert profile is not None
    assert profile.speaker_id == "guest_1"
    assert service.verify_owner(test_guest_voice) is False


def test_empty_audio_returns_zeros():
    features = VoiceEnrollmentService.extract_features(b"")
    assert features == [0.0] * 16
