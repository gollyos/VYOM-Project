from __future__ import annotations

from app.schemas.tasks import Task

from .schemas import MemoryEntry, MemoryProvenance, MemoryType, ProvenanceType, VerificationState


#: Intents whose outcome is TRANSIENT. Opening an app, closing a tab,
#: reading the window list or acknowledging a stop are facts about a
#: moment, not durable knowledge. Writing them to long-term memory is
#: what filled the store with hundreds of "Completed: ..." records at
#: confidence 1.0 - which then came back as retrieval hits and were
#: replayed to the user as current truth. "यह क्या है?" was answered from
#: this sediment instead of from the screen observation taken 20 seconds
#: earlier, and a fixture-era research result was still being quoted as
#: fact months later.
_TRANSIENT_INTENTS = frozenset({
    "close_everything", "daily_status", "explain_routing",
    "app_launch", "app_close", "browser_tab_close", "browser_profile_open",
    "recover_visibility", "screen_observe", "window_list", "active_window",
    "settings_open", "system_query", "runtime_introspection", "ui_interact",
    "filesystem_list", "memory_lookup",
})

#: A response that is a serialised structure is a tool payload, not
#: knowledge. These were being stored verbatim and read back aloud.
_RAW_PAYLOAD_PREFIXES = ("{'", '{"', "[{'", '[{"', "[]", "{}")

#: Text that marks a result as synthetic. It must never enter durable
#: memory, because retrieval cannot tell fixture text from fact.
_FIXTURE_MARKERS = (
    "local fixture", "placeholder result", "no live network call",
    "mock provider", "sample data", "lorem ipsum",
)


class MemoryConsolidator:
    """Creates durable operational summaries, never raw traces or hidden reasoning."""

    def from_verified_task(self, task: Task) -> list[MemoryEntry]:
        if not task.result or not task.verification or not task.verification.passed:
            return []
        intent = task.profile.intent if task.profile else None
        if intent in _TRANSIENT_INTENTS:
            return []
        if task.metadata.get("kernel_interrupt"):
            return []

        response = (task.result.response or "").strip()
        if not response:
            return []
        # A raw tool payload is not knowledge.
        if response.startswith(_RAW_PAYLOAD_PREFIXES):
            return []
        # Synthetic content must never become durable fact.
        lowered = response.lower()
        if any(marker in lowered for marker in _FIXTURE_MARKERS):
            return []
        # A goal that was not verified in the world has nothing to teach.
        if (task.metadata.get("goal_verification") or {}).get("status") in {"FAILED", "PARTIAL"}:
            return []

        return [MemoryEntry(
            type=MemoryType.EPISODIC,
            title=f"Completed: {task.goal[:120]}",
            content=task.result.response,
            summary=task.result.response[:500],
            task_id=task.id,
            importance=0.55,
            confidence=task.verification.score,
            verification_state=VerificationState.VERIFIED,
            provenance=[MemoryProvenance(type=ProvenanceType.TASK_RESULT, task_id=task.id, reference=task.verification.summary)],
            tags=[task.domain.value, "verified-task"],
        )]


# ======================================================================
# Conversational fact capture
# ======================================================================
#
# The user said "मेरा नाम है गुंजन" at 10:03:47 and VYOM answered "I have
# no access to your personal information" at 10:05:02 - 75 seconds later.
# Nothing a user states in conversation was ever written to memory, so
# every turn started from zero.
#
# This extracts durable facts DETERMINISTICALLY (no model call) and writes
# them through the existing MemoryStore. It captures identity, business
# and preference statements only - not small talk, not questions, and
# never a guess.

import re as _re

# SENTENCE BOUNDARIES ARE REAL BOUNDARIES.
#
# The Devanagari value ranges used to span the whole block, which
# CONTAINS the danda । (U+0964) and double danda ॥ (U+0965). Both were
# therefore legal "value"
# characters, so a capture ran straight through the end of the sentence
# and stopped only when it hit its own length ceiling, in the middle of
# the next word. This is exactly what the user's live session recorded:
#
#   said : "मेरा नाम है गुंजन शाह। मेरा जो वेबसाइट है वह है लक्सोरा डिजाइंस।स्पेस ..."
#   wrote: User name = "गुंजन शाह। मेरा जो वेबसाइट है वह है लक्स"   (40 chars)
#
# Two separate facts fused into one slot and truncated mid-token. The
# range below stops short of the danda and resumes after it, so a
# sentence terminator can never be captured as part of a value.
_DEV = "ऀ-ॣ०-ॿ"

#: Clause separators. A single utterance can state several facts -
#: "Mera naam Gunjan Shah hai aur meri website test.example hai" is two
#: facts, and each must land in its own slot uncontaminated.
#: A full stop only ends a sentence when a space or the end of the
#: utterance follows it. Splitting on every "." tore "test.example" into
#: two clauses and stored the website as "test".
_CLAUSE_SPLIT = _re.compile(
    "[।॥!?;\n]+|\\.(?=\\s|$)|\\s+(?:aur|और|and)\\s+", _re.IGNORECASE)


def split_clauses(utterance: str) -> list[str]:
    """Break an utterance into independently-parseable statements."""
    return [part.strip() for part in _CLAUSE_SPLIT.split(utterance or "") if part.strip()]


#: (pattern, memory type, title template). Each group 1 is the value.
_FACT_PATTERNS: list[tuple[str, str, str]] = [
    # Identity - English and Hindi/Hinglish
    (r"\bmy name is\s+([A-Za-z\u0900-\u0963\u0966-\u097F][\w\u0900-\u0963\u0966-\u097F .'-]{1,40})", "identity", "User name"),
    (r"\bi am\s+([A-Z][\w.'-]{1,30})\b", "identity", "User name"),
    (r"मेरा नाम\s*(?:है)?\s*([\u0900-\u0963\u0966-\u097F\w .'-]{2,40})", "identity", "User name"),
    (r"\bmera naam\s*(?:hai)?\s*([\w .'-]{2,40})", "identity", "User name"),
    # Business / company / website
    (r"\bmy (?:business|company|startup) is\s+([\w\u0900-\u0963\u0966-\u097F .'&-]{2,60})", "business", "User business"),
    (r"मेरा (?:बिजनेस|व्यवसाय|बिज़नेस)\s*(?:है)?\s*([\u0900-\u0963\u0966-\u097F\w .'&-]{2,60})", "business", "User business"),
    (r"\bmera (?:business|bijness|bijnes)\s*(?:hai)?\s*([\w .'&-]{2,60})", "business", "User business"),
    # "business ka naam Beta hai" - the natural Hinglish way to state or
    # CORRECT a business name. Its absence is why "Nahi, business ka naam
    # Beta hai" wrote nothing at all, while the model still replied that
    # it had updated the record.
    (r"\b(?:business|company|startup|firm)\s+(?:ka|ke|ki)\s+naam\s+([\wऀ-ॣ०-ॿ .'&-]{2,60})",
     "business", "User business"),
    (r"(?:बिजनेस|व्यवसाय|कंपनी)\s+का\s+नाम\s+([ऀ-ॣ०-ॿ\w .'&-]{2,60})",
     "business", "User business"),
    (r"\bmy website is\s+([\w\s.:/-]{4,80})", "business", "User website"),
    (r"मेरी वेबसाइट\s*(?:है)?\s*([\w\s.:/-]{4,80})", "business", "User website"),
    # Hinglish, which is how this user actually speaks. Without it
    # "meri website luxora-designs.example hai" wrote nothing at all.
    (r"\bmeri\s+(?:website|websites|site)\s*(?:hai)?\s*([\w\s.:/-]{4,80})",
     "business", "User website"),
    # The REPLACEMENT half of a spoken correction: "X meri website nahi
    # hai. Correct website Y hai." The new value is what becomes active.
    (r"\b(?:correct|sahi|sahee)\s+(?:website|site)\s*(?:hai|is)?\s*([\w\s.:/-]{4,80})",
     "business", "User website"),
    (r"\b(?:correct|sahi)\s+(?:naam|name)\s*(?:hai|is)?\s*([\w{_DEV} .'-]{{2,40}})".format(_DEV=_DEV),
     "identity", "User name"),
    # Stable preferences
    (r"\bi prefer\s+([\w\u0900-\u0963\u0966-\u097F .'-]{3,60})", "preference", "User preference"),
    (r"\bremember that\s+(.{5,120})", "preference", "User instruction"),
    (r"\byaad rakhna\s+(.{5,120})", "preference", "User instruction"),
    # Corrections. "wrong X, Y hai" / "galat hai, Y hai" - a plain domain-
    # or-name-shaped value after the correction cue. This exists because a
    # spoken correction ("wrong luxora design, Zoradesigns.space hai.")
    # produced a model reply CLAIMING the memory had been updated while
    # nothing was actually written - the reply was invented, not evidence.
    (r"\bwrong\b.{0,40}?([\w][\w.\-]{2,50}\.(?:space|com|in|co|design|io|org))", "business", "User website"),
    (r"(?:galat|\u0917\u093C\u0932\u0924|\u0917\u0932\u0924)\s+(?:hai|\u0939\u0948)[,.]?\s*([\w][\w.\-]{2,50}\.(?:space|com|in|co|design|io|org))",
     "business", "User website"),
]

#: Cue words marking a correction rather than a fresh statement. A
#: corrected fact must SUPERSEDE the prior entry of the same title, not
#: sit alongside it as an equally-weighted, contradictory record.
_CORRECTION_MARKERS = ("wrong", "galat", "\u0917\u093C\u0932\u0924", "\u0917\u0932\u0924", "nahi", "\u0928\u0939\u0940\u0902", "incorrect", "not correct")


def is_correction(utterance: str) -> bool:
    lowered = (utterance or "").lower()
    return any(marker in lowered for marker in _CORRECTION_MARKERS)

#: A question is never a statement of fact, however it is phrased.
_QUESTION_MARKERS = ("?", "kya hai", "क्या है", "बताओ", "batao", "tell me", "what is my", "kaun hai")


#: Hindi/Hinglish puts the copula AFTER the value: "mera naam Gunjan hai".
#: Every pattern above captures to the end of the phrase, so the verb came
#: along with it and VYOM stored the user's name as "Gunjan hai" - which is
#: then what it called them, and what any later comparison had to match.
_TRAILING_COPULA = _re.compile(
    r"\s+(?:hai|hain|he|है|हैं|is|are)\s*$", _re.IGNORECASE)


#: Tokens that are grammar, not values. A negated statement ("X meri
#: website NAHI hai") matched the same shape as an assertion and stored
#: the negation itself as the user's website.
_NON_VALUES = frozenset({
    "nahi", "nahin", "नहीं", "nai", "not", "no", "none", "hai", "है", "hain",
    "correct", "sahi", "galat", "गलत", "wrong", "kya", "क्या", "yeh", "ye", "वह", "woh",
})

# A website memory is an address, not merely the token that happened to
# follow the word "website".  The physical-mic command "meri website
# kholo" used to match the fact pattern above and persisted `kholo` as the
# user's website.  Requiring an actual dotted host/URL shape fixes the
# ownership boundary structurally: action verbs remain commands and only
# address-shaped values can enter the website slot.
_WEBSITE_VALUE = _re.compile(
    r"^(?:https?://)?(?:www\.)?[\w-]+(?:\.[\w-]+)+(?:[/:?#][^\s]*)?$",
    _re.IGNORECASE,
)


def _clean_value(raw: str) -> str:
    """Reduce a captured span to just the fact's value."""
    value = raw.strip(" .,!?।'\"")
    # Strip repeatedly: "naam Gunjan hai hai" from a stuttered transcript.
    while True:
        stripped = _TRAILING_COPULA.sub("", value).strip(" .,!?।'\"")
        if stripped == value:
            return stripped
        value = stripped


def extract_durable_facts(utterance: str) -> list[dict]:
    """Return durable facts stated in this utterance. Empty for questions,
    small talk, or anything ambiguous - VYOM stores what it was told, never
    what it inferred."""
    text = (utterance or "").strip()
    if len(text) < 6:
        return []
    lowered = text.lower()
    if any(marker in lowered for marker in _QUESTION_MARKERS):
        return []

    corrects = is_correction(text)
    facts: list[dict] = []
    # ONE CLAUSE, ONE FACT. Matching against the whole utterance let a
    # pattern anchored in the first sentence capture across the second -
    # "मेरा नाम है गुंजन शाह। मेरा जो वेबसाइट है..." wrote the name AND the
    # start of the website sentence into the name slot. Each statement is
    # now parsed on its own, so a slot can only ever hold its own value.
    for clause in split_clauses(text):
        if len(clause) < 4:
            continue
        for pattern, kind, title in _FACT_PATTERNS:
            match = _re.search(pattern, clause, _re.IGNORECASE)
            if not match:
                continue
            value = _clean_value(match.group(1))
            if not value or len(value) > 120:
                continue
            if title == "User website":
                # STT commonly inserts spaces inside a spoken domain
                # ("luxora designs . space").  Domain whitespace is not
                # semantic, so normalize it before validating/storing.
                value = _re.sub(r"\s+", "", value)
                if not _WEBSITE_VALUE.fullmatch(value):
                    continue
            if value.strip().lower() in _NON_VALUES:
                continue
            facts.append({"kind": kind, "title": title, "value": value,
                          "said": clause[:200], "correction": corrects})
    # One fact per kind: the last statement wins for the same category.
    unique: dict[str, dict] = {}
    for fact in facts:
        unique[fact["kind"] + fact["title"]] = fact
    return list(unique.values())
