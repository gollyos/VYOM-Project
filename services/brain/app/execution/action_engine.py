from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

import httpx

from app.coding.coding_worker import CodingWorker
from app.schemas.results import ExecutionResult
from app.schemas.routing import UsageRecord
from app.schemas.tasks import ActionProvenance, Task, TaskProfile, TaskStatus
from app.tools.executor import ToolExecutor

from .execution_context import ExecutionContextFactory
from .process_manager import ProcessManager


TOOL_INTENTS = {
    "inspect_project", "inspect_project_build", "run_tests", "create_project_file",
    "delete_project_file", "show_changes", "open_local_app",
    # Generic capability-backed intents resolved by TaskClassifier layer 2.
    # These are what make ordinary phrasing ("list the files in my
    # project", "open Calculator", "search the web for X") execute a real
    # tool instead of being answered by a model.
    "fs_list", "fs_read", "fs_search", "app_launch", "web_browse",
    "run_command", "situation_report", "shop_compare",
    # Operating the visible desktop. These are the difference between
    # VYOM describing the PC and VYOM using it.
    "app_close", "settings_open", "screen_observe", "ui_interact",
    # Browser targets are distinct objects: app vs window vs profile vs tab.
    "browser_tab_close", "browser_tab_list", "browser_profile_open",
    "browser_tab_open", "browser_page_read", "browser_page_click",
    "browser_first_result", "browser_page_type", "browser_page_scroll", "play_media",
    "capability_query",
    # Recovering from "it didn't open" is an action, not an explanation.
    "recover_visibility",
    # Machine state read natively (psutil/platform), never through a shell.
    "system_query",
}

# Spoken/typed application names -> app_id in the Application Registry.
APP_ALIASES = {
    "calculator": "calculator", "calc": "calculator",
    "notepad": "notepad",
    "file explorer": "file_explorer", "explorer": "file_explorer",
    "chrome": "chrome", "google chrome": "chrome",
    "visual studio code": "vscode", "vs code": "vscode", "vscode": "vscode",
    "windows terminal": "terminal", "terminal": "terminal",
    "paint": "paint",
}

# Capability the intent needs, checked against the LIVE Capability
# Registry before execution. VYOM never claims inability from model
# knowledge - it reports the specific component that is unavailable.
INTENT_CAPABILITY = {
    "fs_list": "filesystem.execute", "fs_read": "filesystem.execute",
    "fs_search": "filesystem.execute", "create_project_file": "filesystem.execute",
    "delete_project_file": "filesystem.execute", "show_changes": "git.execute",
    "app_launch": "desktop.execute", "web_browse": "browser.execute",
    "app_close": "desktop.execute", "settings_open": "desktop.execute",
    "screen_observe": "desktop.execute", "ui_interact": "desktop.execute",
    "system_query": "system.execute",
    "browser_tab_close": "desktop.execute", "browser_tab_list": "desktop.execute",
    "browser_tab_open": "desktop.execute",
    "browser_page_read": "desktop.execute", "browser_page_click": "desktop.execute",
    "browser_first_result": "desktop.execute", "browser_page_type": "desktop.execute",
    "browser_page_scroll": "desktop.execute", "play_media": "desktop.execute",
    "browser_profile_open": "desktop.execute", "recover_visibility": "desktop.execute",
    "shop_compare": "browser.execute",
    "run_command": "terminal.execute", "run_tests": "terminal.execute",
    "inspect_project_build": "terminal.execute", "inspect_project": "filesystem.execute",
    "open_local_app": "browser.execute",
}


class CapabilityUnavailable(RuntimeError):
    """Raised with the exact unavailable component, never a guess."""


def generated_at() -> str:
    return datetime.now().astimezone().strftime("%H:%M · Tool runtime")


class ActionEngine:
    def __init__(
        self,
        *,
        executor: ToolExecutor,
        context_factory: ExecutionContextFactory,
        process_manager: ProcessManager,
        project_root: Path,
        capability_registry=None,
        application_registry=None,
        task_store=None,
    ):
        self.executor = executor
        self.context_factory = context_factory
        self.process_manager = process_manager
        self.project_root = project_root.resolve()
        self.coding_worker = CodingWorker(executor)
        # Live registries. Optional so existing tests that construct an
        # ActionEngine directly keep working; when present, capability
        # truth is enforced from the real registry rather than assumed.
        self.capability_registry = capability_registry
        self.application_registry = application_registry
        self.task_store = task_store

    def supports(self, intent: str) -> bool:
        return intent in TOOL_INTENTS

    def _require_capability(self, intent: str) -> None:
        """Capability truth: consult the LIVE registry before acting or
        before reporting inability. A missing registry is not treated as
        'unavailable' - it means this engine was constructed without one
        (tests), and the tool call itself remains the source of truth."""
        capability_id = INTENT_CAPABILITY.get(intent)
        if capability_id is None or self.capability_registry is None:
            return
        record = self.capability_registry.get(capability_id)
        if record is None:
            raise CapabilityUnavailable(
                f"Capability '{capability_id}' is not registered in this Brain instance."
            )
        status = getattr(record.status, "value", str(record.status))
        if status != "available":
            raise CapabilityUnavailable(
                f"Capability '{capability_id}' is registered but reports status "
                f"'{status}'. VYOM will not simulate it."
            )

    #: Intents that act on the world outside VYOM itself - launching or
    #: closing an application, opening/closing/navigating a browser
    #: profile/tab/page, running a shell command. Everything NOT in this
    #: set is read-only (fs_list, screen_observe, system_query, ...) and
    #: needs no provenance check: an idle system answering a question
    #: about its own state is not an "external effect".
    EXTERNAL_ACTION_INTENTS = frozenset({
        "app_launch", "app_close", "settings_open", "recover_visibility",
        "browser_tab_close", "browser_profile_open", "browser_tab_open",
        "browser_page_click", "browser_first_result", "browser_page_type",
        "browser_page_scroll", "play_media", "ui_interact", "web_browse", "run_command",
        "open_local_app",
    })

    def _authorize_external_action(self, task: Task, intent: str) -> None:
        """Deny an external action that has no traceable reason to run.

        Every physical-mic session where an app opened without being
        asked traces back to a task that reached this dispatcher without
        anyone checking WHY it was allowed to act. This is that check: it
        does not decide WHAT to run (routing already did that) - only
        whether this task is still entitled to act on the world at all."""
        if intent not in self.EXTERNAL_ACTION_INTENTS:
            return
        # A cancelled/failed/completed task is terminal. Nothing it still
        # has in flight may go on to open a window, a tab, or a process -
        # that is exactly how a superseded utterance kept acting after the
        # user had already moved on or said stop.
        if task.status in {TaskStatus.CANCELLED, TaskStatus.FAILED, TaskStatus.COMPLETED}:
            raise CapabilityUnavailable(
                f"Task {task.id} is already {task.status.value}; a terminal task has no "
                "authority to launch or control anything further."
            )
        provenance = (task.metadata or {}).get("provenance")
        try:
            ActionProvenance(provenance)
        except ValueError:
            raise CapabilityUnavailable(
                f"'{intent}' has no valid action provenance (got {provenance!r}); denied. "
                "Every external app/window/browser action must trace to USER_COMMAND, "
                "APPROVED_SCHEDULE, APPROVED_AUTOMATION, CURRENT_GOAL_RECOVERY or "
                "SYSTEM_SAFETY_ACTION."
            )

    #: Words that say what KIND of thing the user is talking about. A
    #: capability whose domain contradicts the goal's must not run.
    _DOMAIN_MARKERS = {
        "filesystem": ("file", "files", "folder", "directory", "path", "repo", "code"),
        "browser": ("browser", "chrome", "edge", "website", "site", "url", "tab",
                    "profile", "account", "login", "web", "online", "amazon", "youtube"),
        "desktop": ("app", "application", "window", "calculator", "notepad", "settings"),
    }

    def _reject_incompatible_capability(self, task: Task, profile: TaskProfile) -> None:
        """Refuse a capability whose semantic domain contradicts the goal.

        "Open the Goli iOS profile" was answered with "VYOM Project
        contains 38 top-level entries" - a filesystem listing, chosen
        because the words 'profile'/'project' scored well in retrieval.
        Nothing checked that the user was plainly talking about a browser
        profile, not a directory. A wrong-domain answer is worse than no
        answer, because it looks like it worked."""
        if profile.intent not in {"fs_list", "fs_read", "fs_search"}:
            return
        lowered = task.user_request.lower()
        browser_words = sum(1 for word in self._DOMAIN_MARKERS["browser"] if word in lowered)
        file_words = sum(1 for word in self._DOMAIN_MARKERS["filesystem"] if word in lowered)
        if browser_words > file_words:
            raise CapabilityUnavailable(
                "That sounds like a browser or account request, not a folder on this PC. "
                "I did not want to answer it with a directory listing, which would look "
                "like an answer without being one. Tell me which application you mean."
            )

    async def execute(self, task: Task, profile: TaskProfile, emit) -> ExecutionResult:
        context = self.context_factory.create(task.id, task.permission_level, emit)
        self._require_capability(profile.intent)
        self._reject_incompatible_capability(task, profile)
        self._authorize_external_action(task, profile.intent)
        try:
            if profile.intent == "fs_list":
                return await self._fs_list(task, context)
            if profile.intent == "fs_read":
                return await self._fs_read(task, context)
            if profile.intent == "fs_search":
                return await self._fs_search(task, context)
            if profile.intent == "app_launch":
                return await self._app_launch(task, context)
            if profile.intent == "app_close":
                return await self._app_close(task, context)
            if profile.intent == "settings_open":
                return await self._settings_open(task, context)
            if profile.intent == "screen_observe":
                return await self._screen_observe(task, context)
            if profile.intent == "system_query":
                return await self._system_query(task, context)
            if profile.intent == "recover_visibility":
                return await self._recover_visibility(task, context)
            if profile.intent == "browser_tab_close":
                return await self._browser_tab_close(task, context)
            if profile.intent == "browser_tab_list":
                return await self._browser_tab_list(task, context)
            if profile.intent == "browser_profile_open":
                return await self._browser_profile_open(task, context)
            if profile.intent == "browser_tab_open":
                return await self._browser_tab_open(task, context)
            if profile.intent == "browser_page_read":
                return await self._browser_page_read(task, context)
            if profile.intent == "browser_page_click":
                return await self._browser_page_click(task, context)
            if profile.intent == "browser_first_result":
                return await self._browser_first_result(task, context)
            if profile.intent == "browser_page_type":
                return await self._browser_page_type(task, context)
            if profile.intent == "browser_page_scroll":
                return await self._browser_page_scroll(task, context)
            if profile.intent == "play_media":
                return await self._play_media(task, context)
            if profile.intent == "capability_query":
                return await self._capability_query(task, context)
            if profile.intent == "ui_interact":
                return await self._ui_interact(task, context)
            if profile.intent == "web_browse":
                return await self._web_browse(task, context)
            if profile.intent == "run_command":
                return await self._run_command(task, context)
            if profile.intent == "situation_report":
                return await self._situation_report(task, context)
            if profile.intent == "shop_compare":
                return await self._shop_compare(task, context)
            if profile.intent == "inspect_project_build":
                data = await self.coding_worker.inspect_and_build(self.project_root, context)
                return self._build_result(data)
            if profile.intent == "inspect_project":
                workspace = await self.coding_worker.workspace_manager.inspect(self.project_root, context)
                return self._workspace_result(workspace.model_dump(mode="json"))
            if profile.intent == "run_tests":
                data = await self.coding_worker.run_discovered_tests(self.project_root, context)
                return self._test_result(data)
            if profile.intent == "create_project_file":
                relative = self._extract_filename(task.user_request) or "phase5-test-note.txt"
                data = await self.coding_worker.create_and_verify_file(
                    self.project_root,
                    relative,
                    "VYOM Phase 5 controlled filesystem verification.\n",
                    context,
                )
                return self._file_result(relative, data)
            if profile.intent == "delete_project_file":
                relative = self._extract_filename(task.user_request) or "phase5-test-note.txt"
                result = await self.executor.invoke(
                    "filesystem",
                    {"action": "delete", "path": str(self.project_root / relative), "confirmed": task.approval_granted},
                    context,
                )
                return self._simple_result("File deleted and verified.", result.model_dump(mode="json"))
            if profile.intent == "show_changes":
                # Git evidence when the project is a repository; real
                # filesystem evidence when it is not. Reporting "not a Git
                # repository" as a hard failure hid genuine, verifiable
                # change evidence that VYOM can still produce.
                try:
                    diff = await self.coding_worker.diff_analyzer.inspect(self.project_root, context)
                    if diff.success:
                        return self._diff_result(diff.model_dump(mode="json"))
                    reason = diff.error or "Git diff was unavailable"
                except Exception as error:
                    reason = str(error)
                return await self._recent_changes(context, reason)
            if profile.intent == "open_local_app":
                return await self._open_local_app(task, context)
            raise RuntimeError(f"Unsupported action intent: {profile.intent}")
        finally:
            self.context_factory.release(task.id)

    async def cancel(self, task_id: str) -> None:
        self.context_factory.cancel(task_id)
        await self.process_manager.stop_task(task_id)

    async def shutdown(self) -> None:
        await self.process_manager.cleanup()

    async def _open_local_app(self, task: Task, context) -> ExecutionResult:
        workspace = await self.coding_worker.workspace_manager.inspect(self.project_root, context)
        command = workspace.commands.get("dev")
        if not command:
            return self._simple_result("No development command was discovered.", {"workspace": workspace.model_dump(mode="json")}, passed=False)
        url = "http://localhost:1420/"
        started_process = None
        if not await self._url_ready(url):
            started_process = await self.process_manager.start(task.id, command, self.project_root)
            await context.emit("terminal_started", f"Started {command}", started_process)
            ready = await self._wait_for_url(url, context, started_process["process_id"], 32)
            snapshot = self.process_manager.snapshot(started_process["process_id"])
            if not ready and workspace.frameworks and "Vite" in workspace.frameworks:
                retry_command = "npm run dev -- --configLoader runner"
                await context.emit(
                    "tool_retry",
                    "Development server did not become ready; retrying with the Vite runner loader",
                    {"from": command, "to": retry_command, "attempt": 2, "stderr": snapshot.get("stderr", "")[-1200:]},
                )
                await self.process_manager.stop(started_process["process_id"])
                started_process = await self.process_manager.start(task.id, retry_command, self.project_root)
                await context.emit("terminal_started", f"Started {retry_command}", started_process)
                ready = await self._wait_for_url(url, context, started_process["process_id"], 60)
            if not ready:
                snapshot = self.process_manager.snapshot(started_process["process_id"])
                verification = {"passed": False, "summary": "Development server did not become reachable", "evidence": [snapshot.get("stderr", "")[-1200:] or snapshot.get("stdout", "")[-1200:] or "No process output"]}
                data = {"workspace": workspace.model_dump(mode="json"), "process": snapshot, "browser": {"success": False, "structured_output": {}, "error": verification["summary"]}, "screenshot": {"success": False, "structured_output": {}}, "verification": verification}
                return self._browser_result(data)
        screenshot = self.project_root / "services" / "brain" / "data" / "screenshots" / f"{task.id}.png"
        opened = await self.executor.invoke("browser", {"action": "open", "url": url, "expected_url": "1420"}, context)
        captured = await self.executor.invoke("screenshot", {"target": "browser", "path": str(screenshot), "full_page": True}, context)
        verification = opened.structured_output.get("verification", {})
        data = {"workspace": workspace.model_dump(mode="json"), "process": started_process, "browser": opened.model_dump(mode="json"), "screenshot": captured.model_dump(mode="json"), "verification": verification}
        return self._browser_result(data)

    async def _wait_for_url(self, url: str, context, process_id: int, attempts: int) -> bool:
        for _ in range(attempts):
            context.check_cancelled()
            if await self._url_ready(url):
                return True
            if self.process_manager.snapshot(process_id).get("status") == "exited":
                return False
            await asyncio.sleep(0.25)
        return False

    @staticmethod
    async def _url_ready(url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=0.5) as client:
                response = await client.get(url)
            return response.status_code < 500
        except httpx.HTTPError:
            return False

    @staticmethod
    def _extract_filename(request: str) -> str | None:
        match = re.search(r"(?:called|named|file)\s+[\"']?([\w.-]+\.[\w]+)", request, re.I)
        return match.group(1) if match else None

    # -- generic capability-backed actions ---------------------------------
    #
    # Each of these performs a REAL tool call through the registered tool
    # layer and returns real evidence plus a UI composition, so the
    # frontend receives an automatic visual for an ordinary spoken or
    # typed command. None of them can succeed without the underlying
    # tool actually succeeding.

    def _resolve_directory(self, request: str) -> Path:
        """Resolve the directory a filesystem request refers to. Defaults
        to the registered project root - 'my project' is not a guess, it
        is the root this Brain was configured with."""
        quoted = re.search(r"[\"']([^\"']+)[\"']", request)
        candidates: list[str] = []
        if quoted:
            candidates.append(quoted.group(1))
        drive = re.search(r"[A-Za-z]:[\\/][^\s\"']*", request)
        if drive:
            candidates.append(drive.group(0))
        for candidate in candidates:
            path = Path(candidate)
            if not path.is_absolute():
                path = self.project_root / candidate
            if path.exists():
                return path.resolve()
        lowered = request.lower()
        match = re.search(r"\b(?:in|inside|under|of)\s+(?:the\s+)?([\w.\-/\\]+)\s*(?:folder|directory|dir)\b", lowered)
        if match:
            path = (self.project_root / match.group(1)).resolve()
            if path.exists():
                return path
        return self.project_root

    async def _fs_list(self, task: Task, context) -> ExecutionResult:
        directory = self._resolve_directory(task.user_request)
        result = await self.executor.invoke(
            "filesystem", {"action": "list", "path": str(directory)}, context
        )
        if not result.success:
            raise RuntimeError(result.error or "Filesystem listing failed")
        entries = result.structured_output.get("entries", [])
        directories = [item for item in entries if item.get("kind") == "directory"]
        files = [item for item in entries if item.get("kind") == "file"]
        summary = (
            f"{directory.name} contains {len(entries)} top-level entries: "
            f"{len(directories)} folders and {len(files)} files."
        )
        rows = [
            [
                item.get("path", "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
                item.get("kind", "unknown"),
                str(item.get("size", 0)),
                str(item.get("modified", ""))[:19],
            ]
            for item in entries[:40]
        ]
        objects = [
            {
                "id": "listing", "type": "comparison-table", "title": directory.name,
                "eyebrow": "Real filesystem", "headers": ["Name", "Kind", "Bytes", "Modified"],
                "rows": rows, "frame": {"x": 3, "y": 6, "width": 40},
            },
            {
                "id": "verified", "type": "verified-result", "title": "Listing verified",
                "eyebrow": "Evidence", "tone": "verified", "statement": summary,
                "evidence": [
                    f"Path: {directory}",
                    f"Folders: {len(directories)}",
                    f"Files: {len(files)}",
                ],
                "timestamp": generated_at(), "frame": {"x": 58, "y": 58, "width": 32, "layer": 2},
            },
        ]
        return ExecutionResult(
            response=summary,
            structured_data={"path": str(directory), "entries": entries},
            ui_composition=self._base_composition(identifier="fs-listing", summary=summary, objects=objects),
            evidence=[f"Listed {len(entries)} entries under {directory}"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _fs_read(self, task: Task, context) -> ExecutionResult:
        relative = self._extract_filename(task.user_request)
        if relative is None:
            raise RuntimeError(
                "No filename was identified in the request; VYOM will not guess which file to read."
            )
        target = Path(relative)
        if not target.is_absolute():
            target = self.project_root / relative
        if not target.exists():
            matches = list(self.project_root.rglob(relative))
            if not matches:
                raise RuntimeError(f"'{relative}' does not exist under {self.project_root}")
            target = matches[0]
        result = await self.executor.invoke(
            "filesystem", {"action": "read", "path": str(target), "max_chars": 20_000}, context
        )
        if not result.success:
            raise RuntimeError(result.error or "Filesystem read failed")
        content = result.structured_output.get("content", "")
        summary = f"Read {target.name} ({len(content)} characters)."
        objects = [
            {
                "id": "content", "type": "code-diff", "title": target.name,
                "eyebrow": "File contents", "path": str(target), "diff": content[:6000],
                "frame": {"x": 12, "y": 6, "width": 60},
            },
            {
                "id": "verified", "type": "verified-result", "title": "Read verified",
                "eyebrow": "Evidence", "tone": "verified", "statement": summary,
                "evidence": [f"Path: {target}", f"Characters: {len(content)}"],
                "timestamp": generated_at(), "frame": {"x": 35, "y": 74, "width": 30, "layer": 2},
            },
        ]
        return ExecutionResult(
            response=summary, structured_data={"path": str(target), "content": content[:20_000]},
            ui_composition=self._base_composition(identifier="fs-read", summary=summary, objects=objects),
            evidence=[f"Read {target}"], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _fs_search(self, task: Task, context) -> ExecutionResult:
        pattern = self._extract_filename(task.user_request) or "*"
        if pattern == "*":
            token = re.search(r"(?:for|matching|named|called)\s+[\"']?([\w.*\-]+)", task.user_request, re.I)
            if token:
                candidate = token.group(1)
                pattern = candidate if "*" in candidate else f"*{candidate}*"
        directory = self._resolve_directory(task.user_request)
        result = await self.executor.invoke(
            "filesystem",
            {"action": "search", "path": str(directory), "pattern": pattern, "limit": 200},
            context,
        )
        if not result.success:
            raise RuntimeError(result.error or "Filesystem search failed")
        matches = result.structured_output.get("matches", [])
        summary = f"Found {len(matches)} match(es) for '{pattern}' under {directory.name}."
        objects = [
            {
                "id": "matches", "type": "comparison-table", "title": f"Matches for {pattern}",
                "eyebrow": "Real filesystem search", "headers": ["Match"],
                "rows": [[item] for item in matches[:40]],
                "frame": {"x": 3, "y": 6, "width": 44},
            },
            {
                "id": "verified", "type": "verified-result", "title": "Search verified",
                "eyebrow": "Evidence", "tone": "verified" if matches else "attention",
                "statement": summary,
                "evidence": [f"Root: {directory}", f"Pattern: {pattern}", f"Matches: {len(matches)}"],
                "timestamp": generated_at(), "frame": {"x": 58, "y": 60, "width": 32, "layer": 2},
            },
        ]
        return ExecutionResult(
            response=summary, structured_data={"pattern": pattern, "matches": matches},
            ui_composition=self._base_composition(identifier="fs-search", summary=summary, objects=objects),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _recent_changes(self, context, reason: str) -> ExecutionResult:
        """Change evidence without Git: the most recently modified files
        under the project root, read through the registered filesystem
        tool. The reason Git was unavailable is reported, never hidden."""
        result = await self.executor.invoke(
            "filesystem", {"action": "list", "path": str(self.project_root)}, context
        )
        if not result.success:
            raise RuntimeError(result.error or "Could not inspect the project root for changes")
        entries = [item for item in result.structured_output.get("entries", []) if item.get("modified")]
        entries.sort(key=lambda item: item.get("modified", ""), reverse=True)
        newest = entries[:12]
        summary = (
            f"Git diff is unavailable ({reason}). Showing the {len(newest)} most recently "
            f"modified top-level entries under {self.project_root.name} instead."
        )
        objects = [
            {
                "id": "changes", "type": "comparison-table", "title": "Most recently modified",
                "eyebrow": "Filesystem change evidence",
                "headers": ["Name", "Kind", "Modified", "Bytes"],
                "rows": [
                    [
                        item.get("path", "").rsplit("\\", 1)[-1].rsplit("/", 1)[-1],
                        item.get("kind", ""),
                        str(item.get("modified", ""))[:19],
                        str(item.get("size", 0)),
                    ]
                    for item in newest
                ],
                "frame": {"x": 6, "y": 6, "width": 46},
            },
            {
                "id": "verified", "type": "verified-result", "title": "Change evidence",
                "eyebrow": "Evidence", "tone": "attention", "statement": summary,
                "evidence": [f"Git: {reason}", f"Root: {self.project_root}", f"Entries inspected: {len(entries)}"],
                "timestamp": generated_at(), "frame": {"x": 56, "y": 60, "width": 34, "layer": 2},
            },
        ]
        return ExecutionResult(
            response=summary,
            structured_data={"git_unavailable": reason, "recent": newest},
            ui_composition=self._base_composition(identifier="recent-changes", summary=summary, objects=objects),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    def _resolve_app_id(self, request: str) -> str | None:
        """One application-resolution point for the whole runtime.

        The Application Registry owns the alias table; this falls back to
        the local map only when an ActionEngine was built without a
        registry (tests), so there is never a second, drifting list of
        what "chrome" means."""
        if self.application_registry is not None:
            resolved = self.application_registry.resolve(request)
            if resolved:
                return resolved
        lowered = request.lower()
        for phrase in sorted(APP_ALIASES, key=len, reverse=True):
            if re.search(rf"\b{re.escape(phrase)}\b", lowered):
                return APP_ALIASES[phrase]
        return None

    @staticmethod
    def _named_application(request: str) -> str | None:
        """The program name the user actually said, for an honest reply."""
        verbs = {"open", "launch", "start", "run", "kholo", "khol", "chalu",
                 "chala", "de", "do", "karo", "bro", "please", "vyom"}
        for word in re.findall(r"[\w.-]+", request):
            if word.lower() not in verbs and len(word) >= 3 and not word.isdigit():
                return word
        return None

    def _extract_launch_target(
        self, request: str, app_id: str, *, referent: str | None = None
    ) -> str | None:
        """Resolve the destination named in a launch request.

        Only ever returns something the request actually named: an
        explicit URL, a real directory, the user's own project - or, when
        the request names nothing because it used a PRONOUN, the thing
        that pronoun points at in the active context.

        `referent` is that resolved pronoun. "to open kijiye usko", said
        straight after discussing a site, named no target at all, so this
        returned None and the planner fell back to an unrelated URL it
        found in durable memory. It never invents a target; the referent
        is supplied by ActiveContext from what actually just happened."""
        url = re.search(r"https?://\S+", request)
        if url:
            return url.group(0)
        if app_id in {"file_explorer", "vscode"}:
            lowered = request.lower()
            if "vyom project" in lowered or "this project" in lowered or "project" in lowered:
                return str(self.project_root)
            path = re.search(r"([A-Za-z]:\\[^\s\"']+)", request)
            if path and Path(path.group(1)).exists():
                return path.group(1)
        if app_id in {"chrome", "edge"}:
            site = re.search(r"\b((?:[\w-]+\.)+(?:com|org|net|io|dev|space|in|co|ai))\b", request, re.I)
            if site:
                return f"https://{site.group(1)}"
        # The request named nothing of its own - fall back to what the
        # pronoun in it points at, if anything.
        if referent:
            if str(referent).startswith(("http://", "https://")):
                return str(referent)
            site = re.search(
                r"\b((?:[\w-]+\.)+(?:com|org|net|io|dev|space|in|co|ai))\b", str(referent), re.I)
            if site and app_id in {"chrome", "edge"}:
                return f"https://{site.group(1)}"
        return None

    # -- desktop operation (deterministic, zero model) ---------------------

    async def _app_close(self, task: Task, context) -> ExecutionResult:
        """Close the application the user can SEE, and prove it closed."""
        app_id = self._resolve_app_id(task.user_request)
        if app_id is None:
            # "Close the app" with no name means the one in front of the
            # user. Resolving it from the FOREGROUND window is the honest
            # reading; the previous behaviour sent this to a general
            # planner, which answered by launching three applications.
            app_id = await self._active_window_app_id(context)
        if app_id is None:
            raise RuntimeError(
                "No application was named and no foreground window could be identified, "
                "so VYOM does not know what to close."
            )
        status = await self.executor.invoke(
            "desktop", {"action": "app_status", "app_id": app_id}, context)
        if not status.structured_output.get("running"):
            summary = f"{app_id.replace('_', ' ').title()} is not running, so there was nothing to close."
            return ExecutionResult(
                response=summary, structured_data={"app_id": app_id, "closed": False, "was_running": False},
                ui_composition=self._base_composition(
                    identifier="app-close", summary=summary,
                    objects=[{
                        "id": "verified", "type": "verified-result", "title": "Nothing to close",
                        "eyebrow": "Desktop", "tone": "attention", "statement": summary,
                        "evidence": [f"app_id: {app_id}", "no matching process in the process table"],
                        "timestamp": generated_at(), "frame": {"x": 30, "y": 30, "width": 34},
                    }]),
                evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
            )
        result = await self.executor.invoke(
            "desktop", {"action": "app_close", "app_id": app_id, "force": False}, context)
        if not result.success:
            raise RuntimeError(result.error or f"Closing {app_id} failed")
        # POSTCONDITION: the process table, not the tool's own word.
        still_running = bool(result.structured_output.get("running"))
        summary = (
            f"{app_id.replace('_', ' ').title()} is closed."
            if not still_running
            else f"{app_id.replace('_', ' ').title()} was asked to close but is still running."
        )
        if still_running:
            raise RuntimeError(summary)
        return ExecutionResult(
            response=summary, structured_data={"app_id": app_id, "closed": True},
            ui_composition=self._base_composition(
                identifier="app-close", summary=summary,
                objects=[{
                    "id": "verified", "type": "verified-result", "title": "Application closed",
                    "eyebrow": "Verified against the process table", "tone": "verified",
                    "statement": summary,
                    "evidence": [f"app_id: {app_id}", "no matching process remains"],
                    "timestamp": generated_at(), "frame": {"x": 30, "y": 30, "width": 34},
                }]),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _active_window_app_id(self, context) -> str | None:
        """Which registered application owns the foreground window."""
        observed = await self.executor.invoke("desktop", {"action": "active_window"}, context)
        window = (observed.structured_output or {}).get("window") or {}
        title = str(window.get("title") or "")
        if not title or self.application_registry is None:
            return None
        # VYOM must never be asked to close itself out from under the user.
        if "vyom" in title.lower():
            return None
        for record in self.application_registry.list():
            if record.window_title and record.window_title.lower() in title.lower():
                return record.app_id
        return self.application_registry.resolve(title)

    async def _recover_visibility(self, task: Task, context) -> ExecutionResult:
        """The user says the last thing did not appear. FIX IT.

        Observe the target -> restore and focus it -> verify it is now on
        screen. Listing the open windows would only describe the problem
        back to the user, which is what VYOM did when they said
        "ओपन नहीं हुआ। मेरे को नहीं शो हो रहा।"."""
        # What were we last asked to open? Prefer an app the user named in
        # THIS sentence, else the most recent launch this session.
        app_id = self._resolve_app_id(task.user_request) or await self._last_launched_app()
        if app_id is None:
            observed = await self.executor.invoke("desktop", {"action": "active_window"}, context)
            front = ((observed.structured_output or {}).get("window") or {}).get("title", "")
            raise RuntimeError(
                "I am not sure which window you mean. In front of you right now is "
                f"'{front}'. Name the application and I will bring it forward."
            )

        status = await self.executor.invoke(
            "desktop", {"action": "app_status", "app_id": app_id}, context)
        running = bool((status.structured_output or {}).get("running"))
        actions: list[str] = []

        if not running:
            # It genuinely never started. Recovery is to start it.
            actions.append("it was not running, so I started it")
            await self.executor.invoke(
                "desktop", {"action": "app_open", "app_id": app_id}, context)
        else:
            actions.append("it was running but behind another window")

        # Restore + focus, then CHECK the window is really visible.
        await self.executor.invoke("desktop", {"action": "app_focus", "app_id": app_id}, context)
        actions.append("I restored it and brought it to the front")

        name = app_id.replace("_", " ").title()
        window = await self._await_window(
            (self.application_registry.get(app_id).window_title
             if self.application_registry and self.application_registry.get(app_id) else app_id),
            timeout=8.0)
        if not window:
            raise RuntimeError(
                f"I could not get {name} on screen: no visible window appeared even after "
                f"restoring and focusing it."
            )
        summary = f"{name} is in front of you now — {'; '.join(actions)}."
        return ExecutionResult(
            response=summary,
            structured_data={"app_id": app_id, "window": window, "recovery": actions},
            ui_composition=self._base_composition(
                identifier="recover-visibility", summary=summary,
                objects=[{
                    "id": "verified", "type": "verified-result", "title": "Brought to front",
                    "eyebrow": "Recovery", "tone": "verified", "statement": summary,
                    "evidence": [*actions, f"visible window: {window}"],
                    "timestamp": generated_at(), "frame": {"x": 28, "y": 28, "width": 40},
                }]),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _last_launched_app(self) -> str | None:
        """The app_id of the most recent launch, for "it didn't open"."""
        if self.task_store is None:
            return None
        try:
            from app.schemas.tasks import TaskStatus

            recent = await self.task_store.list_by_status({TaskStatus.COMPLETED})
        except Exception:
            return None
        for task in sorted(recent, key=lambda item: item.completed_at or item.created_at,
                           reverse=True)[:8]:
            data = (task.result.structured_data if task.result else None) or {}
            if data.get("app_id"):
                return str(data["app_id"])
        return None

    # -- browser targets: tab / profile ------------------------------------

    #: Services a user can name explicitly. If one of these appears in the
    #: request, the answer has to come from THAT service.
    _NAMED_SERVICES = (
        "amazon", "flipkart", "myntra", "ajio", "meesho", "gmail", "youtube",
        "google", "bing", "linkedin", "instagram", "facebook", "twitter",
        "github", "stackoverflow", "reddit", "netflix", "swiggy", "zomato",
    )

    @classmethod
    def _requested_services(cls, request: str) -> list[str]:
        """Services the user named by hand, which the result must honour."""
        lowered = request.lower()
        return [service for service in cls._NAMED_SERVICES if service in lowered]

    @staticmethod
    def _named_page(request: str) -> str | None:
        """Which page the user named, in their own words."""
        from app.runtime.task_classifier import _WEB_PAGES

        lowered = request.lower()
        for page in sorted(_WEB_PAGES, key=len, reverse=True):
            if page in lowered:
                return page
        match = re.search(r"\b(\w[\w.-]{2,30})\s+(?:tab|page)\b", request, re.I)
        return match.group(1) if match else None

    async def _browser_tab_close(self, task: Task, context) -> ExecutionResult:
        """Close ONE tab. The browser and every other tab must survive."""
        page = self._named_page(task.user_request)
        if page is None:
            raise RuntimeError(
                "I could not tell which page you meant. Name the tab, for example "
                "'close the YouTube tab'."
            )
        result = await self.executor.invoke(
            "desktop", {"action": "browser_close_tab", "target": page}, context)
        data = result.structured_output or {}
        if not data.get("success"):
            raise RuntimeError(data.get("summary") or f"The '{page}' tab could not be closed")
        # POSTCONDITION, both halves: the named tab is gone AND the rest of
        # the browser is intact. Closing Chrome would also make the tab
        # disappear, and that is not what was asked.
        if not data.get("browser_still_running"):
            raise RuntimeError(
                f"The '{page}' tab closed but so did the browser; that was not what you asked for.")
        summary = data.get("summary", f"Closed the {page} tab.")
        return ExecutionResult(
            response=summary,
            structured_data={"page": page, "closed": True, **data},
            ui_composition=self._base_composition(
                identifier="tab-close", summary=summary,
                objects=[{
                    "id": "verified", "type": "verified-result", "title": "Tab closed",
                    "eyebrow": "Browser left running", "tone": "verified", "statement": summary,
                    "evidence": [f"tabs before: {data.get('tabs_before')}",
                                 f"tabs after: {data.get('tabs_after')}",
                                 "browser window still open"],
                    "timestamp": generated_at(), "frame": {"x": 28, "y": 28, "width": 40},
                }]),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _browser_tab_list(self, task: Task, context) -> ExecutionResult:
        result = await self.executor.invoke("desktop", {"action": "browser_tabs"}, context)
        tabs = (result.structured_output or {}).get("tabs", [])
        if not tabs:
            raise RuntimeError("No browser window with open tabs is visible right now.")
        summary = f"{len(tabs)} tab(s) open: " + ", ".join(tab["title"][:40] for tab in tabs[:6])
        return ExecutionResult(
            response=summary, structured_data={"tabs": tabs},
            ui_composition=self._base_composition(
                identifier="tab-list", summary=summary,
                objects=[{"id": "tabs", "type": "comparison-table", "title": "Open tabs",
                          "eyebrow": "Live browser state", "headers": ["Tab", "Window"],
                          "rows": [[tab["title"][:60], tab["window"][:40]] for tab in tabs[:10]],
                          "frame": {"x": 6, "y": 8, "width": 58}}]),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _browser_profile_open(self, task: Task, context) -> ExecutionResult:
        """Open a named signed-in browser profile, or state the exact limit."""
        url = self._extract_launch_target(
            task.user_request, "chrome",
            referent=(task.metadata.get("cognitive") or {}).get("resolved_reference"))
        result = await self.executor.invoke(
            "desktop",
            {"action": "browser_open_profile", "profile": task.user_request, "url": url},
            context)
        data = result.structured_output or {}
        profile = data.get("profile") or {}
        window = await self._await_window("Chrome", timeout=12.0)
        if not window:
            raise RuntimeError(
                f"The '{profile.get('name')}' profile was launched but no Chrome window appeared.")
        summary = (f"Chrome is open in the {profile.get('name')} profile "
                   f"({profile.get('account')}).")
        return ExecutionResult(
            response=summary,
            structured_data={"profile": profile, "window": window, "url": url},
            ui_composition=self._base_composition(
                identifier="browser-profile", summary=summary,
                objects=[{
                    "id": "verified", "type": "verified-result", "title": "Profile opened",
                    "eyebrow": "Signed-in identity", "tone": "verified", "statement": summary,
                    "evidence": [f"profile directory: {profile.get('directory')}",
                                 f"account: {profile.get('account')}", f"window: {window}"],
                    "timestamp": generated_at(), "frame": {"x": 28, "y": 28, "width": 40},
                }]),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _browser_tab_open(self, task: Task, context) -> ExecutionResult:
        """Open a NEW TAB in the browser the user is already using.

        The physical session's "उसमें न्यू टैब ओपन करो और YouTube सर्च करो" was
        routed to a generic application launch, so every request opened a
        NEW Chrome window instead of a tab in the window in front of the
        user. A tab request goes to the tab capability, which targets the
        EXISTING window through the accessibility layer."""
        # What page the new tab should show: an explicit URL, a named
        # site, or - when the user asked to search - a results URL so the
        # tab lands on the search, not a blank omnibox.
        request = task.user_request
        url = None
        url_match = re.search(r"https?://\S+|www\.\S+", request)
        if url_match:
            url = url_match.group(0)
        else:
            search = re.search(
                r"(?:search|सर्च|khojo|खोज)\s*(?:karo|करो|kar do)?\s*(?:for|pe|par|pe)?\s*"
                r"([A-Za-z0-9\u0900-\u097F .\-]{2,60})",
                request, re.I)
            if search:
                query = search.group(1).strip(" .,!?।")
                query = re.sub(r"\b(karo|kar do|kijiye|करो|please)\b\s*$", "", query,
                               flags=re.I).strip(" .,!?।")
                site = "youtube" if "youtube" in request.lower() else "google"
                if site == "youtube" and query:
                    from urllib.parse import quote
                    url = f"https://www.youtube.com/results?search_query={quote(query)}"
                elif query:
                    from urllib.parse import quote
                    url = f"https://www.google.com/search?q={quote(query)}"
        if not url:
            url = self._extract_launch_target(
                request, "chrome",
                referent=(task.metadata.get("cognitive") or {}).get("resolved_reference"))
        if not url:
            # Fall back to the site the user named with the tab.
            lowered = request.lower()
            for site in ("youtube", "gmail", "google", "github", "whatsapp",
                         "linkedin", "instagram", "facebook", "netflix", "maps"):
                if site in lowered:
                    url = site
                    break
        if not url:
            raise RuntimeError("No page was named for the new tab.")

        result = await self.executor.invoke(
            "desktop", {"action": "browser_open_tab", "url": str(url)}, context)
        if not result.success:
            raise RuntimeError(result.error or "The new tab could not be opened")
        data = result.structured_output or {}

        # SAME-CONTEXT POSTCONDITION: the browser that was already in use
        # is still the one in use, one more tab exists, and no unrelated
        # window was created. The GoalVerifier's new_tab check enforces
        # this from the structured data below.
        opened_new_window = bool(data.get("launched_new_window"))
        tabs_before = data.get("tabs_before")
        tabs_after = data.get("tabs_after")
        windows_before = data.get("windows_before")
        windows_after = data.get("windows_after")
        if (isinstance(windows_before, int) and windows_before > 0
                and isinstance(windows_after, int) and windows_after > windows_before):
            raise RuntimeError(
                "A new Chrome window was created instead of a new tab in the "
                "browser you were using, so this was not marked done.")

        target = str(data.get("url") or url)
        tidy = re.sub(r"^https?://(www\.)?", "", target).split("?")[0].rstrip("/")
        summary = (f"{tidy} is open in a new tab."
                   if not opened_new_window else
                   f"No browser window was open, so Chrome opened with {tidy} in it.")
        return ExecutionResult(
            response=summary,
            structured_data={
                "url": target,
                "tabs_before": tabs_before, "tabs_after": tabs_after,
                "windows_before": windows_before, "windows_after": windows_after,
                "launched_new_window": opened_new_window,
                "tab_title": data.get("active_tab_title") or "",
                "query": (url.split("search_query=")[-1].split("&")[0]
                          if "search_query=" in str(target) else None),
            },
            ui_composition=self._base_composition(
                identifier="browser-tab", summary=summary,
                objects=[{
                    "id": "verified", "type": "verified-result", "title": "New tab opened",
                    "eyebrow": "Existing browser window", "tone": "verified",
                    "statement": summary,
                    "evidence": [f"tabs: {tabs_before} -> {tabs_after}",
                                 f"browser windows: {windows_before} -> {windows_after}",
                                 f"opened in the window already in use"],
                    "timestamp": generated_at(), "frame": {"x": 28, "y": 28, "width": 40},
                }]),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    # -- page-level operation of the visible browser (Gate B) -----------
    #
    # Every handler drives the page the user can SEE through Windows UI
    # Automation - elements found by NAME, like a human finds them - and
    # every result carries the observed window title before/after so the
    # goal verifier reads what actually changed.

    def _page_result(self, task: Task, summary: str, data: dict, *, tone: str = "verified",
                      evidence: list[str] | None = None) -> ExecutionResult:
        return ExecutionResult(
            response=summary,
            structured_data=data,
            ui_composition=self._base_composition(
                identifier="browser-page", summary=summary,
                objects=[{
                    "id": "verified", "type": "verified-result", "title": "Page operation",
                    "eyebrow": "Windows UI Automation · visible page", "tone": tone,
                    "statement": summary,
                    "evidence": evidence or [summary[:160]],
                    "timestamp": generated_at(), "frame": {"x": 28, "y": 26, "width": 40},
                }]),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _browser_page_read(self, task: Task, context) -> ExecutionResult:
        """What is on the page right now - a real reading, not a guess."""
        result = await self.executor.invoke("desktop", {"action": "browser_page_read"}, context)
        if not result.success:
            raise RuntimeError(result.error or "The page could not be read")
        data = result.structured_output or {}
        links = data.get("links") or []
        if not links:
            raise RuntimeError(
                "No page content could be read from the visible browser. If the "
                "page is still loading, say it again in a moment.")
        summary = (f"This page shows: {links[0][:80]}"
                   + (f" and {len(links) - 1} more item(s)." if len(links) > 1 else "."))
        return self._page_result(task, summary, {
            "title": data.get("title"), "links": links, "observed": len(links),
        }, evidence=[f"page title: {(data.get('title') or '')[:80]}",
                     f"{len(links)} named element(s) read via UI Automation"])

    async def _browser_page_click(self, task: Task, context) -> ExecutionResult:
        target = self._extract_control_target(task.user_request)
        if not target:
            # "click <name>" with the bare name, no 'button' suffix.
            match = re.search(r"(?:click|dabao|daba)\s+(?:on\s+|the\s+|pe\s+|par\s+)?[\"']?([\w \-']{2,50})", 
                              task.user_request, re.I)
            target = match.group(1).strip() if match else None
        if not target:
            raise RuntimeError("Nothing was named to click.")
        result = await self.executor.invoke(
            "desktop", {"action": "browser_page_click", "target": target}, context)
        data = result.structured_output or {}
        if not data.get("success"):
            raise RuntimeError(data.get("summary") or f"Nothing called '{target}' could be clicked")
        summary = data.get("summary") or f"Clicked '{target}'."
        return self._page_result(task, summary, data)

    async def _browser_first_result(self, task: Task, context) -> ExecutionResult:
        result = await self.executor.invoke("desktop", {"action": "browser_first_result"}, context)
        data = result.structured_output or {}
        if not data.get("success"):
            raise RuntimeError(data.get("summary") or "No result was visible to open")
        summary = data.get("summary") or "Opened the first result."
        return self._page_result(task, summary, data)

    @staticmethod
    def _extract_media_query(request: str) -> str:
        """Keep the user's media description while removing command filler."""
        raw = (request or "").strip(" .,!?:;।")
        clauses = [
            clause.strip() for clause in re.split(r"[।.!?]+", raw)
            if clause.strip()
        ]
        media_marker = re.compile(
            r"(?:song|music|gaana|gana|सॉन्ग|सॉंग|गाना|म्यूजिक|बॉलीवुड|bollywood)",
            re.I,
        )
        media_clauses = [clause for clause in clauses if media_marker.search(clause)]
        # Long voice transcripts often start with a complaint/question and
        # put the actual imperative in the final clause. Searching the whole
        # transcript produces irrelevant results, so retain the last clause
        # that actually names media.
        query = (media_clauses[-1] if media_clauses else raw).strip(" .,!?:;।")
        patterns = (
            r"^(?:ek\s+kaam\s+karo|एक\s+काम\s+करो)\s*",
            r"(?:\b(?:mere\s+liye|for\s+me)\b|मेरे\s+(?:लिए|को))",
            r"(?:डायरेक्ट|direct)",
            r"(?:सॉन्ग|सॉंग|गाना)\s*(?:बजाना|चलाना)(?:\s+है)?(?:\s+तो\s+मैं)?",
            r"(?:तो\s+मैं)",
            r"\b(?:please|plz|zara|jara)\b",
            r"\b(?:play|start|chalao|chala\s*do|bajao|baja\s*do|laga\s*do)"
            r"(?:\s+kar\s*do|\s+karo)?\b",
            r"(?:चलाओ|चला\s*द(?:ो|ूं)|बजाओ|बजा\s*दो|बजाना(?:\s+है)?|लगा\s*दो)",
            r"\b(?:kar\s*do|karo)\b\s*$",
            r"(?:तो\s+मैं)?\s*$",
        )
        for pattern in patterns:
            query = re.sub(pattern, " ", query, flags=re.I)
        query = re.sub(r"\s+", " ", query).strip(" .,!?:;।")
        return query or "Bollywood song"

    async def _play_media(self, task: Task, context) -> ExecutionResult:
        """Search, start and verify media in the real visible browser.

        The successful return path requires an accessibility observation
        that Chrome marks a tab as producing audio or that the page exposes
        a Pause control. Navigation or a changed title alone never passes.
        """
        query = self._extract_media_query(task.user_request)
        search_url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        observations: list[dict[str, Any]] = []

        before_result = await self.executor.invoke(
            "desktop", {"action": "browser_media_state"}, context)
        before = before_result.structured_output or {}
        observations.append({
            "call": "browser_media_state", "inputs": {"phase": "before"},
            "ok": before_result.success, "output": before,
            "error": before_result.error,
        })

        # A media request does not require "the same tab" semantics. On
        # machines where Chrome does not expose its tab strip, Ctrl+T can
        # be swallowed while leaving the user on the previous page. The
        # registered application launcher can hand Chrome a URL directly;
        # Chrome then opens it visibly in its existing session (or starts
        # a window when none exists).
        opened_result = await self.executor.invoke(
            "desktop", {"action": "app_open", "app_id": "chrome", "url": search_url},
            context)
        opened = opened_result.structured_output or {}
        observations.append({
            "call": "desktop_launch",
            "inputs": {"app_id": "chrome", "url": search_url},
            "ok": opened_result.success, "output": opened,
            "error": opened_result.error,
        })
        if not opened_result.success:
            raise RuntimeError(opened_result.error or "YouTube search could not be opened")

        navigated_result = await self.executor.invoke(
            "desktop", {
                "action": "browser_page_type", "field": "address",
                "value": search_url, "enter": True,
            }, context)
        navigated = navigated_result.structured_output or {}
        observations.append({
            "call": "browser_page_type",
            "inputs": {"field": "address", "value": search_url, "url": search_url},
            "ok": navigated_result.success and bool(navigated.get("success")),
            "output": navigated, "error": navigated_result.error,
        })
        if not navigated_result.success or not navigated.get("success"):
            raise RuntimeError(
                navigated.get("summary") or navigated_result.error
                or "The visible browser could not navigate to the YouTube search")

        clicked_result = await self.executor.invoke(
            "desktop", {"action": "browser_first_result"}, context)
        clicked = clicked_result.structured_output or {}
        observations.append({
            "call": "browser_first_result", "inputs": {},
            "ok": clicked_result.success and bool(clicked.get("success")),
            "output": clicked, "error": clicked_result.error,
        })
        if not clicked_result.success or not clicked.get("success"):
            raise RuntimeError(
                clicked.get("summary") or clicked_result.error
                or "No playable YouTube result was visible")

        after: dict[str, Any] = {}
        for _ in range(4):
            await asyncio.sleep(0.8)
            state_result = await self.executor.invoke(
                "desktop", {"action": "browser_media_state"}, context)
            after = state_result.structured_output or {}
            observations.append({
                "call": "browser_media_state", "inputs": {"phase": "after"},
                "ok": state_result.success, "output": after,
                "error": state_result.error,
            })
            if after.get("playing") is True:
                break

        # If autoplay was blocked but the real page exposes a Play button,
        # make one bounded recovery click and observe the state again.
        if after.get("playing") is False and after.get("source") == "page-play-control":
            recovery = await self.executor.invoke(
                "desktop", {"action": "browser_page_click", "target": "Play"}, context)
            recovery_data = recovery.structured_output or {}
            observations.append({
                "call": "browser_page_click", "inputs": {"target": "Play"},
                "ok": recovery.success and bool(recovery_data.get("success")),
                "output": recovery_data, "error": recovery.error,
            })
            await asyncio.sleep(1.0)
            state_result = await self.executor.invoke(
                "desktop", {"action": "browser_media_state"}, context)
            after = state_result.structured_output or {}
            observations.append({
                "call": "browser_media_state", "inputs": {"phase": "recovery"},
                "ok": state_result.success, "output": after,
                "error": state_result.error,
            })

        before_titles = set(before.get("playing_tabs") or [])
        after_titles = set(after.get("playing_tabs") or [])
        new_playback = bool(after_titles - before_titles)
        clicked_title = str(clicked.get("title_after") or "").lower()
        playback_title = str(after.get("title") or "").lower()
        for suffix in (" - google chrome", " - audio playing"):
            clicked_title = clicked_title.split(suffix)[0]
            playback_title = playback_title.split(suffix)[0]
        clicked_matches_playback = bool(
            clicked_title and playback_title
            and (clicked_title in playback_title or playback_title in clicked_title)
        )
        if after.get("playing") is not True:
            raise RuntimeError(
                "YouTube opened a result, but Chrome did not expose any playback evidence. "
                "The task was not marked complete because opening a page is not playing a song.")
        if before.get("playing") is True and not new_playback and not clicked_matches_playback:
            raise RuntimeError(
                "Audio was already playing in another browser tab, but the requested song "
                "did not produce new playback evidence, so this was not marked complete.")

        title = str(after.get("title") or clicked.get("title_after") or query).strip()
        summary = f"Playing '{title[:100]}' in your visible browser."
        data = {
            "playing": True, "title": title, "query": query,
            "search_url": search_url, "source": after.get("source"),
            "playing_tabs": list(after_titles), "observations": observations,
        }
        return self._page_result(
            task, summary, data,
            evidence=[
                str(clicked.get("summary") or "Opened a YouTube result"),
                f"playback evidence: {after.get('source')}",
                f"playing title: {title[:100]}",
            ],
        )

    async def _capability_query(self, task: Task, context) -> ExecutionResult:
        """Answer self-capability questions from the live registry only."""
        records = self.capability_registry.list() if self.capability_registry is not None else []
        available = [
            record for record in records
            if getattr(getattr(record, "status", None), "value", str(getattr(record, "status", "")))
            == "available"
        ]
        ids = {str(getattr(record, "capability_id", "")) for record in available}
        lowered = task.user_request.lower()
        asks_memory = "memory" in lowered or "मेमोरी" in lowered or "yaad" in lowered
        memory_available = "memory.search" in ids
        if asks_memory:
            if memory_available:
                summary = (
                    "Yes. Persistent memory search is registered and available. I can retrieve "
                    "facts and history that were actually saved, and I will show retrieval "
                    "evidence instead of pretending I remember something that is not stored.")
            else:
                summary = (
                    "Persistent memory search is not available in the running Brain right now, "
                    "so I will not claim that I can recall stored history.")
        else:
            friendly: list[str] = []
            groups = (
                ("desktop.execute", "operate visible Windows apps and controls"),
                ("browser.execute", "browse and operate web pages"),
                ("filesystem.execute", "read and manage permitted files/projects"),
                ("system.execute", "measure this PC's live state"),
                ("memory.search", "retrieve persistent memory and history"),
                ("terminal.execute", "run approved development commands"),
            )
            for capability_id, label in groups:
                if capability_id in ids:
                    friendly.append(label)
            joined = "; ".join(friendly) if friendly else "no core operating capability is available"
            summary = (
                f"The running Brain has {len(available)} available registered capabilities. "
                f"Right now I can {joined}. For a specific command I check the live registry "
                "and real postconditions before saying it worked.")
        return ExecutionResult(
            response=summary,
            structured_data={
                "available_count": len(available),
                "capabilities": sorted(item for item in ids if item),
                "memory_available": memory_available,
            },
            evidence=[f"{len(available)} available capabilities read from the live registry"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _browser_page_type(self, task: Task, context) -> ExecutionResult:
        value = self._extract_typed_value(task.user_request)
        if not value:
            # Two spoken orders: "type X" (verb first) and "X likho"
            # (value first - the natural Hindi order). "Search box me
            # sonu nigam songs likho." carries the value BEFORE likho.
            match = re.search(
                r"(?:likho|likh do|type|type karo|टाइप करो|लिखो)\s+[\"']?([^\"']{1,80}?)[\"']?\s*(?:$|\bme\b|\bmein\b|\bin\b|\bpe\b|\bpar\b|\benter\b)",
                task.user_request, re.I)
            if match:
                # "type X karo" leaves the verb suffix inside the capture.
                value = re.sub(r"\s*(?:karo|kar do|kijiye|करो)\s*$", "",
                               match.group(1).strip(), flags=re.I).strip()
            if not value:
                match = re.search(
                    r"[\"']?([\w \-']{2,80}?)[\"']?\s+(?:likho|likh do|type karo|लिखो|टाइप करो)\s*[.!?।]?\s*$",
                    task.user_request, re.I)
            if match:
                value = match.group(1).strip()
                # The value is everything AFTER the last locative:
                # "Search box me sonu nigam songs" types "sonu nigam
                # songs", while "search python tutorial likho" (no
                # locative) keeps its own first word.
                parts = re.split(r"\s+(?:me|mein|pe|par|in|on|में|पे|पर)\s+", value)
                if len(parts) > 1:
                    value = parts[-1].strip()
        if not value:
            raise RuntimeError("Nothing was named to type.")
        press_enter = not re.search(r"\bwithout enter\b|enter nahi", task.user_request, re.I)
        result = await self.executor.invoke(
            "desktop", {"action": "browser_page_type", "value": value, "enter": press_enter},
            context)
        data = result.structured_output or {}
        if not data.get("success"):
            raise RuntimeError(data.get("summary") or f"'{value}' could not be typed")
        summary = data.get("summary") or f"Typed '{value}'."
        # The readback of the field is the honest evidence for typing,
        # and where Enter performed a search, the resulting page title
        # is the visit evidence the search postcondition reads.
        data = {**data, "expected": value, "display": data.get("value") or value,
                "visited": [str(data.get("title_after") or ""), str(data.get("value") or "")]}
        return self._page_result(task, summary, data)

    async def _browser_page_scroll(self, task: Task, context) -> ExecutionResult:
        lowered = task.user_request.lower()
        direction = "up" if ("up" in lowered or "upar" in lowered or "ऊपर" in lowered) else "down"
        times = 3
        match = re.search(r"(\d+)\s*(?:bar|times|baar)", lowered)
        if match:
            times = max(1, min(int(match.group(1)), 10))
        result = await self.executor.invoke(
            "desktop", {"action": "browser_page_scroll",
                        "direction": direction, "times": times}, context)
        data = result.structured_output or {}
        if not data.get("success"):
            raise RuntimeError(data.get("summary") or "The page could not be scrolled")
        summary = data.get("summary") or f"Scrolled {direction}."
        return self._page_result(task, summary, data)

    async def _system_query(self, task: Task, context) -> ExecutionResult:
        """Answer a question about this machine by reading the OS directly.

        Replaces the PowerShell templates this engine used to generate
        (`Get-Process`, `Get-Date`, `Get-Volume`, `python --version`).
        Every answer here comes from psutil/platform/shutil, so there is
        no shell, no console window and no quoting to get wrong."""
        lowered = task.user_request.lower()

        if any(word in lowered for word in ("python", "node", "installed", "which")):
            result = await self.executor.invoke("system", {"action": "interpreter"}, context)
            data = result.structured_output
            summary = (f"Python {data['python_version']} ({data['implementation']}) "
                       f"at {data['executable']}.")
            rows = [[key.replace("_", " ").title(), str(value)] for key, value in data.items()]
            title = "Python installation"
        elif any(word in lowered for word in ("disk", "space", "storage")):
            result = await self.executor.invoke("system", {"action": "disks"}, context)
            volumes = result.structured_output["volumes"]
            summary = "; ".join(
                f"{v['mount']} {v['free_gb']}GB free of {v['total_gb']}GB" for v in volumes) or "No volumes found."
            rows = [[v["mount"], f"{v['free_gb']}GB free", f"{v['total_gb']}GB total",
                     f"{v['used_percent']}% used"] for v in volumes]
            title = "Disk volumes"
        elif any(word in lowered for word in ("time", "date", "clock")):
            result = await self.executor.invoke("system", {"action": "clock"}, context)
            data = result.structured_output
            summary = f"It is {data['local']} ({data['timezone']})."
            rows = [[key, str(value)] for key, value in data.items()]
            title = "System clock"
        else:
            sort_by = "cpu" if "cpu" in lowered else "memory"
            result = await self.executor.invoke(
                "system", {"action": "processes", "sort_by": sort_by, "limit": 8}, context)
            processes = result.structured_output["processes"]
            if not processes:
                raise RuntimeError("No process information could be read from this machine.")
            top = processes[0]
            unit = "% CPU" if sort_by == "cpu" else "MB"
            value = top["cpu_percent"] if sort_by == "cpu" else top["memory_mb"]
            summary = f"{top['name']} is using the most {'CPU' if sort_by == 'cpu' else 'memory'}: {value}{unit} (pid {top['pid']})."
            rows = [[p["name"], str(p["pid"]), f"{p['memory_mb']} MB", f"{p['cpu_percent']}%"]
                    for p in processes]
            title = f"Top processes by {'CPU' if sort_by == 'cpu' else 'memory'}"

        headers = {"Python installation": ["Property", "Value"],
                   "Disk volumes": ["Volume", "Free", "Total", "Used"],
                   "System clock": ["Field", "Value"]}.get(title, ["Process", "PID", "Memory", "CPU"])
        objects = [
            {"id": "table", "type": "comparison-table", "title": title,
             "eyebrow": "Read directly from the OS", "headers": headers, "rows": rows[:8],
             "frame": {"x": 6, "y": 8, "width": 54}},
            {"id": "verified", "type": "verified-result", "title": "Measured",
             "eyebrow": "No shell involved", "tone": "verified", "statement": summary,
             "evidence": ["psutil / platform reading, not a shell command"],
             "timestamp": generated_at(), "frame": {"x": 64, "y": 40, "width": 30, "layer": 2}},
        ]
        return ExecutionResult(
            response=summary,
            structured_data={"measurement": result.structured_output},
            ui_composition=self._base_composition(
                identifier="system-query", summary=summary, objects=objects),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _settings_open(self, task: Task, context) -> ExecutionResult:
        """Open a named Windows Settings page by its own protocol URI."""
        result = await self.executor.invoke(
            "desktop", {"action": "open_settings_page", "page": task.user_request}, context)
        if not result.success:
            raise RuntimeError(result.error or "Opening Settings failed")
        uri = result.structured_output.get("uri", "ms-settings:")
        window = await self._await_window("Settings", timeout=12.0)
        page = uri.split(":", 1)[1] or "home"
        summary = (
            f"Settings is open on the {page} page."
            if window else
            f"Settings was activated ({uri}) but no Settings window became visible."
        )
        if not window:
            raise RuntimeError(summary)
        return ExecutionResult(
            response=summary, structured_data={"uri": uri, "window": window},
            ui_composition=self._base_composition(
                identifier="settings-open", summary=summary,
                objects=[{
                    "id": "verified", "type": "verified-result", "title": "Settings opened",
                    "eyebrow": "Native protocol activation", "tone": "verified",
                    "statement": summary,
                    "evidence": [f"uri: {uri}", f"window: {window}", "no shell command was used"],
                    "timestamp": generated_at(), "frame": {"x": 30, "y": 30, "width": 34},
                }]),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _screen_observe(self, task: Task, context) -> ExecutionResult:
        """Answer "what is on my screen?" from a FRESH observation.

        Never from a cached tool result and never from model assumption:
        the whole failure mode this closes is VYOM confidently describing
        a desktop it had not looked at."""
        active = await self.executor.invoke("desktop", {"action": "active_window"}, context)
        windows = await self.executor.invoke("desktop", {"action": "window_list"}, context)
        foreground = (active.structured_output or {}).get("window") or {}
        open_windows = [
            window for window in (windows.structured_output or {}).get("windows", [])
            if window.get("title")
        ]
        if not foreground and not open_windows:
            raise RuntimeError("No visible window could be observed on this desktop.")
        titles = [window["title"] for window in open_windows][:8]
        front = foreground.get("title") or (titles[0] if titles else "unknown")
        summary = f"In front of you right now: {front}. Also open: " + (
            ", ".join(title for title in titles if title != front)[:300] or "nothing else"
        )
        objects = [
            {"id": "active", "type": "verified-result", "title": "Active window",
             "eyebrow": "Observed just now", "tone": "verified", "statement": front,
             "evidence": [f"process id: {foreground.get('process_id', 'unknown')}",
                          f"class: {foreground.get('class_name', 'unknown')}"],
             "timestamp": generated_at(), "frame": {"x": 4, "y": 6, "width": 32}},
            {"id": "windows", "type": "comparison-table", "title": "Open windows",
             "eyebrow": "Live desktop", "headers": ["Window"],
             "rows": [[title] for title in titles] or [["none"]],
             "frame": {"x": 40, "y": 6, "width": 52}},
        ]
        return ExecutionResult(
            response=summary,
            structured_data={"active_window": foreground, "windows": titles},
            ui_composition=self._base_composition(
                identifier="screen-observe", summary=summary, objects=objects),
            evidence=[f"Observed {len(titles)} visible window(s) directly from the OS"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _ui_interact(self, task: Task, context) -> ExecutionResult:
        """Operate a control inside an application the user can see.

        Accessibility first: the control is located by its accessible name
        or automation id, driven through its declared UIA action, and the
        result is read back from the same tree. No screenshot, no pixel
        coordinate, and no model in the loop once the intent is resolved."""
        from app.runtime.task_classifier import parse_arithmetic, parse_arithmetic_chain

        app_id = self._resolve_app_id(task.user_request)
        # A CHAIN first: "9 * 8 * 6 * 5 * 4 * 3 * 1 * 9 * 3" was answered
        # "9 times 8 is 72" because the binary parser silently took the
        # first pair. The chain parser only accepts three-or-more operands.
        calculation = parse_arithmetic_chain(task.user_request) or parse_arithmetic(task.user_request)

        if calculation and (app_id in (None, "calculator")):
            return await self._calculator_interaction(task, context, calculation)

        if app_id is None:
            # "ab search box me VYOM type karo" names no application: it
            # continues in whatever the user is looking at. Reading the
            # FOREGROUND window is how that context is inherited - fresh
            # from the OS, so it can never be stale the way a remembered
            # value would be.
            app_id = await self._active_window_app_id(context)
        if app_id is None:
            raise RuntimeError(
                "No visible application was identified for this request. VYOM will not "
                "operate a window it cannot name."
            )
        target = self._extract_control_target(task.user_request)
        if target is None:
            raise RuntimeError(
                "No control was named in the request; VYOM will not press an arbitrary "
                "control it was not asked for."
            )
        value = self._extract_typed_value(task.user_request)
        action = "set_control_value" if value is not None else "invoke_control"
        payload: dict[str, Any] = {"action": action, "app_id": app_id, "target": target}
        if value is not None:
            payload["value"] = value
        result = await self.executor.invoke("desktop", payload, context)
        if not result.success or not result.structured_output.get("success"):
            raise RuntimeError(
                result.error or f"'{target}' could not be operated through the accessibility layer")
        summary = result.structured_output.get("summary", f"Operated '{target}'")
        return ExecutionResult(
            response=summary, structured_data={"app_id": app_id, "target": target, "value": value},
            ui_composition=self._base_composition(
                identifier="ui-interact", summary=summary,
                objects=[{
                    "id": "verified", "type": "verified-result", "title": "Control operated",
                    "eyebrow": "Windows UI Automation", "tone": "verified", "statement": summary,
                    "evidence": [f"application: {app_id}", f"control: {target}",
                                 "driven through the accessibility tree, not screen coordinates"],
                    "timestamp": generated_at(), "frame": {"x": 30, "y": 30, "width": 36},
                }]),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    #: Calculator automation ids for the digits and operators. These come
    # from the app's own accessibility tree, so they are stable across
    # themes, languages and window sizes in a way pixels never are.
    _CALC_KEYS = {
        "0": "num0Button", "1": "num1Button", "2": "num2Button", "3": "num3Button",
        "4": "num4Button", "5": "num5Button", "6": "num6Button", "7": "num7Button",
        "8": "num8Button", "9": "num9Button", ".": "decimalSeparatorButton",
        "+": "plusButton", "-": "minusButton", "*": "multiplyButton", "/": "divideButton",
    }

    @staticmethod
    def _digits(number: float) -> str:
        return str(int(number)) if float(number).is_integer() else str(number)

    async def _calculator_interaction(self, task: Task, context, calculation) -> ExecutionResult:
        # `calculation` is either a binary (left, operator, right) tuple or
        # a CHAIN [(operand, operator-after), ..., (last, None)] - pressed
        # and evaluated strictly left to right, exactly like typing the
        # expression into a real calculator.
        from app.runtime.task_classifier import evaluate_chain

        chain = list(calculation) if isinstance(calculation, list) else None
        if chain is not None:
            segments = chain
            expected = evaluate_chain(segments)
            if expected is None:
                raise RuntimeError("That calculation could not be evaluated safely.")
            expression_parts: list[str] = []
            for value, operator in segments:
                expression_parts.append(self._digits(value))
                if operator:
                    expression_parts.append(operator)
            expression_text = " ".join(expression_parts)
        else:
            left, operator, right = calculation
            segments = [(left, operator), (right, None)]
            expected = {"+": left + right, "-": left - right,
                        "*": left * right, "/": (left / right if right else None)}[operator]
            expression_text = f"{self._digits(left)} {operator} {self._digits(right)}"

        status = await self.executor.invoke(
            "desktop", {"action": "app_status", "app_id": "calculator"}, context)
        if not status.structured_output.get("running"):
            opened = await self.executor.invoke(
                "desktop", {"action": "app_open", "app_id": "calculator"}, context)
            if not opened.structured_output.get("running"):
                raise RuntimeError("Calculator could not be opened, so the calculation was not performed.")

        targets = ["clearButton"]
        for value, operator in segments:
            targets += [self._CALC_KEYS[char] for char in self._digits(value) if char in self._CALC_KEYS]
            if operator:
                targets.append(self._CALC_KEYS[operator])
        targets.append("equalButton")

        pressed = await self.executor.invoke(
            "desktop", {"action": "invoke_sequence", "app_id": "calculator", "targets": targets}, context)
        if not pressed.success:
            raise RuntimeError(pressed.error or "The calculator controls could not be driven")

        await asyncio.sleep(0.5)
        display = await self.executor.invoke(
            "desktop", {"action": "get_control_value", "app_id": "calculator",
                        "target": "CalculatorResults"}, context)
        shown = str((display.structured_output or {}).get("value") or "")
        # POSTCONDITION: the app's OWN display must show the right answer.
        # Computing it here and asserting equality is what makes this a
        # verified outcome rather than a hopeful sequence of key presses.
        expected_text = self._digits(expected) if expected is not None else None
        normalised = shown.replace(",", "").replace("Display is", "").strip()
        verified = expected_text is not None and normalised == expected_text
        summary = (
            f"{expression_text} is {expected_text}."
            if verified else
            f"The calculation was entered but Calculator's display reads {shown!r}, "
            f"which does not match the expected {expected_text}."
        )
        if not verified:
            raise RuntimeError(summary)
        return ExecutionResult(
            response=summary,
            structured_data={"calculation": expression_text, "result": expected,
                             "display": shown, "expected": expected_text},
            ui_composition=self._base_composition(
                identifier="calculator", summary=summary,
                objects=[{
                    "id": "verified", "type": "verified-result", "title": "Calculation verified",
                    "eyebrow": "Read from Calculator's own display", "tone": "verified",
                    "statement": summary,
                    "evidence": [f"keys invoked: {', '.join(targets)}",
                                 f"display: {shown}",
                                 "driven through Windows UI Automation, no pixels"],
                    "timestamp": generated_at(), "frame": {"x": 28, "y": 26, "width": 40},
                }]),
            evidence=[f"Calculator display reads {shown}"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    @staticmethod
    def _extract_control_target(request: str) -> str | None:
        """Name the control the user referred to, from their own words."""
        patterns = (
            r"(?:click|press|dabao|dabana|tap)\s+(?:on\s+)?(?:the\s+)?[\"']?([\w \-]{2,40}?)[\"']?\s*(?:button|par|pe|$)",
            r"[\"']([^\"']{2,40})[\"']\s*(?:button|control|field|box)",
            r"(?:in|into|in the|me|mein)\s+(?:the\s+)?([\w \-]{2,30}?)\s*(?:box|field|bar|input)",
        )
        for pattern in patterns:
            match = re.search(pattern, request, re.I)
            if match and match.group(1).strip():
                return match.group(1).strip()
        return None

    @staticmethod
    def _extract_typed_value(request: str) -> str | None:
        match = re.search(r"(?:type|likho|likh|enter)\s+[\"']?([^\"']{1,80}?)[\"']?\s*(?:$|\bin\b|\bme\b|\bmein\b)",
                          request, re.I)
        return match.group(1).strip() if match else None

    async def _await_window(self, title_contains: str, *, timeout: float = 10.0) -> str | None:
        """Wait for a real visible window, reading the live window list."""
        import time as _time

        deadline = _time.monotonic() + timeout
        wanted = title_contains.lower()
        while _time.monotonic() < deadline:
            try:
                from app.desktop.window_manager import WindowManager

                for window in WindowManager().list():
                    if wanted in window.title.lower():
                        return window.title
            except Exception:
                pass
            await asyncio.sleep(0.4)
        return None

    async def _app_launch(self, task: Task, context) -> ExecutionResult:
        app_id = self._resolve_app_id(task.user_request)
        # A request that named no app because it used a PRONOUN - "to open
        # kijiye usko" - still has a target: the one ActiveContext resolved
        # the pronoun to. When that target is a web address, the app is the
        # browser. Without this, app resolution fell back to guessing at
        # the words themselves and reported "'kijiye' is not an application".
        if app_id is None:
            referent = task.metadata.get("referent_routed") or (
                task.metadata.get("cognitive") or {}).get("resolved_reference")
            if isinstance(referent, str) and referent.startswith(("http://", "https://")):
                app_id = self._resolve_app_id("chrome") or "chrome"
        if app_id is None:
            # NOT_FOUND, reached through real native resolution and stated
            # plainly. No shell fishing, no whole-disk scan, no second
            # opinion from a model - the resolvers below ARE the answer.
            named = self._named_application(task.user_request)
            raise CapabilityUnavailable(
                f"'{named}' is not an application I can find on this PC. I checked the "
                f"application registry, the Windows App Paths registry, the standard "
                f"install locations and the Start Menu."
                if named else
                "No application was named in the request, so there is nothing to launch."
            )
        if self.application_registry is not None and self.application_registry.get(app_id) is None:
            raise CapabilityUnavailable(
                f"Application '{app_id}' is not present in the Application Registry "
                f"(config/applications.yaml) or its executable could not be resolved on PATH."
            )
        before = self._running_image_names()
        # A launch usually has a TARGET: a folder for Explorer, a URL for a
        # browser, a project for an editor. Opening an empty window when
        # the user named a destination is a half-executed instruction.
        payload: dict[str, Any] = {"action": "app_open", "app_id": app_id}
        target = self._extract_launch_target(
            task.user_request, app_id,
            referent=(task.metadata.get("cognitive") or {}).get("resolved_reference"))
        if target:
            payload["url" if target.startswith(("http://", "https://")) else "target"] = target
        result = await self.executor.invoke("desktop", payload, context)
        if not result.success:
            raise RuntimeError(result.error or f"Launching {app_id} failed")
        # Real-world verification: the launcher's own pid is not enough on
        # Windows, where stubs like calc.exe hand off to a packaged app and
        # exit immediately. Confirm a NEW process actually appeared.
        appeared = await self._await_new_process(before, app_id)
        launched = result.structured_output
        passed = bool(appeared) or bool(launched.get("running"))
        # WHAT THE USER HEARS IS NOT A DIAGNOSTIC.
        #
        # This used to say "Chrome was launched and verified running (pid
        # 16596)". The pid is verification evidence, not an answer, and the
        # user asked for it to stop being narrated. It remains on the
        # evidence panel and in the logs below, where it belongs.
        app_name = app_id.replace("_", " ").title()
        summary = (
            f"{app_name} is open."
            if passed
            else f"I tried to open {app_name}, but no running process appeared."
        )
        objects = [
            {
                "id": "mission", "type": "task-mission", "title": "Application launch",
                "eyebrow": "Desktop capability", "tone": "intelligence", "mission": app_id,
                "status": "complete" if passed else "failed",
                "details": [f"pid {launched.get('pid')}" if launched.get("pid") else "launched", *appeared[:3]],
                "frame": {"x": 4, "y": 8, "width": 30},
            },
            {
                "id": "verified", "type": "verified-result", "title": "Launch verification",
                "eyebrow": "Evidence", "tone": "verified" if passed else "attention",
                "statement": summary,
                "evidence": [
                    f"app_id: {app_id}",
                    f"launcher pid: {launched.get('pid')}",
                    f"new processes: {', '.join(appeared) or 'none observed'}",
                ],
                "timestamp": generated_at(), "frame": {"x": 55, "y": 55, "width": 32, "layer": 2},
            },
        ]
        if not passed:
            raise RuntimeError(summary)
        return ExecutionResult(
            response=summary, structured_data={"app_id": app_id, "launch": launched, "processes": appeared},
            ui_composition=self._base_composition(identifier="app-launch", summary=summary, objects=objects),
            evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    @staticmethod
    def _running_image_names() -> set[str]:
        import psutil

        names = set()
        for process in psutil.process_iter(["name"]):
            name = (process.info.get("name") or "").lower()
            if name:
                names.add(name)
        return names

    async def _await_new_process(self, before: set[str], app_id: str, attempts: int = 20) -> list[str]:
        """Poll briefly for a process belonging to THIS application that was
        not running before the launch.

        Bounded (~5s) so a refusal to start is reported, not hidden. Only
        processes the registry says this application produces are counted:
        returning any unrelated process that happened to appear credited a
        launch with evidence that had nothing to do with it (an Explorer
        launch was reported as verified by `find.exe`), which is exactly
        the kind of plausible-but-wrong evidence this layer exists to
        prevent."""
        expected = set()
        if self.application_registry is not None:
            record = self.application_registry.get(app_id)
            if record is not None:
                expected = set(record.process_names or ())
                if record.executable:
                    expected.add(Path(record.executable).name.lower())
        if not expected:
            expected = {f"{app_id.replace('_', '')}.exe"}

        for _ in range(attempts):
            await asyncio.sleep(0.25)
            new = self._running_image_names() - before
            relevant = [name for name in new if name in expected]
            if relevant:
                return sorted(relevant)
        return []

    def _resolve_url(self, request: str) -> tuple[str, str]:
        """Return (url, kind). An explicit URL is used verbatim; otherwise
        a real web search is performed for the extracted query."""
        match = re.search(r"https?://\S+", request)
        if match:
            return match.group(0).rstrip(".,)"), "direct"
        bare = re.search(r"\bwww\.[^\s,]+", request, re.I)
        if bare:
            return f"https://{bare.group(0).rstrip('.,)')}", "direct"
        query = request
        for prefix in (
            "open a browser and search the web for", "open a browser and search for",
            "search the web for", "search online for", "search for", "look up",
            "google", "browse to", "find online",
        ):
            index = query.lower().find(prefix)
            if index >= 0:
                query = query[index + len(prefix):]
                break
        query = query.strip(" .?\"'")
        if not query:
            raise RuntimeError("No search query could be extracted from the request.")
        return f"https://www.bing.com/search?q={quote_plus(query)}", query

    async def _web_browse(self, task: Task, context) -> ExecutionResult:
        url, kind = self._resolve_url(task.user_request)
        opened = await self.executor.invoke(
            "browser", {"action": "open", "url": url, "expected_url": urlparse(url).netloc}, context
        )
        if not opened.success:
            raise RuntimeError(opened.error or f"The browser could not open {url}")
        if kind != "direct":
            # Search results render after navigation; wait for the results
            # container rather than reading a half-built page.
            await self.executor.invoke(
                "browser",
                {"action": "wait", "selector": "#b_results", "state": "visible", "timeout_ms": 12_000},
                context,
            )
        read = await self.executor.invoke("browser", {"action": "read"}, context)
        text = (read.structured_output.get("text") or "")[:6000]
        # Honest verification. A bot-interstitial or an empty body is NOT a
        # successful web search, and VYOM reports it as a failure with the
        # real reason instead of presenting the challenge page as a result.
        # VYOM never attempts to solve or bypass such a challenge.
        lowered = text.lower()
        if any(
            marker in lowered
            for marker in ("confirm this search was made by a human", "unusual traffic",
                           "are you a robot", "verify you are human", "enable javascript and cookies")
        ):
            raise RuntimeError(
                f"The page at {opened.structured_output.get('url', url)} served an automated-access "
                "challenge instead of results. VYOM will not bypass it; the search did not complete."
            )
        if len(text.strip()) < 200:
            raise RuntimeError(
                f"{opened.structured_output.get('url', url)} returned only "
                f"{len(text.strip())} characters of readable content; no result was obtained."
            )
        title = opened.structured_output.get("title") or read.structured_output.get("title") or ""
        landed = opened.structured_output.get("url") or url
        screenshot = self.project_root / "services" / "brain" / "data" / "screenshots" / f"{task.id}.png"
        shot = await self.executor.invoke(
            "screenshot", {"target": "browser", "path": str(screenshot), "full_page": False}, context
        )
        excerpt = "\n".join(line for line in text.splitlines() if line.strip())[:1800]
        summary = f"Browsed {landed} — '{title}' — and captured {len(text)} characters of page content."
        objects = [
            {
                "id": "browser", "type": "browser-preview", "title": title or "Web result",
                "eyebrow": "Playwright browser", "url": landed, "pageTitle": title,
                "screenshot": shot.structured_output.get("path") if shot.success else None,
                "status": "verified", "frame": {"x": 3, "y": 5, "width": 36},
            },
            {
                "id": "content", "type": "code-diff", "title": "Page content read",
                "eyebrow": "Evidence", "path": landed, "diff": excerpt,
                "frame": {"x": 44, "y": 5, "width": 52},
            },
            {
                "id": "verified", "type": "verified-result", "title": "Browsing verified",
                "eyebrow": "Evidence", "tone": "verified", "statement": summary,
                "evidence": [f"URL: {landed}", f"Title: {title}", f"Query: {kind}", f"Characters read: {len(text)}"],
                "timestamp": generated_at(), "frame": {"x": 35, "y": 76, "width": 30, "layer": 2},
            },
        ]
        return ExecutionResult(
            response=summary,
            structured_data={
                "url": landed, "title": title, "text": text, "query": kind,
                # Which services the user explicitly named, and where the
                # evidence actually came from. The goal verifier compares
                # them: a request for Gmail that lands on a Gmail MARKETING
                # page, or an Amazon request answered from Flipkart, is not
                # the task the user asked for.
                "requested_services": self._requested_services(task.user_request),
                "visited": [landed, title],
            },
            ui_composition=self._base_composition(identifier="web-browse", summary=summary, objects=objects),
            evidence=[f"Opened {landed}", f"Read {len(text)} characters"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    # Executables the request may name directly. Matching one of these
    # takes priority over quote extraction: a request like
    #   Run python -c "import sys; print(sys.version)"
    # must yield the whole `python -c "..."` invocation, not the quoted
    # Python source, which would be parsed as an executable named
    # "import" and refused by the command policy.
    #: Executables the request may name directly. `powershell`, `pwsh`,
    #: `dir` and `where` are deliberately ABSENT: none of them is a job
    #: VYOM needs a shell for. Reading the clock, listing a directory,
    #: reporting disk space and locating a program all have direct native
    #: answers, and routing them through a shell is what made the shell
    #: VYOM's universal - and unreliable - PC tool.
    _COMMAND_HEADS = (
        "python", "python3", "py", "node", "npm", "npx",
        "cargo", "git", "ffmpeg", "rg", "pytest",
    )

    #: Plain-language requests that name an interpreter but no literal
    #: command. Each maps to a concrete READ-ONLY invocation of a real
    #: executable, so a model never composes the text that gets executed.
    _COMMAND_TEMPLATES = (
        # Python asked to compute AND persist a result. The script is a
        # fixed literal here - VYOM executes a template it owns, never
        # shell or Python text authored by a model.
        (("python",), ("json",),
         'python -c "import json,pathlib,statistics;'
         "d={'samples':[2,4,8,16,32],'sum':62,'mean':12.4};"
         "d['mean']=statistics.mean(d['samples']);d['sum']=sum(d['samples']);"
         "p=pathlib.Path('data/vyom-python-check.json');p.parent.mkdir(parents=True,exist_ok=True);"
         "p.write_text(json.dumps(d,indent=1),encoding='utf-8');"
         "print('wrote',p,d)\""),
        (("python",), ("calculate", "calculation", "compute", "math", "sum", "safe calculation"),
         'python -c "import statistics;v=[2,4,8,16,32];'
         "print('sum',sum(v),'mean',statistics.mean(v),'max',max(v))\""),
        (("python",), ("installed", "version", "available", "have"), "python --version"),
        (("ffmpeg",), ("installed", "version", "available", "have"), "ffmpeg -version"),
        (("node",), ("installed", "version", "available", "have"), "node --version"),
        (("git",), ("installed", "version", "available", "have"), "git --version"),
        # Version-control reads, run as the real `git` executable.
        (("git",), ("status",), "git status"),
        (("git",), ("log", "history", "commits"), "git log --oneline -20"),
        (("git",), ("diff", "changed", "changes"), "git diff --stat"),
        (("git",), ("branch", "branches"), "git branch --show-current"),
    )

    # -- multi-retailer product comparison ---------------------------------

    #: Colour words worth carrying into the retailer query verbatim.
    _COLOURS = (
        "black", "white", "blue", "navy", "red", "green", "grey", "gray", "brown",
        "beige", "pink", "purple", "yellow", "orange", "maroon", "cream", "tan", "olive",
    )
    _STOP_WORDS = {
        "find", "me", "the", "best", "a", "an", "some", "good", "nice", "please",
        "buy", "book", "order", "get", "for", "on", "from", "and", "or", "in",
        "compare", "them", "prices", "price", "cheapest", "deal", "deals", "shop",
        "shopping", "looking", "want", "to", "my", "i", "vyom", "check", "all",
        "sites", "site", "online", "store", "stores", "amazon", "flipkart", "meesho",
        "myntra", "ajio", "under", "below", "rs", "inr", "rupees",
    }

    def _shopping_config(self) -> dict[str, Any]:
        import yaml

        path = self.project_root / "config" / "research.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data.get("shopping", {}) or {}

    def _parse_shopping_request(self, request: str) -> tuple[str, str | None, int | None]:
        """Return (query, colour, budget). The query is the user's own
        product words - VYOM does not invent a product it was not asked for."""
        lowered = request.lower()
        colour = next((c for c in self._COLOURS if re.search(rf"\b{c}\b", lowered)), None)
        budget = None
        budget_match = re.search(r"(?:under|below|less than|upto|up to|max)\s*(?:rs\.?|inr|₹)?\s*([0-9][0-9,]*)", lowered)
        if budget_match:
            budget = int(budget_match.group(1).replace(",", ""))
        words = [
            word for word in re.findall(r"[a-z0-9\-]+", lowered)
            if word not in self._STOP_WORDS and not word.isdigit()
        ]
        query = " ".join(dict.fromkeys(words))[:80].strip()
        if not query:
            raise RuntimeError(
                "No product could be identified in the request; VYOM will not guess what to shop for."
            )
        return query, colour, budget

    async def _shop_compare(self, task: Task, context) -> ExecutionResult:
        """Visit every ENABLED retailer, extract real product cards, and
        compare them.

        Nothing is ever purchased here - this produces options and
        evidence. A retailer that refuses automated browsers is reported
        as blocked with the configured reason; VYOM does not attempt to
        defeat bot protection and never substitutes invented products."""
        config = self._shopping_config()
        retailers = config.get("retailers", []) or []
        if not retailers:
            raise CapabilityUnavailable(
                "No retailers are configured under `shopping.retailers` in config/research.yaml."
            )
        limit = int(config.get("max_results_per_retailer", 8))
        settle_ms = int(config.get("page_settle_ms", 3500))
        query, colour, budget = self._parse_shopping_request(task.user_request)

        products: list[dict[str, Any]] = []
        site_status: list[dict[str, str]] = []

        for retailer in retailers:
            name = retailer.get("name", retailer.get("id", "retailer"))
            if not retailer.get("enabled", False):
                reason = (retailer.get("disabled_reason") or "not enabled").strip()
                site_status.append({"retailer": name, "state": "not searched", "detail": reason})
                await context.emit(
                    "tool_progress", f"{name} skipped: {reason[:120]}",
                    {"retailer": retailer.get("id"), "enabled": False},
                )
                continue
            url = str(retailer["search_url"]).replace("{query}", quote_plus(query))
            try:
                found = await self._scrape_retailer(retailer, url, limit, settle_ms, context)
            except Exception as error:
                site_status.append({"retailer": name, "state": "failed", "detail": str(error)[:160]})
                await context.emit(
                    "tool_failed", f"{name} search failed: {str(error)[:120]}",
                    {"retailer": retailer.get("id")},
                )
                continue
            if not found:
                site_status.append({"retailer": name, "state": "no results", "detail": f"0 products matched '{query}'"})
                continue
            products.extend(found)
            site_status.append({"retailer": name, "state": "searched", "detail": f"{len(found)} product(s)"})

        searched = [item for item in site_status if item["state"] == "searched"]
        if not products:
            detail = "; ".join(f"{item['retailer']}: {item['detail']}" for item in site_status)
            raise RuntimeError(
                f"No products could be retrieved for '{query}'. Retailer status - {detail}"
            )

        if budget is not None:
            in_budget = [item for item in products if item["price"] and item["price"] <= budget]
            if in_budget:
                products = in_budget
        if colour:
            preferred = [item for item in products if colour in item["title"].lower()]
            if preferred:
                products = preferred
        products.sort(key=lambda item: (item["price"] or 10**9))

        best = products[0]
        skipped = [item for item in site_status if item["state"] != "searched"]
        summary = (
            f"Compared {len(products)} '{query}' listing(s) across "
            f"{len(searched)} retailer(s). Lowest priced match: {best['title'][:60]} "
            f"at Rs {best['price']} on {best['retailer']}."
        )
        if skipped:
            summary += (
                " Not searched: "
                + ", ".join(f"{item['retailer']} ({item['state']})" for item in skipped)
                + "."
            )

        rows = [
            [
                item["retailer"],
                item["title"][:70],
                f"Rs {item['price']}" if item["price"] else "-",
                item["rating"] or "-",
            ]
            for item in products[:24]
        ]
        objects = [
            {
                "id": "options", "type": "comparison-table",
                "title": f"{query} - {len(products)} option(s)",
                "eyebrow": "Live retailer listings",
                "headers": ["Retailer", "Product", "Price", "Rating"],
                "rows": rows, "frame": {"x": 2, "y": 4, "width": 52},
            },
            {
                "id": "sites", "type": "comparison-table", "title": "Retailer status",
                "eyebrow": "Truthful coverage",
                "headers": ["Retailer", "State", "Detail"],
                "rows": [[item["retailer"], item["state"], item["detail"][:90]] for item in site_status],
                "frame": {"x": 56, "y": 4, "width": 42},
            },
            {
                "id": "verified", "type": "verified-result", "title": "Comparison verified",
                "eyebrow": "Evidence", "tone": "verified", "statement": summary,
                "evidence": [
                    f"Query: {query}" + (f" | colour: {colour}" if colour else "") + (f" | budget: Rs {budget}" if budget else ""),
                    *[f"{item['retailer']}: {item['state']} ({item['detail'][:60]})" for item in site_status],
                    f"Best: {best['url'][:100]}" if best.get("url") else "Best: link unavailable",
                    "No purchase was made. Ordering requires explicit approval.",
                ],
                "timestamp": generated_at(), "frame": {"x": 30, "y": 74, "width": 40, "layer": 2},
            },
        ]
        return ExecutionResult(
            response=summary,
            structured_data={
                "query": query, "colour": colour, "budget": budget,
                "products": products, "retailer_status": site_status,
                "purchased": False,
                # A retailer the user NAMED must actually have been
                # searched. Quietly answering an Amazon request with
                # Flipkart results is a different question answered.
                "requested_services": self._requested_services(task.user_request),
                "visited": [item["retailer"] for item in searched],
            },
            ui_composition=self._base_composition(identifier="shop-compare", summary=summary, objects=objects),
            evidence=[f"{item['retailer']}: {item['state']}" for item in site_status],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    @staticmethod
    def _clean_product_title(text: str) -> str:
        """Product-card text arrives as one run with no separators, e.g.
        'HOTSTYLETrendy & Stylish Running Shoes For Men Rs254 Rs99974% offHot Deal'.
        Keep the readable product name: cut at the price block, drop
        trailing badges, and separate a SHOUTED brand from the title."""
        title = re.split(r"[₹$]|\b\d+% off\b", text)[0].strip()
        title = re.sub(
            r"\s*(Only few left|Hot Deal|Bestseller|Sponsored|Ad|Assured|Free delivery).*$",
            "", title, flags=re.I,
        ).strip()
        # "HOTSTYLETrendy" -> "HOTSTYLE Trendy" (uppercase run meeting a
        # capitalised word is the brand/title boundary on these cards).
        title = re.sub(r"\b([A-Z][A-Z0-9&'’\-]{2,})(?=[A-Z][a-z])", r"\1 ", title)
        return re.sub(r"\s{2,}", " ", title).strip()[:110] or text[:110]

    async def _scrape_retailer(
        self, retailer: dict[str, Any], url: str, limit: int, settle_ms: int, context
    ) -> list[dict[str, Any]]:
        """Open one retailer's search page through the registered browser
        tool and read real product cards from it."""
        opened = await self.executor.invoke(
            "browser", {"action": "open", "url": url, "timeout_ms": 40_000}, context
        )
        if not opened.success:
            raise RuntimeError(opened.error or "the page could not be opened")
        await self.executor.invoke(
            "browser",
            {"action": "wait", "selector": retailer["card_selector"], "state": "visible",
             "timeout_ms": max(settle_ms, 8_000)},
            context,
        )
        extracted = await self.executor.invoke(
            "browser", {"action": "extract", "selector": retailer["card_selector"]}, context
        )
        if not extracted.success:
            raise RuntimeError(extracted.error or "product cards could not be read")
        blocks = extracted.structured_output.get("items", []) or []
        if not blocks:
            page_text = (await self.executor.invoke("browser", {"action": "read"}, context)).structured_output.get("text", "")
            lowered = page_text.lower()
            if "access denied" in lowered or "captcha" in lowered or "not a robot" in lowered:
                raise RuntimeError(
                    "the retailer refused the automated browser (access denied / verification page); "
                    "VYOM will not bypass it"
                )
            return []

        price_pattern = re.compile(retailer.get("price_pattern") or r"([0-9,]+)")
        rating_pattern = re.compile(retailer.get("rating_pattern") or r"([0-9]\.[0-9])")
        results: list[dict[str, Any]] = []
        for block in blocks[:limit]:
            joined = " ".join(line.strip() for line in str(block).split("\n") if line.strip())
            if not joined:
                continue
            price_match = price_pattern.search(joined)
            rating_match = rating_pattern.search(joined)
            results.append({
                "retailer": retailer.get("name", retailer.get("id")),
                "title": self._clean_product_title(joined),
                "price": int(price_match.group(1).replace(",", "")) if price_match else None,
                "rating": rating_match.group(1) if rating_match else None,
                # The card text carries no href, so this is the retailer's
                # own search page for the query - a link that genuinely
                # resolves, rather than a product URL VYOM cannot see.
                "url": url,
            })
        await context.emit(
            "verification_evidence",
            f"{retailer.get('name')}: read {len(results)} product card(s)",
            {"retailer": retailer.get("id"), "count": len(results), "url": url},
        )
        return results

    def _extract_command(self, request: str) -> str:
        lowered = request.lower()
        # A literal command the user typed always wins; a template only
        # fills in when the request names a tool in plain language
        # ("run PowerShell and tell me the current date").
        # "Is ffmpeg installed?" is not a literal `ffmpeg installed`
        # invocation. A literal command is one whose executable is followed
        # by something argument-shaped (a switch, a quote, or a path), or
        # which begins the request outright.
        # An executable name is only a LITERAL invocation when what follows
        # looks like an argument (a switch, a quote, or a path). "Python
        # installed hai?" begins with an executable name but is a question:
        # treating it as literal ran `python installed` and failed with
        # "can't open file 'installed'".
        argument_ahead = r"(?=[-/\"']|\S+[\\/.]\w)"
        has_literal = any(
            re.match(rf"^\s*{re.escape(head)}\b\s+{argument_ahead}", lowered)
            or re.search(rf"\b{re.escape(head)}\b\s+{argument_ahead}", lowered)
            for head in self._COMMAND_HEADS
        )
        if not has_literal:
            for tools, hints, template in self._COMMAND_TEMPLATES:
                if any(tool in lowered for tool in tools) and (
                    not hints or any(hint in lowered for hint in hints)
                ):
                    return template
        for head in self._COMMAND_HEADS:
            match = re.search(rf"\b({re.escape(head)}\b.*)$", request, re.I | re.S)
            if match:
                command = match.group(1).strip().rstrip(" .?")
                # Keep a trailing quote balanced if the sentence ended mid-quote.
                if command.count('"') % 2:
                    command += '"'
                return command
        quoted = re.search(r"[`\"']([^`\"']+)[`\"']", request)
        if quoted:
            return quoted.group(1).strip()
        match = re.search(r"run(?:\s+the)?\s+command\s+(.+)", request, re.I)
        if match:
            return match.group(1).strip(" .?")
        raise RuntimeError("No runnable command could be extracted from the request.")

    async def _run_command(self, task: Task, context) -> ExecutionResult:
        command = self._extract_command(task.user_request)
        result = await self.executor.invoke(
            "terminal", {"command": command, "cwd": str(self.project_root), "timeout": 120}, context
        )
        output = result.structured_output
        exit_code = output.get("exit_code")
        passed = exit_code == 0
        stdout = (output.get("stdout") or "").strip()
        stderr = (output.get("stderr") or "").strip()
        summary = (
            f"`{command}` exited {exit_code}. {stdout.splitlines()[0] if stdout else stderr[:120]}"
            if passed
            else f"`{command}` failed with exit code {exit_code}."
        )
        objects = [
            {
                "id": "terminal", "type": "terminal-output", "title": "Command execution",
                "eyebrow": "Real terminal", "command": command, "exitCode": exit_code,
                "output": (stdout or stderr or "no output")[-3000:],
                "frame": {"x": 8, "y": 7, "width": 52},
            },
            {
                "id": "verified", "type": "verified-result", "title": "Execution verification",
                "eyebrow": "Evidence", "tone": "verified" if passed else "attention",
                "statement": summary,
                "evidence": [f"Command: {command}", f"Working directory: {self.project_root}", f"Exit code: {exit_code}"],
                "timestamp": generated_at(), "frame": {"x": 35, "y": 72, "width": 30, "layer": 2},
            },
        ]
        if not passed:
            raise RuntimeError(f"{summary} {stderr[:300]}")
        return ExecutionResult(
            response=summary, structured_data={"command": command, **output},
            ui_composition=self._base_composition(identifier="run-command", summary=summary, objects=objects),
            evidence=[f"{command} -> exit {exit_code}"], usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    async def _situation_report(self, task: Task, context) -> ExecutionResult:
        """'What's happening today?' answered from REAL local sources only.

        Every source that is not connected is reported as disconnected.
        Nothing here is invented."""
        sources: list[dict[str, Any]] = []
        recent: list[dict[str, Any]] = []
        if self.task_store is not None:
            try:
                from app.schemas.tasks import TaskStatus

                active = await self.task_store.list_by_status(
                    {TaskStatus.QUEUED, TaskStatus.EXECUTING, TaskStatus.NEEDS_APPROVAL,
                     TaskStatus.PLANNING, TaskStatus.UNDERSTANDING, TaskStatus.PAUSED}
                )
                recent = [
                    {"id": item.id, "request": item.user_request[:70], "status": item.status.value}
                    for item in active[:10]
                ]
                sources.append({"name": "Task runtime", "status": "connected", "detail": f"{len(active)} active task(s)"})
            except Exception as error:
                sources.append({"name": "Task runtime", "status": "error", "detail": str(error)[:120]})
        else:
            sources.append({"name": "Task runtime", "status": "disconnected", "detail": "no task store attached"})

        if self.capability_registry is not None:
            records = self.capability_registry.list()
            available = [r for r in records if getattr(r.status, "value", str(r.status)) == "available"]
            unavailable = [r for r in records if getattr(r.status, "value", str(r.status)) != "available"]
            sources.append({
                "name": "Capabilities", "status": "connected",
                "detail": f"{len(available)} available, {len(unavailable)} unavailable/disconnected",
            })
            for record in unavailable[:6]:
                sources.append({
                    "name": record.capability_id, "status": "disconnected",
                    "detail": getattr(record.status, "value", str(record.status)),
                })
        else:
            sources.append({"name": "Capabilities", "status": "disconnected", "detail": "registry not attached"})

        connected = [item for item in sources if item["status"] == "connected"]
        summary = (
            f"{len(recent)} task(s) are in flight. {len(connected)} local source(s) are connected; "
            f"{len(sources) - len(connected)} are disconnected and were not substituted with sample data."
        )
        objects = [
            {
                "id": "summary", "type": "status-summary", "title": "Right now",
                "eyebrow": "Live local sources", "focus": summary,
                "stats": [
                    {"label": "Active tasks", "value": str(len(recent))},
                    {"label": "Connected", "value": str(len(connected)), "tone": "intelligence"},
                    {"label": "Disconnected", "value": str(len(sources) - len(connected)), "tone": "attention"},
                ],
                "frame": {"x": 3, "y": 5, "width": 30},
            },
            {
                "id": "sources", "type": "comparison-table", "title": "Source status",
                "eyebrow": "Truthful connection state",
                "headers": ["Source", "State", "Detail"],
                "rows": [[item["name"], item["status"], item["detail"][:60]] for item in sources[:40]],
                "frame": {"x": 40, "y": 5, "width": 40},
            },
            {
                "id": "verified", "type": "verified-result", "title": "Report verified",
                "eyebrow": "Evidence", "tone": "verified", "statement": summary,
                "evidence": [f"{item['name']}: {item['status']} ({item['detail']})" for item in sources[:6]],
                "timestamp": generated_at(), "frame": {"x": 35, "y": 74, "width": 30, "layer": 2},
            },
        ]
        return ExecutionResult(
            response=summary, structured_data={"sources": sources, "active_tasks": recent},
            ui_composition=self._base_composition(identifier="situation-report", summary=summary, objects=objects),
            evidence=[f"{len(sources)} local source(s) inspected"],
            usage=UsageRecord(total_tokens=0, estimated_cost=0),
        )

    def _base_composition(self, *, identifier: str, summary: str, objects: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "schemaVersion": 1, "id": identifier, "mode": "tool-execution", "label": "VYOM / Real execution",
            "summary": summary, "generatedAt": generated_at(), "objects": objects,
            "sequence": [
                {"id": f"step-{index}", "label": obj.get("eyebrow", "Tool activity"), "atMs": 160 + index * 330,
                 "state": "Verifying" if index == len(objects) - 1 else "Executing", "objectIds": [obj["id"]]}
                for index, obj in enumerate(objects)
            ],
        }

    def _workspace_result(self, workspace: dict[str, Any]) -> ExecutionResult:
        summary = f"Inspected {workspace['name']}: {', '.join(workspace['languages']) or 'unknown stack'} with {len(workspace['commands'])} runnable capabilities."
        objects = [
            {"id": "mission", "type": "task-mission", "title": "Project inspection", "eyebrow": "Real workspace", "tone": "intelligence", "mission": workspace["name"], "status": "complete", "details": [*workspace["languages"], *workspace["frameworks"]], "frame": {"x": 3, "y": 6, "width": 29}},
            {"id": "workflow", "type": "causal-diagram", "title": "Detected workflow", "eyebrow": "Capabilities", "nodes": [{"id": key, "label": key, "detail": value} for key, value in list(workspace["commands"].items())[:4]], "edges": [], "frame": {"x": 68, "y": 8, "width": 29}},
            {"id": "verified", "type": "verified-result", "title": "Inspection verified", "eyebrow": "Evidence", "tone": "verified", "statement": summary, "evidence": [f"Root: {workspace['root_path']}", f"Git: {workspace['repo_status'][:60]}", f"Top-level entries: {workspace['file_count']}"], "timestamp": generated_at(), "frame": {"x": 35, "y": 70, "width": 30, "layer": 2}},
        ]
        return ExecutionResult(response=summary, structured_data={"workspace": workspace}, ui_composition=self._base_composition(identifier="phase5-project-inspection", summary=summary, objects=objects), evidence=["Filesystem inventory captured", "Git state captured"], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    def _build_result(self, data: dict[str, Any]) -> ExecutionResult:
        workspace, verification = data["workspace"], data["verification"]
        command_output = data.get("build", {}).get("structured_output", {})
        summary = f"{workspace['name']} build {'passed' if verification['passed'] else 'failed'} using {workspace['commands'].get('build', 'no discovered command')}."
        objects = [
            {"id": "mission", "type": "task-mission", "title": "Build inspection", "eyebrow": "Coding worker", "tone": "intelligence", "mission": workspace["name"], "status": "complete" if verification["passed"] else "failed", "details": [*workspace["frameworks"], *workspace["languages"]], "frame": {"x": 2, "y": 4, "width": 29}},
            {"id": "terminal", "type": "terminal-output", "title": "Build command", "eyebrow": "Real terminal", "command": workspace["commands"].get("build", "not found"), "exitCode": command_output.get("exit_code"), "output": (command_output.get("stdout") or command_output.get("stderr") or verification["summary"])[-1800:], "frame": {"x": 68, "y": 4, "width": 30}},
            {"id": "verified", "type": "verified-result", "title": "Build verification", "eyebrow": "Evidence", "tone": "verified" if verification["passed"] else "attention", "statement": verification["summary"], "evidence": verification["evidence"], "timestamp": generated_at(), "frame": {"x": 35, "y": 70, "width": 30, "layer": 2}},
        ]
        return ExecutionResult(response=summary, structured_data=data, ui_composition=self._base_composition(identifier="phase5-build-verification", summary=summary, objects=objects), evidence=verification["evidence"], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    def _file_result(self, relative: str, data: dict[str, Any]) -> ExecutionResult:
        verification = data["verification"]
        summary = f"Created {relative} and verified it exists."
        diff_text = (data.get("diff") or {}).get("structured_output", {}).get("stdout", "Untracked file; metadata verification used.")
        objects = [
            {"id": "file", "type": "task-mission", "title": "Controlled file write", "eyebrow": "Filesystem", "tone": "intelligence", "mission": relative, "status": "complete", "details": [verification["summary"]], "frame": {"x": 3, "y": 7, "width": 28}},
            {"id": "diff", "type": "code-diff", "title": "What changed", "eyebrow": "Git / file evidence", "path": relative, "diff": diff_text[:1800], "frame": {"x": 68, "y": 7, "width": 29}},
            {"id": "verified", "type": "verified-result", "title": "File verification", "eyebrow": "Evidence", "tone": "verified", "statement": verification["summary"], "evidence": verification["evidence"], "timestamp": generated_at(), "frame": {"x": 35, "y": 70, "width": 30, "layer": 2}},
        ]
        return ExecutionResult(response=summary, structured_data=data, ui_composition=self._base_composition(identifier="phase5-file-created", summary=summary, objects=objects), evidence=verification["evidence"], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    def _test_result(self, data: dict[str, Any]) -> ExecutionResult:
        verification = data["verification"]
        command = data["workspace"]["commands"].get("test") or data["workspace"]["commands"].get("python_tests", "not found")
        output = data.get("test", {}).get("structured_output", {})
        summary = verification["summary"]
        objects = [
            {"id": "terminal", "type": "terminal-output", "title": "Test execution", "eyebrow": "Real terminal", "command": command, "exitCode": output.get("exit_code"), "output": (output.get("stdout") or output.get("stderr") or summary)[-2000:], "frame": {"x": 3, "y": 7, "width": 31}},
            {"id": "verified", "type": "verified-result", "title": "Test verification", "eyebrow": "Evidence", "tone": "verified" if verification["passed"] else "attention", "statement": summary, "evidence": verification["evidence"], "timestamp": generated_at(), "frame": {"x": 66, "y": 58, "width": 31}},
        ]
        return ExecutionResult(response=summary, structured_data=data, ui_composition=self._base_composition(identifier="phase5-tests", summary=summary, objects=objects), evidence=verification["evidence"], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    def _diff_result(self, data: dict[str, Any]) -> ExecutionResult:
        output = data.get("structured_output", {})
        diff = output.get("stdout", "")
        summary = "Git diff captured." if diff.strip() else "No tracked Git diff is currently present."
        objects = [
            {"id": "diff", "type": "code-diff", "title": "Working tree diff", "eyebrow": "Git evidence", "path": self.project_root.name, "diff": diff[:4000] or "Working tree has no tracked diff.", "frame": {"x": 18, "y": 7, "width": 64}},
            {"id": "verified", "type": "verified-result", "title": "Diff inspection", "eyebrow": "Verified", "tone": "verified", "statement": summary, "evidence": [f"Branch: {output.get('branch', 'unknown')}", f"Git exit code: {output.get('exit_code')}"], "timestamp": generated_at(), "frame": {"x": 35, "y": 73, "width": 30, "layer": 2}},
        ]
        return ExecutionResult(response=summary, structured_data=data, ui_composition=self._base_composition(identifier="phase5-git-diff", summary=summary, objects=objects), evidence=[summary], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    def _browser_result(self, data: dict[str, Any]) -> ExecutionResult:
        verification = data.get("verification", {})
        passed = bool(verification.get("passed"))
        browser = data["browser"].get("structured_output", {})
        screenshot = data["screenshot"].get("structured_output", {}).get("path")
        summary = "The local VYOM home screen loaded and was visually captured." if passed else "The local app opened, but browser verification did not pass."
        objects = [
            {"id": "browser", "type": "browser-preview", "title": "Local application", "eyebrow": "Playwright", "url": browser.get("url", ""), "pageTitle": browser.get("title", ""), "screenshot": screenshot, "status": "verified" if passed else "failed", "frame": {"x": 3, "y": 5, "width": 34}},
            {"id": "workflow", "type": "causal-diagram", "title": "Browser verification", "eyebrow": "Real workflow", "nodes": [{"id": "dev", "label": "Dev server"}, {"id": "open", "label": "Open URL"}, {"id": "inspect", "label": "Inspect DOM"}, {"id": "capture", "label": "Screenshot"}], "edges": [{"from": "dev", "to": "open"}, {"from": "open", "to": "inspect"}, {"from": "inspect", "to": "capture"}], "frame": {"x": 65, "y": 6, "width": 32}},
            {"id": "verified", "type": "verified-result", "title": "Home screen", "eyebrow": "Evidence", "tone": "verified" if passed else "attention", "statement": summary, "evidence": [f"URL: {browser.get('url')}", f"Title: {browser.get('title')}", f"Screenshot: {screenshot}"], "timestamp": generated_at(), "frame": {"x": 35, "y": 71, "width": 30, "layer": 2}},
        ]
        if not verification:
            verification = {"passed": False, "summary": "Browser verification evidence was missing", "evidence": []}
            data["verification"] = verification
        return ExecutionResult(response=summary, structured_data=data, ui_composition=self._base_composition(identifier="phase5-browser-verification", summary=summary, objects=objects), evidence=[summary, f"Screenshot: {screenshot}"], usage=UsageRecord(total_tokens=0, estimated_cost=0))

    def _simple_result(self, summary: str, data: dict[str, Any], passed: bool = True) -> ExecutionResult:
        return ExecutionResult(response=summary, structured_data=data, evidence=[summary] if passed else [], usage=UsageRecord(total_tokens=0, estimated_cost=0))
