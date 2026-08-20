from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.schemas.events import EventType
from app.schemas.tasks import Task, TaskProfile

from app.memory.resolution import ResolutionChain
from app.memory.namespaces import CognitiveNamespace, infer_namespace

EventEmitter = Any


@dataclass
class ActiveContext:
    """Compact active context (rule 30): current project, client,
    mission, artifact, research, browser task — enabling 'continue',
    'show it', 'fix it', 'make a PDF of this' without repeated
    explanation. Domain safety: entries are domain-tagged and never
    leak across boundaries (rule 31)."""

    project: str | None = None
    client: str | None = None
    mission_id: str | None = None
    artifact: str | None = None
    research: str | None = None
    browser_task: str | None = None
    last_task_id: str | None = None
    last_verified_goal: str | None = None
    history: list[str] = field(default_factory=list)

    # -- what actually happened, as observed ---------------------------
    #
    # Everything above is derived from what VYOM was ASKED and what memory
    # matched. Nothing recorded what VYOM actually DID, so "to open kijiye
    # usko" - said immediately after discussing luxora designs.space -
    # resolved "usko" to a Zoho workflow, because that was the strongest
    # keyword hit in durable memory. A pronoun points at the conversation,
    # not at the memory store.
    last_target: str | None = None            # the thing acted on
    last_entity: str | None = None            # the thing being discussed
    last_url: str | None = None
    last_app: str | None = None
    last_browser_profile: dict | None = None
    last_successful_action: str | None = None
    last_failure: str | None = None
    #: The most recent real reading of the screen, and when it was taken.
    #: A follow-up about "this" must be answered from a FRESH observation,
    #: never from business memory.
    last_screen: dict | None = None
    last_screen_at: float | None = None

    def snapshot(self) -> dict:
        return {key: value for key, value in self.__dict__.items() if value is not None}

    def screen_age_seconds(self, now: float) -> float | None:
        """How stale the last screen reading is, in seconds."""
        if self.last_screen_at is None:
            return None
        return max(0.0, now - self.last_screen_at)


class CognitiveRuntime:
    """Phase 16: the ResolutionChain becomes REAL Task Runtime
    behavior. Every meaningful task begins here:

    Goal -> resolve context -> Memory -> Experience -> Knowledge ->
    Skill -> Tool -> (external research only if needed) -> Planner

    Also provides memory-before-question answers, conversational
    follow-up resolution, and cross-session continuation — all from
    existing stores, no new persistence."""

    def __init__(self, resolution_chain: ResolutionChain, context_service, *, emit=None):
        self.resolution = resolution_chain
        self.context_service = context_service          # AdaptiveContextService
        self.emit = emit                                # async (task, EventType, message, payload)
        self.active = ActiveContext()

    async def _emit(self, task: Task, event_type: EventType, message: str, payload: dict) -> None:
        if self.emit is None:
            return
        await self.emit(task, event_type, message, payload)

    # -- live runtime hook (called from TaskRuntime.run) --------------------

    async def prepare(self, task: Task, profile: TaskProfile) -> dict:
        """Runs for every meaningful task BEFORE planning: resolves the
        resolution chain, builds the compact ExperienceContext, applies
        follow-up reference resolution, updates active context, and
        emits operational events (never chain-of-thought)."""
        goal = task.user_request

        # Follow-up understanding: resolve 'that'/'it'/'continue' against
        # the active context before hitting the chain.
        resolved_reference = self.resolve_reference(goal)
        if resolved_reference:
            goal = f"{goal} [re: {resolved_reference[:80]}]"

        resolution = await self.resolution.resolve(
            goal, domain=profile.domain.value, text=task.user_request)
        namespace = resolution.namespace

        experience_context = None
        if self.context_service is not None and profile.complexity >= 2:
            experience_context = await self.context_service.build_experience_context(
                goal, profile.domain.value, {}, {})

        cognitive = {
            "namespace": namespace.value,
            "resolution_source": resolution.source,
            "resolved": resolution.resolved,
            "resolution_trace": resolution.trace,
            "hits": resolution.hits[:3],
            "resolved_reference": resolved_reference,
            "reuse_decision": experience_context.reuse_decision.model_dump() if experience_context and experience_context.reuse_decision else None,
            "similar_experiences": experience_context.similar_experiences if experience_context else [],
            "relevant_failures": experience_context.relevant_failures if experience_context else [],
        }
        task.metadata["cognitive"] = cognitive

        if resolution.resolved:
            source = resolution.source
            first = resolution.hits[0] if resolution.hits else {}
            label = first.get("title") or first.get("goal") or first.get("name") or "prior knowledge"
            await self._emit(
                task, EventType.TASK_PROGRESS,
                f"Using {source} before planning: {str(label)[:90]}",
                {"cognitive": {"source": source, "namespace": namespace.value}},
            )
        if cognitive["reuse_decision"] and cognitive["reuse_decision"]["action"] == "reuse":
            await self._emit(
                task, EventType.TASK_PROGRESS,
                "Reusing previous verified solution (conditions match)",
                {"cognitive": {"reuse": cognitive["reuse_decision"]["reasons"][:1]}},
            )

        self._update_active_context(task, resolution)
        return cognitive

    def _update_active_context(self, task: Task, resolution) -> None:
        self.active.last_task_id = task.id
        self.active.history.append(task.user_request[:120])
        self.active.history = self.active.history[-10:]
        if resolution.resolved and resolution.source in ("memory", "experience"):
            first = resolution.hits[0] if resolution.hits else {}
            goal_text = first.get("goal") or first.get("title")
            if goal_text:
                self.active.last_verified_goal = str(goal_text)[:160]
        if resolution.namespace == CognitiveNamespace.PROJECTS:
            self.active.project = task.user_request[:80]
        if resolution.namespace == CognitiveNamespace.AGENCY:
            self.active.client = task.user_request[:80]
        if resolution.namespace == CognitiveNamespace.RESEARCH:
            self.active.research = task.user_request[:80]

    # -- memory before questions (rule 2) -----------------------------------

    async def answer_from_memory(self, question: str) -> dict | None:
        """Answers factual/context questions from verified memory,
        entities, experiences, and current context BEFORE asking the
        user. Returns None only when memory is missing, ambiguous,
        stale, or conflicting — then asking is legitimate."""
        resolution = await self.resolution.resolve(question)
        if not resolution.resolved:
            return None
        hit = resolution.hits[0]
        if resolution.source == "memory":
            confidence = float(hit.get("confidence", 0.5))
            if confidence < 0.4:
                return None  # low-confidence memory is not an answer
            # The hit must actually be ABOUT the asked entity — a related
            # memory that never mentions the asked subject is "missing",
            # and asking the user stays legitimate.
            if not self._subject_matches(question, str(hit.get("title", "")) + str(hit.get("summary", ""))):
                return None
            return {"answer": hit.get("summary"), "source": "memory", "confidence": confidence}
        return None

    @staticmethod
    def _subject_matches(question: str, text: str) -> bool:
        question_tokens = {token for token in question.lower().replace("?", " ").split() if len(token) > 3}
        text_tokens = {token for token in text.lower().replace("\\", " ").split() if len(token) > 3}
        generic = {"where", "what", "project", "the", "does", "have", "tell", "about"}
        specific = question_tokens - generic
        if not specific:
            return True
        return bool(specific & text_tokens)
        return {"answer": (resolution.hits[0].get("summary") or resolution.hits[0].get("goal")),
                "source": resolution.source, "confidence": 0.5}

    # -- follow-up understanding (rule 3) ------------------------------------

    #: Pronouns that point at the thing just discussed or just done. The
    #: original list was English-only ("that", "fix it", "continue"), so
    #: every Hindi/Hinglish follow-up the user actually speaks - "usko",
    #: "isko", "ye kya hai" - was not even recognised as a follow-up and
    #: fell through to a keyword search of durable memory.
    _REFERENT_MARKERS = (
        "that", "fix it", "continue", "show it", "from this", "yesterday",
        "usko", "usko ", "isko", "ise", "use ", "uske", "iske", "wo ", "woh",
        "ye ", "yeh ", "is ko", "us ko", "isi", "usi", "uspe", "ispe",
        "इसको", "उसको", "इसे", "उसे", "यह", "ये", "वह", "वो", "इसी", "उसी",
        "this one", "it.", " it ", "same",
    )

    def resolve_reference(self, text: str) -> str | None:
        """Resolve a pronoun to what it actually points at.

        PRIORITY (the control contract's order):
          1. the active mission's own target/entity  - what we were just doing
          2. the last thing actually observed        - what is actually there
          3. durable memory                          - only as a last resort

        Durable memory used to be FIRST in practice, which is how "to open
        kijiye usko" opened a Zoho workflow from an old record instead of
        the site under discussion one turn earlier."""
        lowered = text.lower()
        if not any(marker in lowered for marker in self._REFERENT_MARKERS):
            return None

        # "continue"/"yesterday" explicitly reach back across the session.
        if "continue" in lowered or "yesterday" in lowered:
            return self.active.last_verified_goal

        # 1. the active mission
        for candidate in (self.active.last_target, self.active.last_url,
                          self.active.last_entity, self.active.last_app):
            if candidate:
                return str(candidate)[:160]
        # 2. the last real observation
        if self.active.last_screen:
            window = self.active.last_screen.get("active")
            if window:
                return str(window)[:160]
        # 3. durable memory, last
        return self.active.last_verified_goal or (
            self.active.history[-2] if len(self.active.history) >= 2 else None)

    # -- what actually happened ---------------------------------------------

    def record_observation(self, *, task, result) -> None:
        """Record what a finished task ACTUALLY did, for the next turn.

        Reads the execution's own structured data - the URL that was
        opened, the profile that was attached to, the windows that were
        read - so the next pronoun resolves against reality rather than
        against whatever memory happened to rank highest."""
        import time as _time

        data = getattr(result, "structured_data", None) or {}
        if not isinstance(data, dict):
            return

        observations = data.get("observations") or []
        payloads: list[dict] = [data]
        for item in observations:
            if isinstance(item, dict) and isinstance(item.get("output"), dict):
                payloads.append(item["output"])
            if isinstance(item, dict) and isinstance(item.get("inputs"), dict):
                payloads.append(item["inputs"])
        # The deterministic paths nest their real evidence one level down -
        # an app launch reports its destination as structured_data["launch"]
        # ["target"], not at the top level. Reading only the top level set
        # the referent to "chrome" instead of the site that was opened, so
        # the next "usko" still had no URL to point at.
        for payload in list(payloads):
            for value in payload.values():
                if isinstance(value, dict):
                    payloads.append(value)

        # A URL is a far more specific referent than an app name, so let
        # any URL in the evidence win regardless of iteration order.
        for payload in payloads:
            url = payload.get("url") or payload.get("target")
            if url and str(url).startswith(("http://", "https://")):
                self.active.last_url = str(url)
                self.active.last_target = str(url)
            if payload.get("app_id"):
                self.active.last_app = str(payload["app_id"])
            if isinstance(payload.get("profile"), dict) and payload["profile"].get("directory"):
                self.active.last_browser_profile = dict(payload["profile"])

            # A real reading of the screen, with the time it was taken.
            window = payload.get("window")
            windows = payload.get("windows")
            active_window = payload.get("active_window")
            if isinstance(window, dict) and window.get("title"):
                self.active.last_screen = {"active": window.get("title"), "all": []}
                self.active.last_screen_at = _time.time()
            elif isinstance(active_window, dict) and active_window.get("title"):
                self.active.last_screen = {"active": active_window.get("title"), "all": []}
                self.active.last_screen_at = _time.time()
            elif isinstance(windows, list) and windows:
                titles = [str(item.get("title", "")) for item in windows
                          if isinstance(item, dict) and item.get("title")]
                focused = next((str(item.get("title")) for item in windows
                                if isinstance(item, dict) and item.get("focused")), None)
                self.active.last_screen = {"active": focused or (titles[0] if titles else None),
                                           "all": titles[:12]}
                self.active.last_screen_at = _time.time()

        # Only when nothing more specific was observed does the app itself
        # become the referent.
        if not self.active.last_target and self.active.last_app:
            self.active.last_target = self.active.last_app

        goal = getattr(task, "user_request", "") or ""
        status = getattr(getattr(task, "status", None), "value", "")
        if status == "completed":
            self.active.last_successful_action = goal[:160]
        elif status in {"failed", "cancelled"}:
            self.active.last_failure = f"{goal[:80]} — {str(getattr(task, 'error', ''))[:120]}"

    async def continue_session(self) -> dict:
        """Cross-session continuation through the existing Phase 15
        context service (unfinished work + last verified step)."""
        return await self.context_service.continue_from_previous_session()
