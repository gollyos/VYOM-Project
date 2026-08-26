"""Telegram gateway: control VYOM from the phone with a free bot token.

The Boss is a non-coder and is often away from the PC. This gateway turns
any Telegram chat into a VYOM command surface: text in -> task in the
normal Brain runtime -> verified answer back. Files (<=20 MB, Telegram's
bot limit) can be fetched with /file <path>. No paid APIs, no extra
dependencies (httpx only), and the gateway stays completely dormant
until a bot token and an explicit local-owner chat allowlist are configured.

Authorization is fail-closed: /start only activates chat ids explicitly
listed by the local owner. File delivery is separately restricted to
configured roots, so a bot chat can never read an arbitrary PC path.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from app.schemas.tasks import TaskCreate, TaskStatus

API = "https://api.telegram.org/bot{token}/{method}"
#: Telegram bots cannot upload more than this per file.
MAX_FILE_BYTES = 20 * 1024 * 1024
#: How long a gateway-created task may run before the watcher reports.
WATCH_TIMEOUT_SECONDS = 15 * 60
POLL_TIMEOUT_SECONDS = 25


class TelegramGateway:
    def __init__(
        self, token: str, runtime, task_store, state_path: Path, *,
        allowed_chat_ids: set[str] | None = None,
        allowed_file_roots: list[Path] | None = None,
    ):
        self._token = token
        self._runtime = runtime
        self._task_store = task_store
        self._state_path = state_path
        self._allowed_chat_ids = {
            str(item).strip() for item in (allowed_chat_ids or set()) if str(item).strip()
        }
        self._allowed_file_roots = tuple(
            Path(root).resolve() for root in (allowed_file_roots or []))
        self._chat_ids: set[str] = set()
        self._poll_task: asyncio.Task | None = None
        self._message_tasks: set[asyncio.Task] = set()
        self._offset = 0
        self._client: httpx.AsyncClient | None = None
        self._load_state()
        self._chat_ids.intersection_update(self._allowed_chat_ids)

    # -- state -------------------------------------------------------------

    def _load_state(self) -> None:
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            self._chat_ids = {str(item) for item in data.get("chat_ids", [])}
            self._offset = int(data.get("offset", 0))
        except (OSError, ValueError):
            pass

    def _save_state(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"chat_ids": sorted(self._chat_ids), "offset": self._offset}), encoding="utf-8")
            os.replace(tmp, self._state_path)
        except OSError:
            pass

    # -- lifecycle ---------------------------------------------------------

    async def start(self) -> None:
        if self._poll_task is not None:
            return
        if not self._allowed_chat_ids:
            raise RuntimeError("Telegram gateway requires an explicit owner chat allowlist")
        self._client = httpx.AsyncClient(timeout=POLL_TIMEOUT_SECONDS + 10)
        self._poll_task = asyncio.create_task(self._poll_loop())
        await self._post("setMyCommands", {"commands": [
            {"command": "start", "description": "Pair this chat with VYOM"},
            {"command": "file", "description": "Send a file from the PC (<=20 MB)"},
        ]})

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None
        if self._message_tasks:
            for task in tuple(self._message_tasks):
                task.cancel()
            await asyncio.gather(*self._message_tasks, return_exceptions=True)
            self._message_tasks.clear()
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # -- telegram plumbing ---------------------------------------------------

    async def _post(self, method: str, payload: dict) -> dict[str, Any]:
        assert self._client is not None
        response = await self._client.post(API.format(token=self._token, method=method), json=payload)
        return response.json()

    async def _send_text(self, chat_id: str, text: str) -> None:
        await self._post("sendMessage", {"chat_id": chat_id, "text": text[:3900]})

    def _track_command(self, chat_id: str, text: str) -> None:
        correlation_id = f"telegram:{chat_id}:{uuid4().hex}"
        task = asyncio.create_task(self._run_command(chat_id, text, correlation_id))
        self._message_tasks.add(task)

        def _finished(done: asyncio.Task) -> None:
            self._message_tasks.discard(done)
            if not done.cancelled():
                done.exception()

        task.add_done_callback(_finished)

    async def _handle_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat", {})
        chat_id = str(chat.get("id", ""))
        text = str(message.get("text") or "").strip()
        if not chat_id:
            return
        if chat.get("type") != "private":
            await self._send_text(chat_id, "VYOM remote control only accepts a private owner chat.")
            return
        if text.startswith("/start"):
            if chat_id not in self._allowed_chat_ids:
                await self._send_text(chat_id, "This Telegram chat is not authorized by the local VYOM owner.")
                return
            self._chat_ids.add(chat_id)
            self._save_state()
            await self._send_text(chat_id, "VYOM online Boss. This owner chat is authorized.")
            return
        if chat_id not in self._allowed_chat_ids or chat_id not in self._chat_ids:
            await self._send_text(chat_id, "This chat is not paired with VYOM.")
            return
        if text.startswith("/file"):
            await self._handle_file(chat_id, text[len("/file"):].strip())
            return
        if text:
            self._track_command(chat_id, text)

    async def _poll_loop(self) -> None:
        while True:
            try:
                data = await self._post("getUpdates", {
                    "offset": self._offset + 1, "timeout": POLL_TIMEOUT_SECONDS,
                    "allowed_updates": ["message"],
                })
                for update in data.get("result", []):
                    self._offset = int(update.get("update_id", self._offset))
                    message = update.get("message") or {}
                    await self._handle_message(message)
                self._save_state()
            except asyncio.CancelledError:
                raise
            except Exception:
                # Network blips must not kill the gateway; back off briefly.
                await asyncio.sleep(3)

    # -- command handling ------------------------------------------------------

    async def _run_command(self, chat_id: str, command: str, correlation_id: str | None = None) -> None:
        try:
            task = await self._runtime.create_task(TaskCreate(
                user_request=command,
                context_id=f"telegram:{chat_id}",
                source=f"telegram:{chat_id}",
                correlation_id=correlation_id or f"telegram:{chat_id}:{uuid4().hex}",
            ))
        except Exception as error:
            await self._send_text(chat_id, f"Task bana nahi paaya Boss: {error}")
            return
        await self._send_text(chat_id, f"Theek hai Boss, kaam shuru — {task.id[:12]}")
        deadline = asyncio.get_event_loop().time() + WATCH_TIMEOUT_SECONDS
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(3)
            current = await self._task_store.get(task.id)
            if current is None:
                return
            if current.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                answer = current.result.response if current.result else None
                answer = str(answer or f"Task {current.status.value}.")
                await self._send_text(chat_id, f"{answer}\n\n— VYOM ({current.status.value})")
                return
        await self._send_text(chat_id, "Kaam abhi chal raha hai Boss — me time lagega. Desktop pe progress dikh raha hai.")

    async def _handle_file(self, chat_id: str, raw_path: str) -> None:
        if not raw_path:
            await self._send_text(chat_id, "Poora path bolo Boss: /file C:\\Users\\...\\file.pdf")
            return
        try:
            path = Path(os.path.expandvars(raw_path.strip('"'))).resolve(strict=True)
        except (OSError, RuntimeError):
            await self._send_text(chat_id, "Ye file nahi mili Boss. Path check karke dobara bhejo.")
            return
        if not self._allowed_file_roots or not any(path.is_relative_to(root) for root in self._allowed_file_roots):
            await self._send_text(chat_id, "Security ke liye sirf VYOM artifact folder ki files bhej sakta hoon.")
            return
        if not path.is_file():
            await self._send_text(chat_id, "Ye file nahi mili Boss. Path check karke dobara bhejo.")
            return
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            await self._send_text(chat_id, f"File {size // (1024 * 1024)} MB hai — Telegram bot limit 20 MB hai Boss.")
            return
        assert self._client is not None
        try:
            with path.open("rb") as handle:
                response = await self._client.post(
                    API.format(token=self._token, method="sendDocument"),
                    data={"chat_id": chat_id, "caption": path.name},
                    files={"document": (path.name, handle)},
                )
            if not response.json().get("ok"):
                await self._send_text(chat_id, "Telegram ne file reject kar di Boss.")
        except OSError as error:
            await self._send_text(chat_id, f"File padhne me dikkat: {error}")
