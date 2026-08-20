from __future__ import annotations

from datetime import datetime, timezone

from .schemas import Commitment, CommitmentSource, CommitmentStatus
from .store import CommitmentStore


class CommitmentService:
    """Tracks promises regardless of where they came from (rule 25):
    explicit user statement, meeting action item, email commitment,
    client agreement, or task assignment. Every commitment keeps its
    source and evidence so "what have I promised people?" answers from
    real records, never a guess (rule 25)."""

    def __init__(self, store: CommitmentStore):
        self.store = store

    async def create(
        self, description: str, *, recipient: str | None = None, deadline: datetime | None = None,
        source: CommitmentSource = CommitmentSource.EXPLICIT_PROMISE, evidence: list[str] | None = None,
    ) -> Commitment:
        commitment = Commitment(description=description, recipient=recipient, deadline=deadline, source=source, evidence=evidence or [])
        return await self.store.save(commitment)

    async def from_meeting_action_items(self, event_id: str, action_items: list[str]) -> list[Commitment]:
        created = []
        for item in action_items:
            commitment = Commitment(
                description=item, source=CommitmentSource.MEETING_ACTION_ITEM,
                evidence=[f"meeting_event:{event_id}"],
            )
            created.append(await self.store.save(commitment))
        return created

    async def complete(self, commitment_id: str) -> Commitment:
        commitment = await self._require(commitment_id)
        commitment.status = CommitmentStatus.COMPLETED
        return await self.store.save(commitment)

    async def cancel(self, commitment_id: str) -> Commitment:
        commitment = await self._require(commitment_id)
        commitment.status = CommitmentStatus.CANCELLED
        return await self.store.save(commitment)

    async def open_commitments(self, *, now: datetime | None = None) -> list[Commitment]:
        """Refreshes overdue status against real deadlines rather than
        letting a stale `open` status hide something that's now late."""
        current_time = now or datetime.now(timezone.utc)
        items = await self.store.list(CommitmentStatus.OPEN)
        for item in items:
            if item.is_overdue(now=current_time):
                item.status = CommitmentStatus.OVERDUE
                await self.store.save(item)
        return await self.store.list(CommitmentStatus.OPEN) + await self.store.list(CommitmentStatus.OVERDUE)

    async def overdue(self, *, now: datetime | None = None) -> list[Commitment]:
        return [item for item in await self.open_commitments(now=now) if item.status == CommitmentStatus.OVERDUE]

    async def _require(self, commitment_id: str) -> Commitment:
        commitment = await self.store.get(commitment_id)
        if commitment is None:
            raise KeyError(commitment_id)
        return commitment
