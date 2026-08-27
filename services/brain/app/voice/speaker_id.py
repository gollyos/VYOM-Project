"""
Voice Enrollment and Speaker Identification System for VYOM.
Allows the owner to enroll voice samples, creates an acoustic speaker fingerprint,
and validates incoming voice commands for Owner / Family / Guest roles.
"""
from __future__ import annotations

import json
import math
import struct
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class SpeakerProfile:
    speaker_id: str
    name: str
    role: str  # "owner" | "family" | "guest"
    feature_vector: list[float]
    threshold: float = 0.78
    enrolled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class VoiceEnrollmentService:
    def __init__(self, storage_path: Path | None = None):
        self.storage_path = storage_path or Path("services/brain/data/speaker_profiles.json")
        self.profiles: dict[str, SpeakerProfile] = {}
        self._load()

    def _load(self) -> None:
        if self.storage_path.exists():
            try:
                data = json.loads(self.storage_path.read_text(encoding="utf-8"))
                for item in data.get("profiles", []):
                    profile = SpeakerProfile(**item)
                    self.profiles[profile.speaker_id] = profile
            except Exception:
                self.profiles = {}

    def _save(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"profiles": [asdict(p) for p in self.profiles.values()]}
        self.storage_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def extract_features(pcm_bytes: bytes) -> list[float]:
        """Extract lightweight acoustic spectral fingerprint from 16-bit PCM audio."""
        if not pcm_bytes or len(pcm_bytes) < 32:
            return [0.0] * 16

        sample_count = len(pcm_bytes) // 2
        samples: list[float] = []
        for i in range(0, len(pcm_bytes) - 1, 2):
            sample = struct.unpack_from("<h", pcm_bytes, i)[0] / 32768.0
            samples.append(sample)

        # 1. Zero crossing rate
        zcr = sum(1 for i in range(1, len(samples)) if (samples[i] >= 0) != (samples[i - 1] >= 0)) / max(len(samples), 1)

        # 2. RMS Energy
        rms = math.sqrt(sum(s * s for s in samples) / max(len(samples), 1))

        # 3. Frequency band energy distribution (split into 14 pseudo-spectral bins)
        bin_size = max(len(samples) // 14, 1)
        bin_energies = []
        for b in range(14):
            chunk = samples[b * bin_size : (b + 1) * bin_size]
            energy = math.sqrt(sum(c * c for c in chunk) / max(len(chunk), 1)) if chunk else 0.0
            bin_energies.append(energy)

        # Combine into normalized 16-dimensional feature vector
        vector = [zcr * 10.0, rms * 10.0] + bin_energies
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            return [v / norm for v in vector]
        return [0.0] * 16

    @staticmethod
    def cosine_similarity(v1: list[float], v2: list[float]) -> float:
        if len(v1) != len(v2) or not v1:
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        norm1 = math.sqrt(sum(a * a for a in v1))
        norm2 = math.sqrt(sum(b * b for b in v2))
        if norm1 == 0 or norm2 == 0:
            return 0.0
        return max(0.0, min(1.0, dot / (norm1 * norm2)))

    def enroll(self, speaker_id: str, name: str, role: str, audio_samples: list[bytes], threshold: float = 0.78) -> SpeakerProfile:
        if not audio_samples:
            raise ValueError("At least one audio sample is required for voice enrollment.")

        vectors = [self.extract_features(sample) for sample in audio_samples]
        dim = len(vectors[0])
        avg_vector = [sum(v[i] for v in vectors) / len(vectors) for i in range(dim)]
        norm = math.sqrt(sum(x * x for x in avg_vector))
        if norm > 0:
            avg_vector = [x / norm for x in avg_vector]

        profile = SpeakerProfile(
            speaker_id=speaker_id,
            name=name,
            role=role.lower(),
            feature_vector=avg_vector,
            threshold=threshold,
        )
        self.profiles[speaker_id] = profile
        self._save()
        return profile

    def identify(self, audio_bytes: bytes) -> tuple[SpeakerProfile | None, float]:
        if not self.profiles:
            return None, 0.0

        query_vec = self.extract_features(audio_bytes)
        best_profile: SpeakerProfile | None = None
        best_sim = 0.0

        for profile in self.profiles.values():
            sim = self.cosine_similarity(query_vec, profile.feature_vector)
            if sim > best_sim and sim >= profile.threshold:
                best_sim = sim
                best_profile = profile

        return best_profile, best_sim

    def verify_owner(self, audio_bytes: bytes) -> bool:
        profile, confidence = self.identify(audio_bytes)
        return profile is not None and profile.role == "owner"
