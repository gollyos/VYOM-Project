from __future__ import annotations

from app.schemas.tasks import PlanStep, Task, TaskProfile


class Planner:
    def __init__(self, complexity_threshold: int = 3):
        self.complexity_threshold = complexity_threshold

    def create_plan(self, task: Task, profile: TaskProfile) -> list[PlanStep]:
        if "business" in profile.needs:
            source = PlanStep(title="Check source availability", summary="Resolve connected providers and persistent local records without inventing missing data.")
            operate = PlanStep(title="Execute bounded workflow", summary="Perform the read, draft, CRM, approval, or automation operation at its declared permission level.", dependencies=[source.id])
            verify = PlanStep(title="Verify operating evidence", summary="Require record IDs, provider IDs, source status, or explicit unavailability.", dependencies=[operate.id])
            return [source, operate, verify]
        if "intelligence" in profile.needs:
            if profile.intent in {"create_build_skill", "create_project_health_agent"}:
                search = PlanStep(title="Search existing intelligence", summary="Check capabilities and equivalent skills/agents before creating anything.")
                validate = PlanStep(title="Build declarative specification", summary="Define bounded capabilities, permissions, memory scope, budget, steps, and verification.", dependencies=[search.id])
                test = PlanStep(title="Sandbox and evaluate", summary="Run deterministic policy checks and a bounded sample mission where required.", dependencies=[validate.id])
                return [search, validate, test]
            if profile.intent in {"run_build_skill", "run_project_health_agent"}:
                match = PlanStep(title="Match reusable intelligence", summary="Select an active skill or ready agent without creating a duplicate.")
                execute = PlanStep(title="Execute through central runtime", summary="Use registered tools, inherited permissions, and bounded budgets.", dependencies=[match.id])
                verify = PlanStep(title="Verify and learn", summary="Require real evidence and update performance memory.", dependencies=[execute.id])
                return [match, execute, verify]
            retrieve = PlanStep(title="Resolve memory scope", summary="Apply type, privacy, provenance, and project context filters.")
            act = PlanStep(title="Read or modify memory", summary="Perform the explicit observable memory operation.", dependencies=[retrieve.id])
            verify = PlanStep(title="Verify memory evidence", summary="Return memory IDs and provenance without hidden reasoning.", dependencies=[act.id])
            return [retrieve, act, verify]
        if profile.intent == "inspect_project_build":
            inspect = PlanStep(title="Inspect project", summary="Detect stack, Git state, and runnable capabilities through registered tools.")
            build = PlanStep(title="Run discovered build", summary="Execute the repository build command with timeout and output limits.", dependencies=[inspect.id])
            verify = PlanStep(title="Verify real output", summary="Require a successful exit code and store command evidence.", dependencies=[build.id])
            return [inspect, build, verify]
        if profile.intent == "create_project_file":
            create = PlanStep(title="Create controlled file", summary="Write only inside the approved project root.")
            verify = PlanStep(title="Verify file", summary="Read metadata and Git diff evidence where available.", dependencies=[create.id])
            return [create, verify]
        if profile.intent == "open_local_app":
            discover = PlanStep(title="Discover development command", summary="Inspect project capabilities.")
            launch = PlanStep(title="Launch local app", summary="Track the bounded background process.", dependencies=[discover.id])
            verify = PlanStep(title="Verify home screen", summary="Use Playwright DOM state and screenshot evidence.", dependencies=[launch.id])
            return [discover, launch, verify]
        if profile.intent in {"inspect_project", "run_tests", "delete_project_file", "show_changes"}:
            return [
                PlanStep(title="Execute registered tools", summary="Use the controlled Phase 5 tool layer."),
                PlanStep(title="Verify evidence", summary="Confirm real outputs before completion."),
            ]
        if profile.complexity < self.complexity_threshold:
            return [PlanStep(title="Resolve request", summary="Produce and verify the requested result.")]

        if profile.intent == "plan_today":
            context = PlanStep(title="Review priorities", summary="Identify commitments, decisions, and focus constraints.")
            sequence = PlanStep(
                title="Sequence the day",
                summary="Arrange focused work, meetings, and approval windows.",
                dependencies=[context.id],
            )
            verify = PlanStep(
                title="Check feasibility",
                summary="Confirm time blocks and expose the highest-priority action.",
                dependencies=[sequence.id],
            )
            return [context, sequence, verify]

        inspect = PlanStep(title="Inspect context", summary="Gather the supplied task context and constraints.")
        execute = PlanStep(
            title="Produce result",
            summary="Complete the non-tool reasoning work with the routed provider.",
            dependencies=[inspect.id],
        )
        verify = PlanStep(
            title="Verify output",
            summary="Check structure, completeness, and evidence before completion.",
            dependencies=[execute.id],
        )
        return [inspect, execute, verify]


class ModelAssistedPlanner:
    """OPTIONAL mission-planning contract for MissionLoop (Phase 17).

    Deterministic decomposition stays the default and the fallback; a
    model is consulted ONLY for genuinely complex/unknown missions
    (long, multi-domain, or no deterministic split found). The model
    returns a STRUCTURED plan (step titles) through the existing
    provider/structured-output path — bounded to one call and a maximum
    step count; no chain-of-thought is requested or stored; any
    failure, refusal, or schema mismatch falls back to the
    deterministic plan."""

    MAX_MODEL_STEPS = 12

    def __init__(self, model_router=None, providers=None, *, complexity_words: int = 24):
        self.model_router = model_router
        self.providers = providers
        self.complexity_words = complexity_words

    @staticmethod
    def deterministic_plan(goal: str) -> list[str]:
        import re

        # Split on commas/" and " (original) PLUS sentence boundaries and
        # explicit fallback/alternative connectors ("if that fails",
        # "instead", "otherwise", "if not") — a goal like "Try X. If that
        # fails, instead do Y." has NO comma-before-and-list structure but
        # is very much two real steps; without these markers the whole
        # sentence became one unsplittable clause and a genuine fallback
        # instruction from the user was silently dropped from the plan.
        normalized = re.sub(
            r"\s*(?:if that fails|if it fails|if unsuccessful|if not|otherwise)\s*,?\s*(?:instead\s+)?",
            ". ", goal, flags=re.IGNORECASE,
        )
        parts = [
            part.strip()
            for part in re.split(r",\s+|\s+and\s+|(?<=[.!?])\s+", normalized)
            if part.strip()
        ]
        actionable = [part for part in parts if len(part) > 3]
        if len(actionable) >= 2:
            return [part[0].upper() + part[1:] for part in actionable][: ModelAssistedPlanner.MAX_MODEL_STEPS]
        return [
            "Understand the task and constraints",
            "Gather the required inputs",
            "Execute the core work",
            "Verify the result against the goal",
            "Report the outcome with evidence",
        ]

    def _needs_model(self, goal: str, context: dict) -> bool:
        if len(goal.split()) < self.complexity_words and len(context.get("prior_knowledge", {}) or {}) > 0:
            return False
        # Genuinely complex: long, multi-clause, unknown to memory.
        clauses = [part for part in goal.replace(";", ",").split(",") if len(part.strip()) > 3]
        return len(goal.split()) >= self.complexity_words or len(clauses) >= 5

    async def plan_mission(self, goal: str, context: dict) -> list[str]:
        deterministic = self.deterministic_plan(goal)
        if not self._needs_model(goal, context):
            return deterministic
        plan = await self._model_plan(goal)
        if not plan:
            return deterministic
        # Plan-quality guard: a model plan with FEWER real steps than the
        # goal's own deterministic decomposition is a worse plan, not a
        # better one — it means the model merged clauses the user
        # explicitly separated (e.g. collapsing "do X. If that fails,
        # instead do Y." into one step), silently dropping a fallback
        # instruction the user gave on purpose. Prefer whichever plan
        # actually covers more of the goal's distinct clauses.
        if len(deterministic) > len(plan) and len(deterministic) >= 2:
            return deterministic
        return plan

    async def _model_plan(self, goal: str) -> list[str] | None:
        if self.model_router is None or self.providers is None:
            return None
        try:
            from app.schemas.tasks import Task, TaskCreate, TaskProfile

            task = Task.from_create(TaskCreate(user_request=goal))
            profile = TaskProfile(domain=task.domain, complexity=3, deterministic=False, intent="mission_planning")
            decision = await self.model_router.route(task, profile)
            provider = self.providers.get(decision.primary_provider)
            if provider is None or not provider.configured:
                return None
            from app.providers.base import ProviderRequest
            from app.schemas.tasks import TaskProfile as _Profile

            request = ProviderRequest(
                model=decision.primary_model,
                user_request=goal,
                system_instruction=(
                    "You are a mission planner. Return ONLY a JSON object of the shape "
                    '{"steps": ["...", "..."]} with between 3 and 12 short imperative step '
                    "titles that complete the user's goal. No explanations, no reasoning."
                ),
                profile=_Profile(domain=task.domain, complexity=3, deterministic=False, intent="mission_planning"),
            )
            response = await provider.structured_output(request)
            data = response.structured if isinstance(response.structured, dict) else None
            steps = [str(step).strip() for step in (data or {}).get("steps", []) if str(step).strip()]
            steps = steps[: self.MAX_MODEL_STEPS]
            return steps if len(steps) >= 3 else None
        except Exception:
            return None  # bounded: fall back to the deterministic plan


# ======================================================================
# General tool-calling planner
# ======================================================================
#
# The deterministic classifier is an OPTIMIZATION for known commands, not
# VYOM's intelligence. Anything it did not recognise used to reach a
# text-only model, which could only describe what the user might do - or
# invent an answer ("The Sohon Agency is a creative marketing firm...").
# This planner closes that gap: it hands the model the LIVE tool registry
# as callable contracts and requires a structured call, so an unknown
# goal still reaches real capabilities.

#: Words meaning the answer depends on the world right now. A request
#: carrying one of these may never be answered from pretrained knowledge.
FRESHNESS_MARKERS = (
    "latest", "current", "today", "now", "recent", "news", "update", "updates",
    "price", "cost", "review", "compare", "research", "trending", "release",
    "released", "version", "status of", "aaj", "abhi", "naya", "nayi", "taza",
    # "Real-time mein sabse best AI model kaun sa hai?" was answered from
    # stale training data (an old model name) instead of being research-
    # gated, because none of the above matched "real time". The user
    # explicitly called this out: "यह पुराना डिटेल है" (this is old detail).
    "real time", "realtime", "right now",
    # Application ecosystems change independently of VYOM's durable
    # project memory.  These phrases must force live evidence (for example
    # official n8n release/node documentation) instead of treating an old
    # successful procedure as current product truth.
    "what's new", "what is new", "new feature", "new features", "new node",
    "new nodes", "kya naya", "kya nayi", "kya aaya", "kya aya",
    "नया क्या", "क्या नया", "नए फीचर", "नया नोड",
)

#: Phrases a model uses to decline. VYOM never shows these before its own
#: capability resolution has actually failed.
FALSE_INABILITY_MARKERS = (
    "i cannot", "i can't", "i am unable", "i'm unable", "i do not have access",
    "i don't have access", "i am not able", "i'm not able", "as an ai",
    "i do not have the ability", "i don't have the ability",
)


def needs_fresh_evidence(goal: str) -> bool:
    lowered = goal.lower()
    return any(marker in lowered for marker in FRESHNESS_MARKERS)


def claims_inability(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in FALSE_INABILITY_MARKERS)


#: Callable contracts over the EXISTING tool registry. Each maps onto a
#: real registered tool; this is not a second tool system.
TOOL_CONTRACTS: dict[str, dict] = {
    "filesystem_list": {
        "tool": "filesystem",
        "description": "List the entries of a directory on this computer.",
        "fixed": {"action": "list"},
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Absolute directory path. Defaults to the project root."}}},
    },
    "filesystem_read": {
        "tool": "filesystem",
        "description": "Read the text content of a file on this computer.",
        "fixed": {"action": "read"},
        "parameters": {"type": "object", "required": ["path"], "properties": {
            "path": {"type": "string", "description": "Absolute file path."}}},
    },
    "filesystem_search": {
        "tool": "filesystem",
        "description": "Find files matching a glob pattern under a directory.",
        "fixed": {"action": "search"},
        "parameters": {"type": "object", "required": ["pattern"], "properties": {
            "path": {"type": "string"},
            "pattern": {"type": "string", "description": "Glob such as *.py"}}},
    },
    "terminal_execute": {
        "tool": "terminal",
        "description": (
            "Run a command-line PROGRAM in the project directory and return its real stdout, "
            "stderr and exit code. Use ONLY for genuine command-line work: git, pytest, python, "
            "npm, node, cargo, ffmpeg. The program is executed directly - shell operators "
            "(pipes, redirection, chaining) are not available, and shell hosts such as "
            "powershell or cmd must never be used here. To open an application, read a file, "
            "list a directory, or inspect this machine, use the dedicated capability instead: "
            "those have native implementations and a shell command for them will be rejected."),
        "parameters": {"type": "object", "required": ["command"], "properties": {
            "command": {"type": "string",
                        "description": "The program and its arguments, e.g. 'git status' or "
                                       "'python -m pytest tests'. No pipes or redirection."}}},
    },
    "system_info": {
        "tool": "system",
        "description": (
            "Read this machine's live state directly from the operating system: running "
            "processes with their memory and CPU, disk volumes, the clock, or the Python "
            "installation. Use this instead of running any command for these questions."),
        "parameters": {"type": "object", "required": ["action"], "properties": {
            "action": {"type": "string",
                       "enum": ["processes", "disks", "clock", "interpreter", "which", "status"]},
            "sort_by": {"type": "string", "enum": ["memory", "cpu"]},
            "target": {"type": "string", "description": "Program name, for action=which."}}},
    },
    "desktop_close": {
        "tool": "desktop",
        "description": (
            "Close a running application the user can see, by its registered id. Verified "
            "against the real process table. Never run a command to end a program."),
        "fixed": {"action": "app_close"},
        "parameters": {"type": "object", "required": ["app_id"], "properties": {
            "app_id": {"type": "string"}}},
    },
    "desktop_active_window": {
        "tool": "desktop",
        "description": "Report the window the user is currently looking at, read fresh from the OS.",
        "fixed": {"action": "active_window"},
        "parameters": {"type": "object", "properties": {}},
    },
    "browser_navigate": {
        "tool": "browser",
        "description": (
            "Fetch a URL in a HEADLESS background browser to READ its content. The user cannot "
            "see this window. Use it to gather information, never to show the user a page."),
        "fixed": {"action": "open"},
        "parameters": {"type": "object", "required": ["url"], "properties": {
            "url": {"type": "string", "description": "Absolute http or https URL."}}},
    },
    "browser_read": {
        "tool": "browser",
        "description": "Read the visible text of the page currently open in the browser.",
        "fixed": {"action": "read"},
        "parameters": {"type": "object", "properties": {}},
    },
    "desktop_launch": {
        "tool": "desktop",
        "description": (
            "Launch an installed desktop application THE USER CAN SEE, by its registered id: "
            "calculator, chrome, notepad, paint, file_explorer, terminal, vscode. "
            "For chrome you may pass `url` to open a page in the user's real visible browser. "
            "ALWAYS use this - not browser_navigate - when the user asks to open a browser, "
            "show them a site, or work in a page they want to watch."),
        "fixed": {"action": "app_open"},
        "parameters": {"type": "object", "required": ["app_id"], "properties": {
            "app_id": {"type": "string"},
            "url": {"type": "string", "description": "Optional page to open in the visible browser."}}},
    },
    "desktop_status": {
        "tool": "desktop",
        "description": "Report this computer's live system status: CPU, memory and disk.",
        "fixed": {"action": "status"},
        "parameters": {"type": "object", "properties": {}},
    },
    "desktop_window_list": {
        "tool": "desktop",
        "description": "List the windows currently open on this computer.",
        "fixed": {"action": "window_list"},
        "parameters": {"type": "object", "properties": {}},
    },
    "browser_tabs": {
        "tool": "desktop",
        "description": (
            "List the tabs currently open in the user's VISIBLE browser window(s), with "
            "titles. Read-only observation; use it before acting on 'the YouTube tab' "
            "or similar references."),
        "fixed": {"action": "browser_tabs"},
        "parameters": {"type": "object", "properties": {}},
    },
    "browser_media_state": {
        "tool": "desktop",
        "description": (
            "Read whether audio/video is ACTUALLY playing in the user's visible browser. "
            "Returns the browser tab or player-control evidence. Use this after any request "
            "to play a song or video; opening a page is not playback."),
        "fixed": {"action": "browser_media_state"},
        "parameters": {"type": "object", "properties": {}},
    },
    "browser_open_profile": {
        "tool": "desktop",
        "description": (
            "Open a named signed-in Chrome PROFILE in a window the user can see. The "
            "profile name is matched semantically against the profiles installed on "
            "this PC. Use this - not a generic Chrome launch - when the user names a "
            "profile, account or persona. Optionally also open a URL in that profile."),
        "fixed": {"action": "browser_open_profile"},
        "parameters": {"type": "object", "required": ["profile"], "properties": {
            "profile": {"type": "string",
                        "description": "Profile name, account or directory as the user said it."},
            "url": {"type": "string", "description": "Optional page to open in that profile."}}},
    },
    "browser_close_tab": {
        "tool": "desktop",
        "description": (
            "Close ONE named TAB in the user's visible browser, keeping the browser "
            "itself running. Give a word from the tab's title, e.g. 'youtube'."),
        "fixed": {"action": "browser_close_tab"},
        "parameters": {"type": "object", "required": ["target"], "properties": {
            "target": {"type": "string", "description": "A word from the tab title, e.g. 'youtube'."}}},
    },
    "browser_open_tab": {
        "tool": "desktop",
        "description": (
            "Open a NEW TAB in the browser window the user is already using - NOT a "
            "new browser window. Use whenever the user says 'new tab' or is working "
            "in an already-open Chrome. Pass the url to load; a site name "
            "(youtube, gmail) is accepted and resolved."),
        "fixed": {"action": "browser_open_tab"},
        "parameters": {"type": "object", "required": ["url"], "properties": {
            "url": {"type": "string", "description": "URL or well-known site name for the new tab."}}},
    },
    "browser_page_click": {
        "tool": "desktop",
        "description": (
            "Click a named LINK or BUTTON on the page the user is looking at, "
            "through Windows UI Automation (elements found by name, not pixels)."),
        "fixed": {"action": "browser_page_click"},
        "parameters": {"type": "object", "required": ["target"], "properties": {
            "target": {"type": "string", "description": "The link/button's visible name."}}},
    },
    "browser_first_result": {
        "tool": "desktop",
        "description": (
            "Open the FIRST RESULT on the current page (first substantial content "
            "link, skipping browser navigation chrome). Use after a search."),
        "fixed": {"action": "browser_first_result"},
        "parameters": {"type": "object", "properties": {}},
    },
    "browser_page_type": {
        "tool": "desktop",
        "description": (
            "TYPE text into the visible page's search/entry field (or the address "
            "bar if the page has no field). Presses Enter unless told not to."),
        "fixed": {"action": "browser_page_type"},
        "parameters": {"type": "object", "required": ["value"], "properties": {
            "value": {"type": "string", "description": "The text to type."},
            "enter": {"type": "boolean", "description": "Press Enter after typing (default true)."},
            "field": {"type": "string", "description": "Optional field name to prefer."}}},
    },
    "browser_page_scroll": {
        "tool": "desktop",
        "description": "Scroll the page the user is looking at, up or down.",
        "fixed": {"action": "browser_page_scroll"},
        "parameters": {"type": "object", "properties": {
            "direction": {"type": "string", "enum": ["down", "up"]},
            "times": {"type": "integer", "description": "Page-down presses (default 3)."}}},
    },
    "browser_page_read": {
        "tool": "desktop",
        "description": (
            "Read what is on the page the user is looking at: its title and named "
            "links/buttons/fields, directly from the accessibility tree."),
        "fixed": {"action": "browser_page_read"},
        "parameters": {"type": "object", "properties": {}},
    },
    "desktop_ui_inspect": {
        "tool": "desktop",
        "description": (
            "Read the UI elements (buttons, fields, values) of a window through "
            "Windows accessibility. Use this to find what to click or read in the "
            "application the user is looking at - not a directory listing."),
        "fixed": {"action": "inspect_ui_tree"},
        "parameters": {"type": "object", "properties": {
            "app_id": {"type": "string"},
            "title": {"type": "string", "description": "Part of the window title, if known."}}},
    },
    "memory_search": {
        "tool": "__memory__", "description": (
            "Answer a question from what VYOM knows. For a person, company, project or past "
            "event, search VYOM's stored memories. For a general-knowledge question about the "
            "world ('what is X', 'who is X', 'find out about X and remember it'), answer from "
            "VYOM's own knowledge base FIRST and, when a topic is unknown or stale, run web "
            "research and record what you learn, so the answer is learned for next time. "
            "Returns an empty result when nothing is known and research could not find "
            "anything - say so plainly rather than guessing."),
        "parameters": {"type": "object", "required": ["query"], "properties": {
            "query": {"type": "string", "description": "Person, company, project, event, or a world-knowledge subject."}}},
    },
    "git_status": {
        "tool": "git",
        "description": "Report the Git status of the project.",
        "fixed": {"action": "status"},
        "parameters": {"type": "object", "properties": {"cwd": {"type": "string"}}},
    },
    "git_diff": {
        "tool": "git",
        "description": "Return the Git diff of the project working tree.",
        "fixed": {"action": "diff"},
        "parameters": {"type": "object", "properties": {"cwd": {"type": "string"}}},
    },
}

#: Keyword hints used to retrieve a RELEVANT subset. Sending every
#: contract on every call wastes tokens and dilutes the choice.
_CONTRACT_HINTS = {
    "filesystem_list": ("file", "files", "folder", "directory", "project", "list", "dikha", "repo"),
    "filesystem_read": ("read", "content", "inspect", "code", "padh"),
    "filesystem_search": ("find", "search", "locate", "dhoond"),
    # Terminal is offered for GENUINE command-line work only. "powershell"
    # and "version" were hints here, so asking about a version or naming a
    # shell put the terminal at the top of the shortlist for questions that
    # have direct native answers - which is how the shell became the
    # first tool VYOM reached for.
    "terminal_execute": ("test", "tests", "pytest", "build", "compile", "git", "npm",
                         "cargo", "ffmpeg", "script", "commit", "branch", "lint"),
    "system_info": ("cpu", "ram", "memory", "disk", "space", "storage", "process",
                    "processes", "version", "installed", "python", "node", "time",
                    "date", "clock", "slow", "performance", "kaunsa", "konsa"),
    "desktop_close": ("close", "band", "quit", "exit", "shut"),
    "desktop_active_window": ("window", "screen", "active", "foreground", "open hai", "front"),
    "browser_navigate": ("browse", "web", "internet", "site", "url", "search", "research",
                         "latest", "news", "update", "review", "price", "compare", "google",
                         "go to", "visit", "open website"),
    "browser_read": ("browse", "web", "research", "extract", "source", "review", "latest"),
    "desktop_launch": ("open", "launch", "start", "kholo", "chalu", "app", "application",
                       "chrome", "calculator", "notepad", "explorer", "vscode"),
    "desktop_status": ("slow", "performance", "cpu", "memory", "ram", "disk", "system", "pc"),
    "desktop_window_list": ("window", "windows", "screen"),
    # The deterministic path already executes profile/tab/UIA goals; these
    # hints make the SAME capabilities reachable when the request arrives in
    # wording only the general planner can interpret. Without them, a
    # profile request fell back to a generic Chrome launch and a screen
    # question to a filesystem listing - the capabilities existed but were
    # invisible to the planner (NOT_WIRED, in ledger terms).
    "browser_open_profile": ("profile", "profiles", "account", "persona",
                             "prоfail", "प्रोफाइल"),
    "browser_close_tab": ("tab", "tabs", "टैब"),
    "browser_tabs": ("tab", "tabs", "टैब"),
    "browser_open_tab": ("new tab", "naya tab", "nayi tab", "नई टैब", "न्यू टैब", "टैब"),
    "browser_page_click": ("click", "dabao", "दबाओ", "link", "kholo result", "button"),
    "browser_first_result": ("first result", "pehla result", "pahla result"),
    "browser_page_type": ("likho", "type", "लिखो", "टाइप", "search box", "box me", "enter"),
    "browser_page_scroll": ("scroll", "स्क्रॉल", "neeche", "upar scroll"),
    "browser_page_read": ("page pe kya", "on the page", "page me kya", "is page", "page dikh"),
    "desktop_ui_inspect": ("click", "button", "element", "control", "checkbox", "box me",
                           "type karo", "likho", "dabao", "press"),
    "git_status": ("git", "repo", "repository", "branch"),
    "memory_search": ("remember", "remembered", "recall", "yaad", "know about", "who is",
                      "kaun hai", "kab mila", "told you", "last time", "previously", "my crm",
                      "my client", "my project notes",
                      # General-knowledge cues: the knowledge base answers these first and
                      # researches + records an unknown world topic, so "what is X / who is
                      # X / find out about X and remember it" actually learns instead of
                      # hitting a raw memory search that knows nothing in the world.
                      "what is", "what are", "what was", "who was", "define", "definition",
                      "explain", "meaning of", "what does", "find out", "learn about",
                      "facts about", "history", "wikipedia", "details about"),
    "git_diff": ("diff", "changed", "changes", "git"),
}


#: Utterances that ask nothing of the machine. These must never become a
#: tool mission: routing them through the planner is what made VYOM run
#: system-status calls for "good, what about you?" and reply with a CPU
#: card instead of a sentence.
_CONVERSATIONAL_PATTERNS = (
    "how are you", "what about you", "who are you", "what can you do",
    "thank", "thanks", "good morning", "good evening", "good night",
    "kaise ho", "kya haal", "tum kaun ho", "kya kar sakte ho",
    "nice", "great", "cool", "okay", "hmm",
)
#: Meta-commentary ABOUT the conversation itself ("I'm not saying
#: everything that stays on topic", "main topic") is small talk about
#: how the user is talking, not a request for VYOM to do anything - but
#: it commonly runs past _MAX_CONVERSATIONAL_WORDS (real sentences
#: about a topic are rarely under 7 words) and has no action verb
#: either, so without this it fell through to the tool-calling mission,
#: where the model itself hallucinated an unrelated memory_search call
#: ("मैं सारी बातें नहीं बोल रहा हूं जो मेन टॉपिक रहते हैं" ->
#: memory_search(query="Our solar system")) - a real production bug.
_META_CONVERSATIONAL_PATTERNS = (
    "main topic", "mein topic", "मेन टॉपिक", "मुख्य विषय",
    "topic pe", "topic par", "on topic", "off topic",
)
#: A goal this short with no verb is almost always conversational filler.
_MAX_CONVERSATIONAL_WORDS = 7


def is_conversational(goal: str) -> bool:
    lowered = goal.strip().lower().rstrip("?.!")
    if not lowered:
        return True
    # A question about the world the machine can SEE is never small talk -
    # "Screen pe abhi kya hai?" has no action verb, so the word-count rule
    # below called it conversation and it was answered by a model from
    # memory, with no window ever read. Fresh-evidence questions keep the
    # mission path (or the deterministic screen intent).
    from app.runtime.task_classifier import is_screen_question

    if is_screen_question(goal):
        return False
    # A general-knowledge question ('what is X', 'who is X', 'find out about
    # X and remember it') is not small talk either. It must reach the
    # knowledge-base-first-then-research flow, not be answered from a model
    # or a raw memory search that knows nothing in the world.
    from app.runtime.task_classifier import is_general_knowledge_query

    if is_general_knowledge_query(goal):
        return False
    if any(pattern in lowered for pattern in _CONVERSATIONAL_PATTERNS):
        return True
    if any(pattern in lowered for pattern in _META_CONVERSATIONAL_PATTERNS):
        return True
    # Short utterance with no actionable verb anywhere.
    action_words = (
        "open", "close", "run", "show", "list", "read", "find", "search", "check",
        "create", "delete", "inspect", "research", "browse", "test", "build", "fix",
        "install", "start", "stop", "kholo", "chala", "dikha", "band", "bana", "padh",
    )
    if len(lowered.split()) <= _MAX_CONVERSATIONAL_WORDS and not any(
        word in lowered for word in action_words
    ):
        return True
    return False


class GeneralPlanner:
    """Chooses the next REAL action for a goal the classifier did not
    recognise, using the live tool registry as callable contracts.

    Prose is never accepted as the answer to an actionable goal - a
    text-only reply is treated as a refusal to act and reported as such."""

    SYSTEM_INSTRUCTION = (
        "You are VYOM — Gunjan's personal AI chief of staff, running natively on his Windows computer. "
        "You have REAL tools listed as callable functions — use them to actually do the work. "
        "You are not a generic chatbot. You are specifically built for Gunjan: you know his business, "
        "routines, goals, and preferences. You speak Hinglish naturally when appropriate. "
        "Personality: direct, fast, proactive, loyal. You work faster than human speed. "
        "EXECUTION RULES:\n"
        "1. To satisfy the goal you MUST call tools. Never reply with instructions telling "
        "Gunjan how to do it himself — you are the one doing it.\n"
        "2. Never claim you cannot browse, read files, run code, or control the computer. "
        "Your tools do exactly those things.\n"
        "3. Never invent facts, companies, prices, versions or results. If you do not know "
        "something, call a tool to find out. If a tool cannot verify it, say plainly that it "
        "could not be verified.\n"
        "4. Work one step at a time. After each tool result, decide the next step from what you "
        "actually observed.\n"
        "5. When the goal is genuinely satisfied, reply with a short direct summary of what "
        "you did and what you found. Match Gunjan's language — Hindi question = Hindi/Hinglish answer.\n"
        "6. If Gunjan is about to do something risky or wrong, say it ONCE briefly, then execute "
        "what he asked. Never lecture. Never delay the work.\n"
        "7. Prefer the smallest number of steps that truly answers the goal."
    )

    def __init__(self, model_router, providers, *, max_tools: int = 8, provider_health=None):
        self.model_router = model_router
        self.providers = providers
        self.max_tools = max_tools
        # Shared with the Task Runtime so one 429 stops every caller, not
        # just the mission that happened to receive it.
        self.provider_health = provider_health

    #: Contracts that change the user's visible world. These are only
    #: offered when the utterance is an actual action request - the
    #: 2026-08-19 physical session had a COMPLAINT ("I cannot show on the
    #: calculator this is clear") answered by launching Calculator, and a
    #: descriptive fragment ("jo Chrome profile open hai...") answered by
    #: opening a profile. Intelligence is not permission to act: a goal
    #: with no imperative can ground itself by OBSERVING, never by
    #: changing the desktop.
    EFFECT_CONTRACTS = frozenset({
        "desktop_launch", "desktop_close", "browser_open_profile",
        "browser_close_tab", "browser_open_tab", "terminal_execute",
        "browser_page_click", "browser_first_result", "browser_page_type",
        "browser_page_scroll",
    })

    def relevant_tools(self, goal: str) -> list:
        """Retrieve only the contracts plausibly relevant to this goal."""
        from app.providers.base import ToolSchema
        from app.runtime.task_classifier import requests_external_action

        action_requested = requests_external_action(goal)

        lowered = goal.lower()
        scored: list[tuple[int, str]] = []
        for name, hints in _CONTRACT_HINTS.items():
            score = sum(1 for hint in hints if hint in lowered)
            if score:
                scored.append((score, name))
        chosen = [name for _, name in sorted(scored, key=lambda pair: pair[0], reverse=True)][: self.max_tools]
        if not action_requested:
            chosen = [name for name in chosen if name not in self.EFFECT_CONTRACTS]
        if not chosen:
            # Unknown shape of request: the planner still investigates
            # instead of giving up - but investigation starts by LOOKING AT
            # THE WORLD (foreground window, open windows, own memory), not
            # by listing the repository or by changing anything. filesystem_list
            # used to sit in this default set, which is how a request about
            # the user's screen was answered with 'VYOM Project contains 38
            # top-level entries'.
            chosen = ["desktop_active_window", "desktop_window_list",
                      "memory_search", "browser_read"]
        return [
            ToolSchema(
                name=name,
                description=TOOL_CONTRACTS[name]["description"],
                parameters=TOOL_CONTRACTS[name]["parameters"],
            )
            for name in chosen
        ]

    async def next_action(self, goal: str, history: list[dict], tools: list):
        """Ask the model for the next structured action given what has
        actually been observed so far."""
        from app.providers.base import ProviderRequest
        from app.schemas.tasks import Task, TaskCreate, TaskProfile

        task = Task.from_create(TaskCreate(user_request=goal))
        profile = TaskProfile(domain=task.domain, complexity=4, deterministic=False,
                              intent="general_planning")
        decision = await self.model_router.route(task, profile)
        # The primary model may have no quota left. Its SIBLINGS usually
        # do - Google meters the free tier per model per day - so the
        # planner walks the routed fallback chain instead of abandoning
        # the mission. Without this, one exhausted model made every
        # non-deterministic request fail with "the reasoning provider is
        # rate limited", which is what the user hit repeatedly.
        return await self._call_with_fallback(decision, goal, request_profile=profile,
                                              tools=tools, history=history)

    async def _call_with_fallback(self, decision, goal, *, request_profile, tools, history):
        from app.providers.base import ProviderRateLimitError, ProviderRequest

        candidates = [(decision.primary_provider, decision.primary_model)]
        for model_id in decision.fallback_models:
            definition = getattr(self.model_router, "registry", None)
            provider_name = decision.primary_provider
            if definition is not None:
                record = definition.get(model_id)
                if record is not None:
                    provider_name = record.provider
            candidates.append((provider_name, model_id))

        last_error: Exception | None = None
        for provider_name, model_id in candidates:
            provider = self.providers.get(provider_name)
            if provider is None or not provider.configured:
                continue
            if self.provider_health is not None and self.provider_health.rate_limited(
                provider_name, model_id
            ):
                continue
            if not provider.supports_tool_calls:
                continue
            try:
                if self.provider_health is None:
                    response = await provider.generate_with_tools(
                        ProviderRequest(model=model_id, user_request=goal,
                                        system_instruction=self.SYSTEM_INSTRUCTION,
                                        profile=request_profile),
                        tools, history,
                    )
                else:
                    # Bounded concurrency per model, then RE-CHECK inside
                    # the slot. Twenty simultaneous missions all found the
                    # circuit closed and all hit the same exhausted model;
                    # queuing behind a small budget means the ones that
                    # waited see the 429 that has since been recorded.
                    async with self.provider_health.slot(provider_name, model_id):
                        if self.provider_health.rate_limited(provider_name, model_id):
                            continue
                        response = await provider.generate_with_tools(
                            ProviderRequest(model=model_id, user_request=goal,
                                            system_instruction=self.SYSTEM_INSTRUCTION,
                                            profile=request_profile),
                            tools, history,
                        )
            except ProviderRateLimitError as error:
                last_error = error
                if self.provider_health is not None:
                    self.provider_health.record_rate_limit(
                        provider_name, model_id,
                        daily_quota=getattr(error, "daily_quota", False))
                continue  # try the next model rather than failing the mission
            if self.provider_health is not None:
                self.provider_health.record_success(provider_name, model_id)
            return response

        if last_error is not None:
            raise last_error
        raise RuntimeError(
            "No configured model with remaining quota can make structured tool calls")

    async def _legacy_single_model_call(self, goal: str, history: list[dict], tools: list):
        """Retained for callers that pin one model explicitly."""
        from app.providers.base import ProviderRequest
        from app.schemas.tasks import Task, TaskCreate, TaskProfile

        task = Task.from_create(TaskCreate(user_request=goal))
        profile = TaskProfile(domain=task.domain, complexity=4, deterministic=False,
                              intent="general_planning")
        decision = await self.model_router.route(task, profile)
        provider = self.providers.get(decision.primary_provider)
        if provider is None or not provider.configured:
            raise RuntimeError(f"Planning provider '{decision.primary_provider}' is not configured")
        # Honour the circuit breaker BEFORE spending a request. Calling a
        # provider that has already returned 429 cannot succeed; it only
        # deepens the rate limit and delays the honest failure.
        if self.provider_health is not None and self.provider_health.rate_limited(
            decision.primary_provider, decision.primary_model
        ):
            from app.providers.base import ProviderRateLimitError

            remaining = self.provider_health.cooldown_remaining(
                decision.primary_provider, decision.primary_model)
            raise ProviderRateLimitError(
                f"'{decision.primary_model}' has no remaining quota for another {remaining:.0f}s")
        if not provider.supports_tool_calls:
            raise RuntimeError(
                f"Model '{decision.primary_model}' cannot make structured tool calls; VYOM will "
                "not answer an actionable request from model text alone")
        request = ProviderRequest(
            model=decision.primary_model,
            user_request=goal,
            system_instruction=self.SYSTEM_INSTRUCTION,
            profile=profile,
        )
        from app.providers.base import ProviderRateLimitError

        try:
            return await provider.generate_with_tools(request, tools, history)
        except ProviderRateLimitError as error:
            # Open the circuit immediately so no other mission, and no
            # later step of this one, spends another request against this
            # model. Scoped to the MODEL: a sibling with its own quota
            # stays available for the router to fall back to.
            if self.provider_health is not None:
                self.provider_health.record_rate_limit(
                    decision.primary_provider, decision.primary_model,
                    daily_quota=getattr(error, "daily_quota", False),
                )
            raise
