from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from pathlib import Path

from .store import KanbanCard, KanbanStatus, KanbanStore

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 5
DEFAULT_MAX_CONCURRENT_WORKERS = 3  # VYOM equivalent of Hermes's per-profile worker cap


class KanbanDispatcher:
    """Claims PENDING cards and spawns one real OS subprocess per card
    (app/kanban/worker.py), mirroring Hermes's own dispatcher: worker
    lifecycle (spawn/exit/stale-claim) is tracked, and several cards
    genuinely run in parallel as separate processes bounded by
    max_concurrent_workers - not just concurrent asyncio coroutines
    inside one process."""

    def __init__(
        self,
        store: KanbanStore,
        *,
        base_url: str = "http://127.0.0.1:7788",
        board: str = "default",
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        max_concurrent_workers: int = DEFAULT_MAX_CONCURRENT_WORKERS,
        python_executable: str | None = None,
    ) -> None:
        self.store = store
        self.base_url = base_url
        self.board = board
        self.poll_seconds = max(1.0, poll_seconds)
        self.max_concurrent_workers = max(1, max_concurrent_workers)
        self.python_executable = python_executable or sys.executable
        self._worker: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._processes: dict[str, subprocess.Popen] = {}

    def start(self) -> None:
        if self._worker is None or self._worker.done():
            self._stop.clear()
            self._worker = asyncio.create_task(self._loop(), name="vyom-kanban-dispatcher")

    async def stop(self) -> None:
        self._stop.set()
        if self._worker is not None:
            try:
                await asyncio.wait_for(self._worker, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._worker.cancel()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self._reap_finished()
                await self.store.reclaim_stale(board=self.board)
                await self._dispatch_one_if_capacity()
            except Exception:
                logger.exception("Kanban dispatch tick failed; will retry next poll")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
            except asyncio.TimeoutError:
                pass

    async def _reap_finished(self) -> None:
        finished = [card_id for card_id, proc in self._processes.items() if proc.poll() is not None]
        for card_id in finished:
            self._processes.pop(card_id, None)

    async def _dispatch_one_if_capacity(self) -> KanbanCard | None:
        if len(self._processes) >= self.max_concurrent_workers:
            return None
        # Claim first (durable), THEN spawn - a spawn failure after a
        # successful claim just leaves the card CLAIMED for reclaim_stale
        # to recover, never silently drops it.
        card = await self.store.claim_next(board=self.board, worker_pid=0)
        if card is None:
            return None
        try:
            process = subprocess.Popen(
                [self.python_executable, "-m", "app.kanban.worker", card.id, card.goal, "--base-url", self.base_url],
                cwd=str(Path(__file__).resolve().parents[2]),
            )
        except Exception as error:
            await self.store.fail(card.id, error=f"Failed to spawn worker: {error}")
            return None
        self._processes[card.id] = process
        await self._record_worker_pid(card.id, process.pid)
        await self.store.mark_in_progress(card.id)
        logger.info("Dispatched kanban card %s to worker pid %s", card.id, process.pid)
        return card

    async def _record_worker_pid(self, card_id: str, pid: int) -> None:
        connection = self.store.database.require_connection()
        await connection.execute(
            "UPDATE kanban_cards SET worker_pid = ? WHERE id = ?", (pid, card_id)
        )
        await connection.commit()

    def active_worker_count(self) -> int:
        return len(self._processes)
