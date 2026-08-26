from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.kanban.store import KanbanCard, KanbanStatus

router = APIRouter(prefix="/api/kanban", tags=["kanban"])


@router.post("/cards", response_model=KanbanCard)
async def create_card(request: Request, payload: dict) -> KanbanCard:
    """Create a card on the default board. The dispatcher (started at
    Brain boot, see main.py) claims it automatically within one poll
    interval and runs it in a real worker subprocess - no separate
    'start' call needed."""
    store = request.app.state.kanban_store
    title = payload.get("title") or payload.get("goal", "")[:80]
    goal = payload["goal"]
    board = payload.get("board", "default")
    return await store.create(board=board, title=title, goal=goal)


@router.get("/cards")
async def list_cards(request: Request, board: str = "default", status: str | None = None, limit: int = 100) -> dict:
    store = request.app.state.kanban_store
    status_enum = KanbanStatus(status) if status else None
    cards = await store.list(board=board, status=status_enum, limit=min(max(limit, 1), 500))
    return {"count": len(cards), "cards": [c.model_dump(mode="json") for c in cards]}


@router.get("/cards/{card_id}", response_model=KanbanCard)
async def get_card(card_id: str, request: Request) -> KanbanCard:
    store = request.app.state.kanban_store
    card = await store.get(card_id)
    if card is None:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.post("/cards/{card_id}/complete")
async def complete_card(card_id: str, request: Request, payload: dict) -> dict:
    """Called by the worker subprocess (app/kanban/worker.py) when its
    submitted task completed successfully. Not intended for direct user
    calls - a worker is the one authority that knows its task's real
    outcome."""
    store = request.app.state.kanban_store
    await store.complete(card_id, result=payload)
    return {"status": "ok"}


@router.post("/cards/{card_id}/fail")
async def fail_card(card_id: str, request: Request, payload: dict) -> dict:
    store = request.app.state.kanban_store
    await store.fail(card_id, error=payload.get("error", "unknown error"))
    return {"status": "ok"}


@router.get("/status")
async def dispatcher_status(request: Request) -> dict:
    dispatcher = request.app.state.kanban_dispatcher
    return {"active_workers": dispatcher.active_worker_count(), "max_concurrent_workers": dispatcher.max_concurrent_workers}


@router.post("/messages")
async def send_message(request: Request, payload: dict) -> dict:
    """Agent-to-agent messaging between kanban workers - the
    single-Brain equivalent of Hermes's message_agent. Called by a
    worker (see app/kanban/worker.py --message-to) or directly for
    testing/manual coordination."""
    store = request.app.state.agent_message_store
    message_id = await store.send(
        from_card_id=payload["from_card_id"], to_card_id=payload["to_card_id"], content=payload["content"],
    )
    return {"message_id": message_id}


@router.get("/messages/{card_id}/inbox")
async def get_inbox(card_id: str, request: Request, mark_delivered: bool = True) -> dict:
    """Undelivered messages waiting for card_id. A worker polls this
    for messages sent by other workers."""
    store = request.app.state.agent_message_store
    messages = await store.inbox(card_id, mark_delivered=mark_delivered)
    return {"count": len(messages), "messages": messages}


@router.get("/messages/{card_id}/history")
async def get_message_history(card_id: str, request: Request, limit: int = 100) -> dict:
    store = request.app.state.agent_message_store
    messages = await store.history(card_id, limit=min(max(limit, 1), 500))
    return {"count": len(messages), "messages": messages}
