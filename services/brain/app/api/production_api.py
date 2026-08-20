from __future__ import annotations

from fastapi import APIRouter, Request

from app.production.compatibility import VersionInfo

router = APIRouter(prefix="/api/production", tags=["production"])


@router.get("/version")
async def version(request: Request) -> dict:
    channel = getattr(request.app.state, "release_channel", "alpha")
    info = VersionInfo().as_dict()
    info["channel"] = channel
    return info


@router.get("/startup-report")
async def startup_report(request: Request) -> dict:
    report = getattr(request.app.state, "startup_report", None)
    if report is None:
        return {"ok": False, "degraded": True, "ready": False, "failures": ["startup report not recorded"], "warnings": [], "steps": []}
    return {
        "ok": report.ok, "degraded": report.degraded, "ready": report.ready,
        "failures": report.failures, "warnings": report.warnings, "steps": report.steps,
    }


@router.post("/shutdown-plan")
async def shutdown_plan(request: Request) -> dict:
    """Returns the graceful-shutdown sequence. The actual exit is
    operator-initiated (service stop); the same code runs in lifespan
    teardown so shutdown is orderly either way."""
    from app.production.shutdown import GracefulShutdown

    state = request.app.state
    shutdown = GracefulShutdown(
        automation_scheduler=getattr(state, "automation_scheduler", None),
        supervisor=getattr(state, "supervisor", None),
        sync_bridge=getattr(state, "sync_bridge", None),
    )
    return {
        "ordered_steps": [
            "stop supervisor", "stop automation scheduler", "stop sync bridge",
            "checkpoint active tasks", "cancel/park remaining work",
            "close action engine", "close browser/playwright", "flush and close database",
        ],
        "timeout_seconds": 15,
    }


@router.get("/readiness")
async def readiness(request: Request) -> dict:
    return request.app.state.readiness.snapshot()
