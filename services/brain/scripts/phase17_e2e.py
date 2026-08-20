"""Phase 17 end-to-end mission.

User goal -> cognitive resolution -> memory/experience -> planner ->
tool/model routing -> execution -> failure -> adaptation ->
verification -> experience learning -> final visual report (a real
UIComposition event streamed through the existing Composer contract).
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN))


def _composition(mission, goal: str) -> dict:
    from datetime import datetime, timezone

    steps = [
        {"feature": step.title[:60], "option": step.status, "notes": "verified" if step.verified else str(step.output)[:40]}
        for step in mission.completed[:6]
    ]
    return {
        "schemaVersion": 1, "id": f"mission-report-{mission.mission_id}", "mode": "brain-context",
        "label": "Mission Report", "summary": f"Mission {mission.status}: {goal[:90]}",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "objects": [
            {
                "id": "mission-summary", "type": "verified-result", "title": "Mission outcome",
                "eyebrow": "End-to-end", "tone": "verified" if mission.status == "completed" else "attention",
                "frame": {"x": 16, "y": 12, "width": 44}, "statement":
                f"{len(mission.completed)} steps executed, "
                f"{sum(1 for s in mission.completed if s.verified)} verified; "
                f"experience saved: {mission.experience_saved}.",
                "evidence": [f"status:{mission.status}"], "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            {
                "id": "mission-steps", "type": "comparison-table", "title": "Steps",
                "eyebrow": "Verified trail", "frame": {"x": 62, "y": 16, "width": 34, "layer": 2},
                "headers": ["Step", "Status", "Result"],
                "rows": [[row["feature"], row["option"], row["notes"]] for row in steps] or [["-", "-", "-"]],
            },
        ],
        "sequence": [
            {"id": "reveal-0", "label": obj["eyebrow"], "atMs": index * 300,
             "state": "Verifying", "objectIds": [obj["id"]]}
            for index, obj in enumerate([
                {"id": "mission-summary", "eyebrow": "Mission outcome"},
                {"id": "mission-steps", "eyebrow": "Steps"},
            ])
        ],
    }


async def main() -> None:
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    from app.schemas.events import BrainEvent, EventType

    with tempfile.TemporaryDirectory(prefix="vyom-e2e-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = Settings(
            database_path=base / "e2e.db", skills_root=base / "skills", agents_root=base / "agents",
            audit_log_path=base / "audit.jsonl", secret_store_path=base / "secrets",
            artifacts_root=base / "artifacts", backup_root=base / "backups",
        )
        with TestClient(create_app(settings)) as client:
            state = client.app.state

            # 1) Seed verified memory the mission should reuse (no re-explanation).
            from app.memory.namespaces import CognitiveNamespace

            await state.namespace_router.remember(
                CognitiveNamespace.RESEARCH, "Vyom market position",
                "Vyom's differentiation is the living neural core plus verifiable evidence trails.",
                provenance_reference="verified research 2026", confidence=0.9,
            )

            # 2) The user goal (genuinely multi-step).
            goal = ("Research the Vyom competitive position with citations, extract the pricing page, "
                    "verify the evidence, and report with a visual summary")

            # 3) Run the deep-research mission pack through the ONE loop.
            mission = await state.run_mission_pack("deep-research", state, goal=goal, context={
                "url": "https://example.com/pricing",
            })
            assert mission.status == "completed", mission.status

            # 4) Confirm cognitive resolution ran (memory-first).
            answer = await state.cognitive_runtime.answer_from_memory("What is Vyom's market position?")
            assert answer is not None and "neural core" in str(answer.get("answer"))

            # 5) Confirm experience learning recorded the mission AND the
            # one real extraction it performed. Note: the "Research..."
            # step's sources come from LocalFixtureSearchProvider, which
            # is deliberately synthetic (docs.example.test placeholders)
            # and must never trigger a live fetch/browser call - so the
            # real, safely-verified experience count for this mission is
            # the "Extract the pricing page" step (one genuine, bounded
            # browser-backed extraction of a real URL) plus the mission
            # outcome itself, not an arbitrary higher count that would
            # require either an unsafe live network call against a known-
            # fake source or a live web-search provider (explicitly
            # disabled for automated/offline runs - see config/research.yaml).
            metrics = await state.improvement_metrics.snapshot()
            assert metrics["mission_outcomes"]["count"] >= 1
            assert metrics["total_experiences"] >= 2
            assert metrics["extraction_outcomes"], "the real pricing-page extraction should have recorded a learned-routing outcome"

            # 6) Final visual report through the existing Composer contract.
            composition = _composition(mission, goal)
            await state.event_bus.publish(BrainEvent(
                task_id=mission.mission_id, type=EventType.VISUALIZATION_REQUESTED,
                human_readable_message=f"Mission complete: {len(mission.completed)} steps, verified",
                structured_payload={"layout": "contextual", "composition": composition},
            ))
            published = [event for event in state.event_bus.history
                         if event.type == EventType.VISUALIZATION_REQUESTED]
            assert published and published[-1].structured_payload["composition"]["id"].startswith("mission-report")

            print(f"E2E PASSED: mission={mission.status} steps={len(mission.completed)} "
                  f"verified={sum(1 for s in mission.completed if s.verified)} "
                  f"experiences={metrics['total_experiences']} "
                  f"visual_report={composition['id']}")


if __name__ == "__main__":
    asyncio.run(main())
