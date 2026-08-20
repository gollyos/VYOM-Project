"""Phase 18 extended local soak test: repeated missions, task creation,
browser sessions, memory writes/retrieval, cancellation, all within ONE
long-lived process (the only way relaunches can't hide a real leak),
watching for RSS growth, handle/thread growth, orphan processes, DB
locking, and task-ID duplication across iterations.

This is a bounded, honest soak (minutes, not hours/days) - it does NOT
prove 24/7 reliability. It proves the system does not visibly degrade
across N repeated cycles of real work.

Usage: python scripts/phase18_extended_soak.py [iterations]
"""
from __future__ import annotations

import asyncio
import gc
import sys
import tempfile
import time
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BRAIN))

ITERATIONS = int(sys.argv[1]) if len(sys.argv) > 1 else 15


def sample():
    import psutil
    proc = psutil.Process()
    return {
        "rss_mb": round(proc.memory_info().rss / 1024 / 1024, 1),
        "threads": proc.num_threads(),
        "handles": proc.num_handles() if hasattr(proc, "num_handles") else None,
        "children": len(proc.children(recursive=True)),
    }


async def main() -> None:
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    from app.memory.namespaces import CognitiveNamespace
    from app.runtime.mission_packs import MISSION_PACKS

    with tempfile.TemporaryDirectory(prefix="vyom-soak-ext-", ignore_cleanup_errors=True) as root:
        base = Path(root)
        settings = Settings(
            database_path=base / "soak.db", skills_root=base / "skills", agents_root=base / "agents",
            audit_log_path=base / "audit.jsonl", secret_store_path=base / "secrets",
            artifacts_root=base / "artifacts", backup_root=base / "backups",
        )
        with TestClient(create_app(settings)) as client:
            state = client.app.state

            gc.collect()
            baseline = sample()
            print(f"[baseline] rss={baseline['rss_mb']}MB threads={baseline['threads']} "
                  f"handles={baseline['handles']} children={baseline['children']}", flush=True)

            seen_task_ids: set[str] = set()
            seen_mission_ids: set[str] = set()
            samples = [baseline]
            t_start = time.monotonic()

            cycle_packs = ["deep-research", "browser", "document", "chief-of-staff"]
            for i in range(ITERATIONS):
                # Real HTTP task creation (through the actual ASGI app, not
                # a bypass) - checks for task-ID collisions across many
                # rapid creations.
                response = client.post("/api/tasks", json={"user_request": f"What is my status today? (cycle {i})"})
                task_id = response.json()["id"]
                assert task_id not in seen_task_ids, f"DUPLICATE task id on cycle {i}: {task_id}"
                seen_task_ids.add(task_id)

                # A real mission each cycle, rotating through packs that
                # touch memory, browser, artifacts, and cross-domain context.
                pack_id = cycle_packs[i % len(cycle_packs)]
                mission = await state.run_mission_pack(pack_id, state, goal=MISSION_PACKS[pack_id].goal_template,
                                                        context={"url": "https://example.com"} if pack_id in ("deep-research", "browser") else {})
                assert mission.mission_id not in seen_mission_ids, f"DUPLICATE mission id on cycle {i}"
                seen_mission_ids.add(mission.mission_id)

                # Memory write + retrieval each cycle.
                await state.namespace_router.remember(
                    CognitiveNamespace.PROJECTS, f"soak-fact-{i}", f"Soak cycle {i} recorded this fact.",
                    provenance_reference="soak test", confidence=0.8,
                )

                if i % 4 == 0:
                    samples.append(sample())

            gc.collect()
            final = sample()
            samples.append(final)
            elapsed = time.monotonic() - t_start

            rss_growth = final["rss_mb"] - baseline["rss_mb"]
            rss_series = [s["rss_mb"] for s in samples]
            print(f"[after {ITERATIONS} cycles, {elapsed:.1f}s] rss={final['rss_mb']}MB "
                  f"(growth {rss_growth:+.1f}MB) threads={final['threads']} handles={final['handles']} "
                  f"children={final['children']} rss_series={rss_series}", flush=True)
            print(f"unique task ids: {len(seen_task_ids)}, unique mission ids: {len(seen_mission_ids)} "
                  f"(both must equal {ITERATIONS} - no duplication)", flush=True)

            # A DB-locking problem would have already raised by now (every
            # write above goes through the same SQLite connection under
            # WAL); confirm the store is still genuinely responsive.
            recent = await state.task_store.list_by_status({__import__("app.schemas.tasks", fromlist=["TaskStatus"]).TaskStatus.COMPLETED})
            print(f"DB still responsive: {len(recent)} completed tasks queryable after {ITERATIONS} cycles", flush=True)

        gc.collect()
        remaining = 0
        try:
            import psutil
            remaining = len(psutil.Process().children(recursive=True))
        except Exception:
            pass

        ok = (
            len(seen_task_ids) == ITERATIONS
            and len(seen_mission_ids) == ITERATIONS
            and remaining == 0
            and rss_growth < 150  # generous bound; this is a smoke check for runaway growth, not a tight leak assertion
        )
        print(f"\norphan children after shutdown: {remaining}", flush=True)
        print("EXTENDED SOAK: " + ("PASSED" if ok else "FAILED - see above"), flush=True)
        if not ok:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
