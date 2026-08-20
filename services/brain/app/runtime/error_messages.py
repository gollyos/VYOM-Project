"""Human-facing failure messages.

A raw exception string ("Google tool request failed with HTTP 503: {...}")
was being written straight into the response the user hears and reads.
`task.error` still keeps the exact diagnostic text for logs, evidence, and
this module's own matching - only the copy sent outward is humanised.

Deterministic pattern matching, not a model call: a failure explanation
must never depend on the same provider that just failed.
"""
from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(429|rate limit)\b", re.I),
     "The model provider is rate-limited right now. Please try again in a moment."),
    (re.compile(r"\b(503|UNAVAILABLE|502|504)\b", re.I),
     "The model provider is temporarily unavailable. Please try again shortly."),
    (re.compile(r"\bthought_signature\b", re.I),
     "The reasoning provider rejected the request format. Retrying should resolve it."),
    (re.compile(r"\b(timed? ?out|timeout)\b", re.I),
     "That took too long and was stopped. Please try again."),
    (re.compile(r"credentials are not configured|not configured", re.I),
     "That capability is not configured yet."),
    (re.compile(r"is not a registered capability", re.I),
     "VYOM does not have a tool for that yet."),
    (re.compile(r"postcondition failed|effect was not observed", re.I),
     "That did not visibly complete, so it was not marked done."),
    (re.compile(r"model-call limit reached|step limit reached|tool-call limit reached", re.I),
     "That request needed more steps than are allowed and was stopped safely."),
    (re.compile(r"requires (L\d) approval|requires explicit approval", re.I),
     "That action needs your approval before VYOM can do it."),
]


# ======================================================================
# Observation rendering
# ======================================================================
#
# A tool payload is not an answer. These were spoken to the user verbatim:
#
#   {'app_id': 'chrome', 'running': True, 'pid': 22276,
#    'window_title': 'Untitled - Google Chrome', 'target': 'https://...'}
#   {'window': {'title': 'New Tab - Google Chrome', 'process_id': 22276,
#    'handle': 4915714, 'focused': True}}
#
# The runtime knew exactly what happened; it just read out its own
# bookkeeping. Pids, handles, class names and absolute paths stay in the
# evidence panel and the logs - they never reach speech.

#: Keys that are internal bookkeeping and must never be narrated.
_INTERNAL_KEYS = frozenset({
    "pid", "process_id", "handle", "hwnd", "window_id", "class_name",
    "display_id", "correlation_id", "task_id", "request_id", "app_id",
})


def _tidy_target(value: str) -> str:
    """A URL the user can recognise, not a full query string."""
    text = str(value or "").strip()
    text = re.sub(r"^https?://(www\.)?", "", text)
    return text.split("?")[0].rstrip("/") or text


def humanise_observation(output) -> str:
    """Render a capability's structured result as a plain sentence."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, list):
        if not output:
            return "Nothing was found."
        titles = [
            str(item.get("title") or item.get("name") or item.get("summary") or "")[:90]
            for item in output if isinstance(item, dict)
        ]
        titles = [title for title in titles if title]
        if titles:
            head = "; ".join(titles[:3])
            more = f" (and {len(titles) - 3} more)" if len(titles) > 3 else ""
            return f"{head}{more}"
        return f"{len(output)} result(s)."
    if not isinstance(output, dict):
        return str(output)

    # -- an application's run state ------------------------------------
    if "running" in output and ("window_title" in output or "target" in output):
        name = str(output.get("app_id") or "The application").replace("_", " ").title()
        if not output.get("running"):
            return f"{name} is not running."
        target = output.get("target") or output.get("url")
        if target:
            return f"{name} is open at {_tidy_target(target)}."
        title = output.get("window_title")
        return f"{name} is open{f' — {title}' if title else ''}."

    # -- a closed application ------------------------------------------
    if output.get("closed") is True:
        name = str(output.get("app_id") or "It").replace("_", " ").title()
        return f"{name} is closed."

    # -- the focused window --------------------------------------------
    window = output.get("window")
    if isinstance(window, dict) and window.get("title"):
        return f"The window in front of you is {window['title']}."

    # -- every open window ---------------------------------------------
    windows = output.get("windows")
    if isinstance(windows, list) and windows:
        titles = [str(item.get("title", "")).strip() for item in windows
                  if isinstance(item, dict) and item.get("title")]
        focused = next((item.get("title") for item in windows
                        if isinstance(item, dict) and item.get("focused")), None)
        listed = ", ".join(titles[:6])
        lead = f"In front of you: {focused}. Also open: " if focused else "Open right now: "
        rest = ", ".join(title for title in titles if title != focused)[:400]
        return f"{lead}{rest}." if focused else f"{lead}{listed}."

    # -- a browser profile ---------------------------------------------
    profile = output.get("profile")
    if isinstance(profile, dict) and profile.get("name"):
        account = f" ({profile['account']})" if profile.get("account") else ""
        return f"Chrome is open in the {profile['name']} profile{account}."

    # -- a directory listing -------------------------------------------
    if "entries" in output and isinstance(output["entries"], list):
        folder = str(output.get("path", "")).replace("\\", "/").rstrip("/").split("/")[-1]
        return f"{len(output['entries'])} item(s) in {folder or 'that folder'}."

    # -- anything else: a readable field list, internals removed -------
    parts = [
        f"{key.replace('_', ' ')}: {value}"
        for key, value in output.items()
        if key not in _INTERNAL_KEYS
        and isinstance(value, (str, int, float, bool))
        and str(value).strip()
    ]
    return "; ".join(parts[:5]) if parts else "Done."


def humanize_error(raw: str) -> str:
    """Map a raw exception string to a short, honest, user-facing sentence.

    Falls back to a generic message rather than ever surfacing provider
    payloads, stack traces, or internal identifiers verbatim."""
    text = (raw or "").strip()
    for pattern, message in _PATTERNS:
        if pattern.search(text):
            return message
    # Strip anything that looks like a raw HTTP/JSON provider dump before
    # falling back, so an unmatched case still never leaks internals.
    if "{" in text or "HTTP" in text or len(text) > 160:
        return "That request could not be completed. Please try again."
    return text or "That request could not be completed."


# ======================================================================
# Response-boundary sanitisation
# ======================================================================
#
# The LAST line of defence, not the first. Individual engines build
# semantic sentences, but every completion path funnels through
# TaskRuntime._finish_result - so THAT is where the invariant is enforced
# structurally: whatever any code anywhere produced, the text the user
# reads and hears contains no raw Python dict, no pid narration, no
# internal absolute path. The originals stay in structured_data, evidence
# and the logs for diagnostics.

_PID_NARRATION = re.compile(r"\s*\(?\bpid[= :]+\d+\)?", re.I)
_INTERNAL_PATH = re.compile(
    r"\b[A-Za-z]:\\[^\s'\"]*?(?:vyom project|services[\\/]brain|src-tauri|\.env)[^\s'\"]*",
    re.I,
)
_CONTAINER_REPR = re.compile(r"^\s*[\[{].*[\]}]\s*$", re.DOTALL)


def sanitise_user_response(text: str) -> str:
    """Return text safe for the user to read and hear.

    1. A whole-string dict/list repr is rendered semantically (the
       structure is known - narrate its meaning, not its syntax).
    2. Pid narration is removed; internal absolute paths collapse to
       their file name.
    """
    if not text:
        return text
    cleaned = text.strip()

    if _CONTAINER_REPR.match(cleaned):
        import ast

        try:
            parsed = ast.literal_eval(cleaned)
        except (ValueError, SyntaxError):
            parsed = None
        rendered = humanise_observation(parsed) if parsed is not None else ""
        cleaned = rendered or "Done — the details are on the result panel."

    cleaned = _PID_NARRATION.sub("", cleaned)
    cleaned = _INTERNAL_PATH.sub(lambda m: m.group(0).replace("\\", "/").split("/")[-1], cleaned)
    return cleaned.strip() or "Done."
