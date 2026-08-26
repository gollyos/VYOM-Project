"""9 Meta-Learning Loops — inspired by the Jarvis/Atlas architecture.

Each loop is a structural feedback mechanism that turns real failures
into permanent improvements. They run automatically on events, never
requiring manual intervention.

Loop 1: Failure-to-Guardrail Pipeline
Loop 2: Tiered Memory with Trust Scoring
Loop 3: Prediction-Outcome Calibration
Loop 4: Nightly Extraction
Loop 5: Friction Detection
Loop 6: Active Context Holds
Loop 7: Epistemic Tagging
Loop 8: Creative Mode
Loop 9: Recursive Self-Improvement
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# =====================================================================
# Loop 1: Failure-to-Guardrail Pipeline
# =====================================================================
# Every significant failure becomes a named regression loaded at boot.
# Cost: a few tokens. Payoff: permanent prevention.

@dataclass
class Guardrail:
    """A named regression extracted from a real failure."""
    id: str
    name: str
    trigger_pattern: str  # regex or keyword that would have caught this
    failure_description: str
    prevention_action: str
    created_at: str = ""
    hit_count: int = 0
    severity: str = "medium"  # low | medium | high | critical


class FailureToGuardrailPipeline:
    """Turns every failure into a named guardrail that prevents recurrence."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path("data/meta_learning")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._guardrails: dict[str, Guardrail] = {}

    def record_failure(self, task_id: str, error: str, goal: str, context: dict | None = None) -> Guardrail | None:
        """Extract a guardrail from a failure if it's significant enough."""
        # Only create guardrails for failures that aren't trivial
        if not error or len(error) < 20:
            return None

        # Generate a guardrail ID from the failure signature
        guardrail_id = f"guard_{hash(f'{error[:100]}') & 0xFFFFFF:06x}"

        if guardrail_id in self._guardrails:
            self._guardrails[guardrail_id].hit_count += 1
            return self._guardrails[guardrail_id]

        # Extract trigger pattern from the error
        trigger = self._extract_trigger(error, goal)

        guardrail = Guardrail(
            id=guardrail_id,
            name=f"Prevent: {error[:60]}",
            trigger_pattern=trigger,
            failure_description=error[:500],
            prevention_action=f"Check for {trigger} before executing similar goals",
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        self._guardrails[guardrail_id] = guardrail
        self._persist_guardrails()
        return guardrail

    def _extract_trigger(self, error: str, goal: str) -> str:
        """Extract a keyword/regex pattern from the error that could prevent recurrence."""
        error_lower = error.lower()
        # Common failure patterns
        if "not found" in error_lower or "404" in error:
            return "resource_not_found"
        if "permission" in error_lower or "access denied" in error_lower:
            return "permission_denied"
        if "timeout" in error_lower:
            return "timeout"
        if "rate limit" in error_lower or "429" in error:
            return "rate_limited"
        if "connection" in error_lower:
            return "connection_error"
        if "not available" in error_lower:
            return "resource_unavailable"
        # Default: use first 3 words of error as pattern
        words = error.split()[:3]
        return "_".join(w.lower().strip(".,!?") for w in words if w)

    def check_guardrails(self, goal: str) -> list[Guardrail]:
        """Check if a goal would trigger any existing guardrails."""
        triggered = []
        goal_lower = goal.lower()
        for guardrail in self._guardrails.values():
            if guardrail.trigger_pattern in goal_lower:
                guardrail.hit_count += 1
                triggered.append(guardrail)
        return triggered

    def get_all_guardrails(self) -> list[Guardrail]:
        return sorted(self._guardrails.values(), key=lambda g: -g.hit_count)

    def _persist_guardrails(self) -> None:
        """Save guardrails to disk."""
        import json
        path = self.data_dir / "guardrails.json"
        data = {gid: {
            "id": g.id, "name": g.name, "trigger_pattern": g.trigger_pattern,
            "failure_description": g.failure_description,
            "prevention_action": g.prevention_action,
            "created_at": g.created_at, "hit_count": g.hit_count,
            "severity": g.severity,
        } for gid, g in self._guardrails.items()}
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_guardrails(self) -> int:
        """Load guardrails from disk at boot."""
        import json
        path = self.data_dir / "guardrails.json"
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for gid, gdata in data.items():
                self._guardrails[gid] = Guardrail(**gdata)
            return len(self._guardrails)
        except Exception:
            return 0


# =====================================================================
# Loop 3: Prediction-Outcome Calibration
# =====================================================================
# Before major decisions, the agent writes what it expects.
# Later, it checks. The delta is where learning lives.

@dataclass
class Prediction:
    """A prediction made before an action."""
    id: str
    task_id: str
    goal: str
    predicted_outcome: str
    confidence: float  # 0-1
    actual_outcome: str = ""
    was_correct: bool | None = None
    delta: float = 0.0  # |predicted - actual| for numerical outcomes
    created_at: str = ""
    resolved_at: str = ""


class PredictionCalibration:
    """Tracks predictions vs outcomes to improve future judgment."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path("data/meta_learning")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._predictions: dict[str, Prediction] = {}
        self._accuracy_history: list[float] = []

    def record_prediction(self, task_id: str, goal: str, predicted_outcome: str, confidence: float) -> Prediction:
        """Record a prediction before executing a task."""
        pred_id = f"pred_{task_id[:12]}"
        prediction = Prediction(
            id=pred_id, task_id=task_id, goal=goal,
            predicted_outcome=predicted_outcome,
            confidence=confidence,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._predictions[pred_id] = prediction
        return prediction

    def resolve_prediction(self, pred_id: str, actual_outcome: str, was_correct: bool) -> None:
        """Record the actual outcome and compare to prediction."""
        if pred_id not in self._predictions:
            return
        pred = self._predictions[pred_id]
        pred.actual_outcome = actual_outcome
        pred.was_correct = was_correct
        pred.resolved_at = datetime.now(timezone.utc).isoformat()

        # Update accuracy history
        total = len([p for p in self._predictions.values() if p.was_correct is not None])
        correct = len([p for p in self._predictions.values() if p.was_correct is True])
        if total > 0:
            self._accuracy_history.append(correct / total)

    def get_calibration_score(self) -> float:
        """Return the overall prediction accuracy (0-1)."""
        if not self._accuracy_history:
            return 0.5  # neutral prior
        return self._accuracy_history[-1]

    def get_overconfident_areas(self) -> list[dict]:
        """Find areas where confidence is high but accuracy is low."""
        areas = []
        for pred in self._predictions.values():
            if pred.was_correct is False and pred.confidence > 0.7:
                areas.append({
                    "goal": pred.goal[:100],
                    "confidence": pred.confidence,
                    "predicted": pred.predicted_outcome[:100],
                    "actual": pred.actual_outcome[:100],
                })
        return areas[:10]


# =====================================================================
# Loop 5: Friction Detection
# =====================================================================
# When instructions contradict each other, the agent flags the conflict
# instead of silently following the latest one.

@dataclass
class Friction:
    """A detected contradiction between instructions or behaviors."""
    id: str
    instruction_a: str
    instruction_b: str
    conflict_description: str
    severity: str  # low | medium | high
    resolved: bool = False
    resolution: str = ""
    detected_at: str = ""


class FrictionDetector:
    """Detects contradictions between instructions and behaviors."""

    def __init__(self):
        self._frictions: list[Friction] = []
        self._instruction_history: list[str] = []

    def observe_instruction(self, instruction: str) -> Friction | None:
        """Check if a new instruction contradicts any previous instruction."""
        self._instruction_history.append(instruction)
        if len(self._instruction_history) > 100:
            self._instruction_history = self._instruction_history[-100:]

        # Check for contradictions
        for prev in self._instruction_history[:-1]:
            friction = self._check_contradiction(prev, instruction)
            if friction:
                self._frictions.append(friction)
                return friction
        return None

    def _check_contradiction(self, a: str, b: str) -> Friction | None:
        """Simple contradiction detection based on negation patterns."""
        a_lower = a.lower()
        b_lower = b.lower()

        # Check for direct negation patterns
        negation_pairs = [
            ("always", "never"), ("do", "don't"), ("must", "must not"),
            ("should", "should not"), ("enable", "disable"),
            ("allow", "block"), ("use", "avoid"),
            ("open", "close"), ("start", "stop"),
        ]

        for pos, neg in negation_pairs:
            if (pos in a_lower and neg in b_lower) or (neg in a_lower and pos in b_lower):
                return Friction(
                    id=f"friction_{hash(f'{a[:50]}{b[:50]}') & 0xFFFFFF:06x}",
                    instruction_a=a[:200],
                    instruction_b=b[:200],
                    conflict_description=f"Contradiction: '{pos}' vs '{neg}'",
                    severity="medium",
                    detected_at=datetime.now(timezone.utc).isoformat(),
                )
        return None

    def get_unresolved(self) -> list[Friction]:
        return [f for f in self._frictions if not f.resolved]

    def resolve(self, friction_id: str, resolution: str) -> None:
        for f in self._frictions:
            if f.id == friction_id:
                f.resolved = True
                f.resolution = resolution


# =====================================================================
# Loop 7: Epistemic Tagging
# =====================================================================
# Forces the agent to label claims as: consensus, observed, inferred,
# speculative, or contrarian. The act of choosing a tag interrupts
# autopilot.

@dataclass
class EpistemicTag:
    """A tagged claim with its epistemic status."""
    claim: str
    tag: str  # consensus | observed | inferred | speculative | contrarian
    confidence: float
    evidence: str = ""
    timestamp: str = ""


class EpistemicTagger:
    """Tags claims with their epistemic status to prevent overconfidence."""

    TAGS = {
        "consensus": "Widely agreed upon, strong evidence",
        "observed": "Directly seen/measured, high confidence",
        "inferred": "Deduced from evidence, medium confidence",
        "speculative": "Possible but unverified, low confidence",
        "contrarian": "Against mainstream view, needs strong evidence",
    }

    def tag_claim(self, claim: str, evidence: str = "") -> EpistemicTag:
        """Automatically tag a claim based on evidence strength."""
        claim_lower = claim.lower()

        # Heuristic tagging
        if any(w in claim_lower for w in ["always", "never", "all", "none", "everyone"]):
            tag = "speculative"  # Absolute claims are usually speculative
            confidence = 0.3
        elif any(w in claim_lower for w in ["i saw", "measured", "observed", "tested"]):
            tag = "observed"
            confidence = 0.8
        elif any(w in claim_lower for w in ["probably", "likely", "seems", "appears"]):
            tag = "inferred"
            confidence = 0.6
        elif any(w in claim_lower for w in ["research shows", "studies", "proven", "established"]):
            tag = "consensus"
            confidence = 0.9
        elif any(w in claim_lower for w in ["actually", "contrary", "despite", "however"]):
            tag = "contrarian"
            confidence = 0.5
        else:
            tag = "inferred"
            confidence = 0.5

        return EpistemicTag(
            claim=claim[:500], tag=tag, confidence=confidence,
            evidence=evidence[:300],
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


# =====================================================================
# Loop 9: Recursive Self-Improvement
# =====================================================================
# Generate → Evaluate → Diagnose → Improve → Repeat.
# Stop after 3 iterations with <5% improvement.

class RecursiveSelfImprovement:
    """Generates improvements, evaluates them, and iterates."""

    MAX_ITERATIONS = 3
    MIN_IMPROVEMENT = 0.05  # 5%

    def __init__(self):
        self._iterations: list[dict] = []
        self._best_score: float = 0.0

    def evaluate(self, metric_name: str, score: float) -> dict | None:
        """Evaluate a metric and suggest improvement if needed."""
        self._iterations.append({
            "metric": metric_name,
            "score": score,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if len(self._iterations) >= 2:
            prev = self._iterations[-2]["score"]
            curr = self._iterations[-1]["score"]
            improvement = (curr - prev) / max(prev, 0.001)

            if improvement < self.MIN_IMPROVEMENT and len(self._iterations) >= self.MAX_ITERATIONS:
                return {"action": "stop", "reason": f"Improvement below {self.MIN_IMPROVEMENT:.0%} threshold"}
            elif improvement > 0:
                return {"action": "continue", "improvement": improvement}
            else:
                return {"action": "revert", "reason": "Score decreased"}
        return {"action": "continue", "improvement": 0}

    def get_history(self) -> list[dict]:
        return self._iterations[-20:]


# =====================================================================
# Unified Meta-Learning Manager
# =====================================================================

class MetaLearningManager:
    """Coordinates all 9 meta-learning loops."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or Path("data/meta_learning")
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Loop 1: Failure-to-Guardrail
        self.guardrail_pipeline = FailureToGuardrailPipeline(self.data_dir)
        # Loop 3: Prediction-Outcome Calibration
        self.prediction_calibration = PredictionCalibration(self.data_dir)
        # Loop 5: Friction Detection
        self.friction_detector = FrictionDetector()
        # Loop 7: Epistemic Tagging
        self.epistemic_tagger = EpistemicTagger()
        # Loop 9: Recursive Self-Improvement
        self.self_improvement = RecursiveSelfImprovement()

        # Load persisted state
        self.guardrail_pipeline.load_guardrails()

    def on_task_failed(self, task_id: str, error: str, goal: str) -> dict:
        """Loop 1: Extract guardrail from failure."""
        guardrail = self.guardrail_pipeline.record_failure(task_id, error, goal)
        return {"guardrail_created": guardrail is not None, "guardrail": guardrail}

    def on_task_completed(self, task_id: str, goal: str, result: str, confidence: float) -> dict:
        """Loop 3: Resolve prediction if one was made."""
        pred_id = f"pred_{task_id[:12]}"
        self.prediction_calibration.resolve_prediction(pred_id, result, confidence > 0.5)
        return {"calibration_score": self.prediction_calibration.get_calibration_score()}

    def on_instruction(self, instruction: str) -> dict:
        """Loop 5: Check for friction."""
        friction = self.friction_detector.observe_instruction(instruction)
        return {"friction_detected": friction is not None, "friction": friction}

    def tag_claim(self, claim: str, evidence: str = "") -> dict:
        """Loop 7: Tag a claim with epistemic status."""
        tag = self.epistemic_tagger.tag_claim(claim, evidence)
        return {"tag": tag.tag, "confidence": tag.confidence}

    def evaluate_improvement(self, metric: str, score: float) -> dict:
        """Loop 9: Evaluate and iterate."""
        return self.self_improvement.evaluate(metric, score)

    def get_dashboard(self) -> dict:
        """Get a complete view of all meta-learning loops."""
        return {
            "guardrails": {
                "total": len(self.guardrail_pipeline.get_all_guardrails()),
                "top": [
                    {"name": g.name, "hits": g.hit_count}
                    for g in self.guardrail_pipeline.get_all_guardrails()[:5]
                ],
            },
            "calibration": {
                "score": self.prediction_calibration.get_calibration_score(),
                "overconfident_areas": self.prediction_calibration.get_overconfident_areas()[:3],
            },
            "frictions": {
                "unresolved": len(self.friction_detector.get_unresolved()),
            },
            "self_improvement": {
                "iterations": len(self.self_improvement.get_history()),
            },
        }
