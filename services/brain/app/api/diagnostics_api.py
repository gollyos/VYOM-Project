from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.post("/doctor")
async def run_doctor(request: Request, repair: bool = False) -> dict:
    doctor = request.app.state.doctor
    return await doctor.run(repair=repair)


@router.post("/security-audit")
async def run_security_audit(request: Request) -> dict:
    audit = request.app.state.security_audit
    return audit.run()


@router.get("/repair-recommendations")
async def repair_recommendations(request: Request) -> dict:
    doctor = request.app.state.doctor
    report = await doctor.run()
    return {"recommendations": report["recommendations"], "overall": report["overall"]}


# -- voice/command path trace -------------------------------------------
#
# The frontend posts one line per hop of a user command so the WHOLE path
# can be read back from a single file:
#
#   microphone transcript -> dispatch decision -> Brain task -> tool ->
#   verification -> spoken result
#
# Written as JSON Lines to data/logs/vyom-trace.jsonl. This exists because
# the voice half of the path lives in the webview, where nothing was
# observable from outside the running application - the reason a broken
# voice bus could look identical to a broken tool layer.

TRACE_PATH = Path("data/logs/vyom-trace.jsonl")
_TRACE_LOCK = asyncio.Lock()
_MAX_TRACE_BYTES = 5_000_000


class TraceEvent(BaseModel):
    correlation_id: str = Field(max_length=64)
    stage: str = Field(max_length=64)
    detail: dict = Field(default_factory=dict)


@router.post("/trace")
async def append_trace(event: TraceEvent) -> dict:
    """Append one hop of a user command to the trace log."""
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "correlation_id": event.correlation_id,
        "stage": event.stage,
        **{key: value for key, value in event.detail.items() if key not in {"at", "stage"}},
    }
    async with _TRACE_LOCK:
        TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Bounded: never let the trace grow without limit on a long session.
        if TRACE_PATH.exists() and TRACE_PATH.stat().st_size > _MAX_TRACE_BYTES:
            TRACE_PATH.rename(TRACE_PATH.with_suffix(".jsonl.1"))
        with TRACE_PATH.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return {"recorded": True}


@router.get("/trace")
async def read_trace(limit: int = 200) -> dict:
    """Read the most recent trace lines back, newest last."""
    if not TRACE_PATH.exists():
        return {"lines": [], "path": str(TRACE_PATH.resolve())}
    lines = TRACE_PATH.read_text(encoding="utf-8").splitlines()[-max(1, min(limit, 2000)):]
    parsed = []
    for line in lines:
        try:
            parsed.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"lines": parsed, "path": str(TRACE_PATH.resolve())}
