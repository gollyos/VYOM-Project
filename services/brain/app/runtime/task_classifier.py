from __future__ import annotations

import re
import re as _re_module

from app.phase10.extraction import extract_symbol
from app.schemas.tasks import TaskDomain, TaskProfile


# Generic, capability-backed action intents. Every one of these is
# executed by ActionEngine through a REGISTERED tool - they are not
# phrases, they are verbs that map onto a live capability. Before this
# existed, only the ~80 exact demo phrases below reached a tool at all
# and every other request fell through to a model-only answer, which is
# why the shipped application behaved like a chatbot.
_URL = re.compile(r"https?://\S+|\bwww\.\S+\b", re.I)
_FILE_VERBS = ("list", "show", "what files", "which files", "find", "search", "read", "open", "look at", "cat")
# Concrete, nameable applications only. The generic word "browser" is
# deliberately absent: "open a browser and search for X" is one web task,
# not an application launch, and treating it as a launch target split the
# request into a meaningless "Open a browser" step with nothing to open.
_APP_WORDS = (
    "calculator", "calc", "notepad", "explorer", "file explorer", "chrome",
    "vscode", "vs code", "visual studio code", "terminal", "cmd", "powershell", "paint",
    "edge", "settings", "task manager",
)
_BROWSER_APPS = ("chrome", "browser", "edge", "firefox")


# ======================================================================
# Kernel interrupt
# ======================================================================
#
# STOP OUTRANKS EVERY MISSION.
#
# "Stop. Stop. Stop." was classified as a general request, routed to the
# general planner, spent a model call, and executed filesystem_list on
# C:\ - then read the directory back to the user as a completed task at
# verification score 1.0. The user was trying to make VYOM stop talking.
#
# Interruption is recognised HERE, before routing, before planning,
# before memory, before any capability. It is not a phrase list bolted
# onto the tool router: it is a small set of imperative stop verbs across
# the languages this user actually speaks, matched only when the
# utterance is JUST that - a bare command to stop, not a sentence that
# happens to contain the word.

#: Bare stop verbs. Multilingual, deliberately small - the discriminator
#: is the SHAPE of the utterance (a short bare imperative), not coverage
#: of every possible phrasing.
_STOP_VERBS = (
    "stop", "cancel", "halt", "abort", "quit it", "shut up", "be quiet", "enough",
    "ruko", "ruk", "ruk ja", "ruk jao", "rukiye", "bas", "bas karo", "band karo",
    "band kar", "chhodo", "chodo", "mat karo", "nahi karo", "rehne do", "rahne do",
    "रुको", "रुक जाओ", "बस", "बस करो", "बंद करो", "छोड़ो", "मत करो", "रहने दो",
    "थम जाओ", "चुप", "चुप हो जाओ",
)

#: Words that turn a stop verb into a request ABOUT something, which is a
#: normal task and must keep its ordinary route. "band karo" alone is an
#: interrupt; "Chrome band karo" is an app-close capability.
_STOP_OBJECTS = (
    "chrome", "browser", "calculator", "notepad", "app", "application", "window",
    "tab", "music", "song", "video", "edge", "explorer", "terminal", "vscode",
    "focus", "session", "timer", "everything", "all",
)


def is_interrupt_command(text: str) -> bool:
    """True when this utterance is a bare command to stop what is running.

    Bare is the whole test. "Stop." / "Stop. Stop. Stop." / "ruko" / "bas
    karo" are interrupts. "Chrome band karo" names an object and is an
    ordinary close capability. "Stop the deployment before it breaks
    production" is a sentence, not a kernel interrupt."""
    cleaned = (text or "").strip().lower()
    if not cleaned or len(cleaned) > 60:
        return False
    # Collapse the repetition a frustrated user produces: "Stop. Stop. Stop."
    cleaned = _re_module.sub(r"[.!,?।\s]+", " ", cleaned).strip()
    if not cleaned:
        return False
    words = cleaned.split()
    if len(words) > 6:
        return False
    # Naming a target makes this a normal capability request, not a kernel
    # interrupt - "Chrome band karo" must still close Chrome.
    if any(obj in words for obj in _STOP_OBJECTS):
        return False
    # Every remaining token must belong to a stop verb, so "stop stop stop"
    # and "bas ruko" qualify while "stop and open chrome" does not.
    verb_tokens = {token for verb in _STOP_VERBS for token in verb.split()}
    # Address, politeness and SELF-REFERENCE carry no target. "Cancel
    # this", "isko band karo" and "ye task stop karo" all point at the
    # work in flight, which is exactly what an interrupt means - unlike
    # "Chrome band karo", which names something in the world.
    filler = {
        "vyom", "hey", "ok", "okay", "please", "abhi", "now", "yaar", "arre", "अभी", "अरे",
        "this", "that", "it", "ise", "isko", "usko", "ye", "yeh", "current", "task",
        "kaam", "इसको", "इसे", "ये", "यह", "काम",
    }
    meaningful = [word for word in words if word not in filler]
    if not meaningful:
        return False
    return all(word in verb_tokens for word in meaningful)


# ======================================================================
# STT noise gate
# ======================================================================
#
# A physical microphone produces garbage. "guerra rua" and "novio on
# desktop my PC" were real utterances, and the runtime treated each as a
# legitimate request: a model call, a memory lookup, and a confident,
# entirely invented answer about the user's business. The honest response
# to a transcript VYOM cannot parse is to say so - at zero model cost.
#
# The test is deliberately conservative: an utterance is noise only when
# NONE of its tokens is a word a real request would contain (English or
# Hindi/Hinglish function words, command verbs, or the vocabulary of the
# capabilities themselves). Anything recognisable - even one word - keeps
# its ordinary route. False negatives (noise that slips through) merely
# reach the planner, which must ground itself in tools anyway; false
# positives (real requests rejected here) are what this set is tuned to
# avoid.

#: Words a genuine request can contain. Not a phrase list - a coverage
#: probe: if the transcript shares ZERO tokens with everything VYOM knows
#: how to hear, it is not a request yet.
_AUDIBLE_VOCABULARY = frozenset({
    # English function + question words
    "the", "a", "an", "is", "are", "was", "do", "does", "did", "can", "could",
    "you", "me", "my", "i", "we", "it", "this", "that", "what", "where", "when",
    "why", "how", "who", "which", "please", "now", "today", "open", "close",
    "launch", "start", "stop", "cancel", "find", "search", "read", "write",
    "show", "tell", "list", "play", "run", "make", "create", "delete", "move",
    "on", "in", "at", "for", "to", "from", "with", "not", "no", "yes", "ok",
    # Greetings are audible - "Hello." is a conversation opener, not noise
    # (the replay showed it falling into the re-ask gate).
    "hello", "hi", "hey", "namaste", "goodbye", "bye",
    "screen", "window", "windows", "file", "files", "folder", "directory",
    "browser", "chrome", "app", "application", "tab", "tabs", "profile",
    "song", "music", "video", "calculator", "notepad", "explorer", "terminal",
    "settings", "name", "website", "business", "memory", "remember", "task",
    "project", "code", "test", "build", "status", "system", "pc", "desktop",
    "battery", "network", "internet", "phone", "call", "message", "email",
    "calendar", "meeting", "price", "news", "latest", "update", "version",
    "client", "told", "said", "date", "ago", "history", "old",
    # Hindi/Hinglish function + command words (romanised and Devanagari)
    "kya", "kyu", "kyun", "kaise", "kaisa", "kab", "kaun", "konsa", "kaunsa",
    "kholo", "khol", "kholo", "khol", "kholiye", "band", "karo", "kar", "karo",
    "kijiye", "chala", "chalao", "bajao", "baja", "dekho", "dikhao", "dikh",
    "hai", "hain", "nahi", "nahin", "mera", "meri", "mere", "me", "mein", "se",
    "ko", "ki", "ka", "ke", "naam", "kaam", "abhi", "bas", "ruko", "chhodo",
    "bataya", "bola", "yaad", "purana", "tareekh", "tarikh",
    "wala", "wale", "achha", "achchha", "koi", "accha", "thik", "theek", "aur",
    "yaar", "bhai", "ji", "nahi", "haan", "han", "matlab", "phone", "gana",
    "gaana", "bhajan", "बंद", "क्या", "क्यों", "कैसे", "कब", "कौन", "खोलो",
    "करो", "कीजिए", "चलाओ", "बजाओ", "दिखाओ", "है", "नहीं", "मेरा", "मेरी",
    "नाम", "काम", "अभी", "रुको", "छोड़ो", "वाला", "कोई", "प्रोफाइल", "टैब",
    "स्क्रीन", "गाना",
})


def looks_like_stt_noise(text: str) -> bool:
    """True when nothing in the transcript is a word a real request
    contains. Conservative by construction - a single recognised token
    (or any question marker, number, URL or email) keeps the ordinary
    route."""
    cleaned = (text or "").strip()
    if len(cleaned) < 3:
        return True
    lowered = cleaned.lower()
    if _re_module.search(r"\d", lowered):
        return False  # numbers carry content ("25 guna 18")
    if _re_module.search(r"https?://|www\.|@\w+\.\w+", lowered):
        return False  # URLs and emails carry content
    if any(marker in lowered for marker in ("?", "kya hai", "what is", "kaun", "why")):
        return False  # questions are never discarded unread
    tokens = _re_module.findall(r"[\w\u0900-\u097F]+", lowered)
    if len(tokens) < 2:
        # A single word is noise only when it is not a word VYOM can
        # hear at all - "hello" is one token and one greeting.
        return not (tokens and tokens[0] in _AUDIBLE_VOCABULARY)
    return not any(token in _AUDIBLE_VOCABULARY for token in tokens)

#: Windows Settings pages addressable by their own protocol URI. Naming
#: one of these is what makes "Bluetooth settings kholo" a direct native
#: activation instead of a shell command plus UI navigation.
_SETTINGS_PAGES = (
    "bluetooth", "wifi", "wi-fi", "network", "display", "sound", "battery",
    "storage", "printer", "printers", "privacy", "windows update", "power",
    "notification", "notifications", "default apps", "personalisation",
    "personalization",
)

#: Asking what is on screen. Answering this from anything other than a
#: fresh observation is how VYOM described windows that were not open.
_SCREEN_QUESTIONS = (
    "screen pe kya", "screen par kya", "screen me kya", "what's on my screen",
    "whats on my screen", "what is on my screen", "what is open", "what's open",
    "whats open", "kya open hai", "kya khula hai", "konsi app", "kaunsi app",
    "which app is open", "current window", "active window", "abhi kya open",
    # "Screen pe abhi kya hai?" - the ABHI between 'pe' and 'kya' broke the
    # two-word phrase match, the question fell to the model, and the user
    # got a generic paragraph about their workspace instead of the real
    # window list. The positional variants are explicit so word order can
    # no longer decide between a fresh reading and an invented answer.
    "screen pe abhi", "screen par abhi", "screen me abhi",
    "abhi screen pe", "abhi screen par", "abhi screen me",
    "screen pe abhi kya", "on my screen now", "screen showing",
    "show nahi ho raha", "dikh nahi raha", "is button pe kya", "is button par kya",
    # Devanagari: Gemini Live transcribes spoken Hindi in this script.
    "स्क्रीन पर क्या", "स्क्रीन पे क्या", "स्क्रीन में क्या", "क्या ओपन है",
    "क्या खुला है", "कौन सी ऐप", "कौनसी ऐप", "अभी क्या ओपन",
    "स्क्रीन पर अभी", "स्क्रीन पे अभी", "स्क्रीन में अभी",
    # Asking whether VYOM can see the screen is a request for a reading,
    # not a yes/no about its own eyesight.
    "screen dikh rahi", "screen dikh raha", "show my screen", "see my screen",
    "स्क्रीन दिख रही", "स्क्रीन दिख रहा", "मेरी स्क्रीन",
)


def is_screen_question(text: str) -> bool:
    """True when the utterance asks what is on the user's screen - a
    question that may only be answered from a FRESH observation."""
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in _SCREEN_QUESTIONS)


# ======================================================================
# Action imperatives — permission to change the outside world
# ======================================================================
#
# "Intelligence is not permission to act." The 2026-08-19 physical
# session produced three unsolicited application launches:
#
#   "I cannot show on the calculator this is clear."  -> Calculator launched
#   "…No. Why again and again you speech to my…"      -> Calculator launched
#   "अभी जो क्रोम की प्रोफाइल ओपन है उसमें…"            -> profile opened
#
# None of them asked for anything. The first two are complaints that
# MENTION an app; the third describes state ("the profile that IS open")
# and trails off mid-sentence. In every case the planner was forced to
# use a tool (grounding) and the only tool the words suggested was a
# launch. An externally visible action now requires an actual IMPERATIVE
# in the utterance - the thing that makes "Chrome kholo" a command and
# "Chrome open hai" a description.

#: Unambiguous action imperatives across this user's languages. Bare
#: "open"/"ओपन" is deliberately NOT here: "the profile that is open" is
#: a description, not a command.
_ACTION_IMPERATIVES = (
    "kholo", "khol do", "kholiye", "khol dena", "khol", "खोलो", "खोल दो", "खोलिए",
    "open karo", "open kar do", "ओपन करो", "ओपन कर दो",
    "band karo", "band kar do", "band kar", "बंद करो", "बंद कर दो",
    "chalao", "chalu karo", "chala do", "चालू करो", "चला दो",
    "bajao", "baja do", "बजाओ", "बजा दो",
    "launch", "start karo", "shuru karo",
    "dikhao", "dikha do", "दिखाओ",
    # Page-level operation verbs - the human actions of using a page.
    "click karo", "click kar", "pe click", "par click", "dabao", "daba do",
    "scroll karo", "scroll kar", "scroll down", "scroll up", "scroll",
    "likho", "likh do", "type karo", "type kar", "type",
    "enter dabao", "enter mar", "दबाओ", "लिखो", "टाइप करो", "स्क्रॉल",
)

#: English imperatives: a sentence that opens with the verb itself.
_LEADING_ACTION_VERBS = ("open", "close", "launch", "play", "start", "navigate", "visit", "goto", "go to")


def requests_external_action(text: str) -> bool:
    """True only when the utterance is an actual instruction to change
    something in the world. Complaints, questions and descriptions -
    even ones naming an application - are not."""
    cleaned = (text or "").lower().strip()
    if not cleaned:
        return False
    if any(phrase in cleaned for phrase in _ACTION_IMPERATIVES):
        return True
    # "Open the Chrome." / "Launch calculator" - verb-first English.
    first = _re_module.sub(r"[^a-z0-9\s]", " ", cleaned).split()
    return bool(first) and first[0] in _LEADING_ACTION_VERBS

#: A BARE demonstrative question - "ye kya hai?", "यह क्या है?" - points at
#: whatever is in front of the user. It was being answered from durable
#: business memory ("your website is Luxora"), twenty seconds after a real
#: window reading had been taken and thrown away.
#:
#: Bareness is the whole test. "ye kya hai" is the screen; "ye API kya hai"
#: names its own subject and stays an ordinary question.
_BARE_DEMONSTRATIVES = frozenset({
    "ye", "yeh", "yah", "ise", "isko", "is", "this", "that", "it",
    "यह", "ये", "इसे", "इसको", "वह", "वो",
})
_BARE_QUESTION_TAILS = frozenset({
    "kya", "hai", "he", "h", "क्या", "है", "what", "is", "s",
})


def is_bare_demonstrative_question(text: str) -> bool:
    """'ye kya hai?' with no subject of its own."""
    cleaned = _re_module.sub(r"[.,!?।'\"]+", " ", (text or "").lower()).strip()
    words = [word for word in cleaned.split() if word]
    if not (2 <= len(words) <= 4):
        return False
    if not any(word in _BARE_DEMONSTRATIVES for word in words):
        return False
    return all(
        word in _BARE_DEMONSTRATIVES or word in _BARE_QUESTION_TAILS
        for word in words
    )

#: The user telling VYOM its last action did not appear. This is a
#: CORRECTION, not a question: the right response is to look at the target
#: again, restore/focus it and re-verify - not to narrate what is open.
_NOT_VISIBLE_COMPLAINTS = (
    "show nahi ho raha", "dikh nahi raha", "nahi dikh raha", "dikhai nahi",
    "nahi khula", "open nahi hua", "kuch nahi hua", "nothing happened",
    "i can't see", "i cannot see", "not showing", "didn't open", "did not open",
    "nahi aaya", "शो नहीं हो रहा", "दिख नहीं रहा", "नहीं शो हो रहा",
    "ओपन नहीं हुआ", "कुछ नहीं हुआ", "नहीं खुला", "नहीं दिख रहा",
)

#: Operating a control INSIDE an already-visible application.
_UI_VERBS = (
    "click", "dabao", "dabana", "press", "type", "likho", "likh", "enter karo",
    "select karo", "choose", "scroll", "tick", "check karo", "untick",
)


#: Spoken arithmetic operators, English and Hinglish, mapped to the
#: operator symbol. This is a NORMALISATION table, not a phrase list: it
#: is what keeps "27 guna 43" on the free deterministic path instead of
#: paying a planning model to rediscover multiplication.
_OPERATOR_WORDS: tuple[tuple[str, str], ...] = (
    ("multiplied by", "*"), ("times", "*"), ("guna", "*"), ("gunna", "*"), ("into", "*"),
    ("divided by", "/"), ("divide by", "/"), ("bhag", "/"), ("batta", "/"),
    ("plus", "+"), ("jod", "+"), ("add", "+"), ("aur", "+"),
    ("minus", "-"), ("ghata", "-"), ("subtract", "-"), ("less", "-"),
)

_ARITHMETIC = _re_module.compile(
    r"(\d+(?:\.\d+)?)\s*([*/+\-x×÷])\s*(\d+(?:\.\d+)?)"
)


def parse_arithmetic(text: str) -> tuple[float, str, float] | None:
    """Extract a single binary calculation from ordinary speech.

    Returns (left, operator, right) or None. Deliberately limited to one
    unambiguous binary operation: anything more complex is a genuine
    reasoning task and is allowed to become one."""
    lowered = text.lower()
    for word, symbol in _OPERATOR_WORDS:
        lowered = lowered.replace(f" {word} ", f" {symbol} ")
    match = _ARITHMETIC.search(lowered)
    if not match:
        return None
    operator = {"x": "*", "×": "*", "÷": "/"}[match.group(2)] if match.group(2) in {"x", "×", "÷"} else match.group(2)
    return float(match.group(1)), operator, float(match.group(3))


#: A CHAIN of at least two operations ("9 * 8 * 6 * 5 * ..."). The
#: physical session asked exactly that and the binary parser above
#: silently computed only the first pair - VYOM said "9 times 8 is 72"
#: while the user was still saying the rest of the number. A chain is
#: evaluated strictly LEFT TO RIGHT, because that is what pressing a
#: calculator's buttons in sequence does.
_ARITHMETIC_CHAIN = _re_module.compile(
    r"(?:\d+(?:\.\d+)?\s*[*/+\-x×÷]\s*){2,}\d+(?:\.\d+)?"
)
_CHAIN_TOKEN = _re_module.compile(r"\d+(?:\.\d+)?|[*/+\-x×÷]")
#: Guardrail: nobody says more than this many operands in one breath.
_MAX_CHAIN_OPERANDS = 12


def parse_arithmetic_chain(text: str) -> list[tuple[float, str | None]] | None:
    """Parse a multi-operation calculation into [(operand, operator-after),
    ..., (last operand, None)]. None when the utterance is not a chain of
    at least three operands."""
    lowered = text.lower()
    for word, symbol in _OPERATOR_WORDS:
        lowered = lowered.replace(f" {word} ", f" {symbol} ")
    match = _ARITHMETIC_CHAIN.search(lowered)
    if not match:
        return None
    tokens = _CHAIN_TOKEN.findall(match.group(0))
    segments: list[tuple[float, str | None]] = []
    expect_number = True
    for token in tokens:
        if expect_number:
            if not token[0].isdigit() and token[0] != ".":
                return None
            segments.append((float(token), None))
        else:
            if token[0].isdigit():
                return None
            operator = {"x": "*", "×": "*", "÷": "/"}.get(token, token)
            segments[-1] = (segments[-1][0], operator)
        expect_number = not expect_number
    if expect_number or len(segments) < 3 or len(segments) > _MAX_CHAIN_OPERANDS:
        return None
    return segments


def evaluate_chain(segments: list[tuple[float, str | None]]) -> float | None:
    """Left-to-right fold, exactly like sequential calculator presses.

    Segments are (operand, operator-AFTER) pairs, so the operator joining
    segment i to the running total lives on the PREVIOUS segment."""
    if not segments:
        return None
    total = segments[0][0]
    for index in range(1, len(segments)):
        operator = segments[index - 1][1]
        if operator is None:
            return None
        value = segments[index][0]
        if operator == "+":
            total += value
        elif operator == "-":
            total -= value
        elif operator == "*":
            total *= value
        elif operator == "/":
            if value == 0:
                return None
            total /= value
        else:
            return None
    return total


def _arithmetic_request(text: str) -> bool:
    return parse_arithmetic(text) is not None


#: Words that make a short "open X" request about something other than an
#: application, so it is not treated as a launch of an unknown program.
_NON_APP_OBJECTS = (
    "file", "folder", "directory", "url", "website", "site", "link", "page",
    "tab", "door", "account", "issue", "ticket", "email", "mail", "document",
)


#: Named web destinations. Saying one of these alongside a browser means
#: the TAB showing that page, not the browser application.
_WEB_PAGES = (
    "youtube", "gmail", "amazon", "flipkart", "google", "facebook", "instagram",
    "whatsapp", "twitter", "linkedin", "netflix", "chatgpt", "claude", "github",
    "python.org", "stackoverflow", "reddit", "maps", "drive", "docs", "sheets",
)

#: Ways of saying "a new tab" - roman and Devanagari, including the
#: "न्यू टैब" transliteration the physical session actually produced.
_NEW_TAB_PHRASES = (
    "new tab", "naya tab", "nayi tab", "naye tab", "newtabs",
    "नई टैब", "नया टैब", "न्यू टैब", "नयी टैब",
)


def _wants_new_tab(text: str) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in _NEW_TAB_PHRASES)


# ======================================================================
# Memory relevance — "remember broadly, retrieve narrowly"
# ======================================================================
#
# The physical session recited the user's name and business at:
#   "Sorry. This is the clear first."   -> "Understood, Gunjan Shah. I have
#                                          noted that your business is..."
#   "You are not a perfect."            -> "I acknowledge that I am not
#                                          perfect, Gunjan Shah. I am here
#                                          to assist you with लग्जुरा..."
#
# Both went through the reasoning path, which unconditionally attached
# every profile fact to the prompt. Durable memory now enters a mission
# only with a recorded REASON; a greeting, a complaint or a calculation
# carries none.

#: Identity slots the request itself may name.
_IDENTITY_SLOT_WORDS = (
    "my name", "mera naam", "meri naam", "naam kya", "who am i", "kaun hoon",
    "user name", "मेरा नाम", "मेरी नाम", "नाम क्या", "नाम क्या है",
    "my business", "mera business", "meri business", "business ka naam",
    "company", "कंपनी", "बिजनेस", "मेरा बिजनेस",
    "my website", "meri website", "mera website", "website kya", "site ka naam",
    "मेरी वेबसाइट", "वेबसाइट",
)

#: Business-work contexts in which business/client facts genuinely help.
_BUSINESS_WORK_WORDS = (
    "client", "clients", "lead", "leads", "crm", "invoice", "quote", "quotation",
    "proposal", "briefing", "report for", "outreach", "follow up", "followup",
    "pipeline", "deal", "customer", "ग्राहक", "क्लाइंट", "रिपोर्ट",
)

#: Correction markers (a correction about X requires X's current value).
_CORRECTION_MARKERS = (
    "nahi hai", "nahi he", "wrong", "galat", "correct kar", "instead",
    "बदलो", "गलत", "सही", "नहीं है",
)


def memory_relevance_reason(request: str) -> str | None:
    """Why durable profile memory may enter this mission, or None.

    One of: EXACT_SLOT_REQUIRED, SEMANTICALLY_RELEVANT,
    USER_REFERENCED, CORRECTION_REQUIRED. None means: retrieve nothing -
    the request is complete without personal history, and attaching it
    only tempts the response into reciting it."""
    lowered = (request or "").lower()
    if not lowered:
        return None
    if any(word in lowered for word in _IDENTITY_SLOT_WORDS):
        return "EXACT_SLOT_REQUIRED"
    if any(word in lowered for word in _CORRECTION_MARKERS) and any(
        word in lowered for word in ("naam", "name", "business", "website", "site",
                                     "नाम", "बिजनेस", "वेबसाइट")
    ):
        return "CORRECTION_REQUIRED"
    if any(word in lowered for word in _BUSINESS_WORK_WORDS):
        return "SEMANTICALLY_RELEVANT"
    return None


def _names_browser_page(text: str) -> bool:
    """Does this name a PAGE inside a browser rather than the browser?

    "Chrome me YouTube close karo" carries both a browser word and a page
    word: the object being closed is the page. "Chrome band karo" carries
    only the browser word."""
    if "tab" in text:
        return True
    names_page = any(page in text for page in _WEB_PAGES)
    if not names_page:
        return False
    # A page named ALONGSIDE a browser, or with an "inside" particle, is a
    # tab. A page named alone ("close YouTube") is also a tab - there is
    # nothing else it could mean.
    return True


def _looks_like_app_launch(text: str) -> bool:
    """Is this "open <something that is plainly a program name>"?

    Deliberately narrow: a short request, an open verb, and a single
    remaining noun that is not a file, URL or document. It exists so an
    unrecognised application name still reaches the desktop capability -
    which answers NOT_FOUND from real resolution - instead of falling
    through to a planner that goes looking for it with shell commands."""
    words = [word for word in re.findall(r"[\w.-]+", text) if word]
    if not (2 <= len(words) <= 4):
        return False
    if any(noun in text for noun in _NON_APP_OBJECTS):
        return False
    if _URL.search(text):
        return False
    verbs = {"open", "launch", "start", "run", "kholo", "khol", "chalu", "chala"}
    remaining = [word for word in words if word not in verbs]
    if len(remaining) != 1:
        return False
    candidate = remaining[0]
    # A bare domain ("google.com") is a website, not an installed program.
    if re.search(r"\.(com|org|net|io|dev|space|in|co|ai|app)$", candidate, re.I):
        return False
    # A bare number or a one-letter token is not an application name.
    return len(candidate) >= 3 and not candidate.isdigit()


def _mentions_file_target(text: str) -> bool:
    """Does this request talk about FILES, as opposed to naming the File
    Explorer application?

    "File Explorer me VYOM Project kholo" contains the word "file", but it
    is an application launch with a folder target - reading it as a
    directory listing answered a completely different question."""
    without_app_names = text.replace("file explorer", " ").replace("windows explorer", " ")
    # Word-boundary match for "file"/"files": a plain substring check also
    # lit up on "profile"/"profiles" ("pro-FILE"), so "show me my browser
    # profiles" was read as a filesystem listing request instead of the
    # browser-profile request it actually is.
    if re.search(r"\bfiles?\b", without_app_names):
        return True
    return any(
        word in without_app_names
        for word in ("folder", "directory", "dir", "contents of", "what's in", "whats in")
    )



# Hindi/Hinglish action verbs mapped onto the English the deterministic
# classifier already understands. This is a small NORMALISATION layer, not
# a phrase list: it keeps spoken Hindi on the free, near-instant C0 path
# instead of paying for a planning model to re-discover "open".
_HINGLISH_VERBS = (
    # DEVANAGARI FIRST. Gemini Live transcribes spoken Hindi in Devanagari
    # script, not romanised Hinglish - "उसको क्लोज कर दो" never matched the
    # romanised table below, so a plain "close Chrome" fell through to the
    # general planner and failed. Longer forms precede shorter ones so
    # "बंद कर दो" is not consumed by "बंद".
    ("क्लोज कर दो", "close"), ("क्लोज करो", "close"), ("क्लोज", "close"),
    ("बंद कर दो", "close"), ("बंद करो", "close"), ("बंद कर", "close"), ("बंद", "close"),
    ("ओपन कर दो", "open"), ("ओपन करो", "open"), ("ओपन", "open"),
    ("खोल दो", "open"), ("खोलो", "open"), ("खोल", "open"),
    ("चालू करो", "open"), ("चालू कर", "open"), ("शुरू करो", "open"),
    ("चला दो", "run"), ("चलाओ", "run"), ("चला", "run"),
    ("दिखा दो", "show"), ("दिखाओ", "show"), ("दिखा", "show"),
    ("बता दो", "tell me"), ("बताओ", "tell me"), ("बता", "tell me"),
    ("बना दो", "create"), ("बनाओ", "create"),
    ("पढ़ो", "read"), ("पढ़", "read"),
    ("ढूंढो", "find"), ("ढूँढो", "find"), ("खोजो", "find"), ("फाइंड", "find"),
    ("टाइप करो", "type"), ("क्लिक करो", "click"), ("दबाओ", "click"),
    ("हटाओ", "delete"),
    # Romanised Hinglish.
    ("kholo", "open"), ("khol do", "open"), ("khol", "open"),
    ("chalu karo", "open"), ("chalu kar", "open"), ("start karo", "open"),
    ("chala do", "run"), ("chalao", "run"), ("chala", "run"),
    ("dikhao", "show"), ("dikha do", "show"), ("dikha", "show"),
    ("batao", "tell me"), ("bata do", "tell me"), ("bata", "tell me"),
    ("banao", "create"), ("bana do", "create"),
    ("band karo", "close"), ("band kar", "close"),
    ("padho", "read"), ("padh", "read"),
    ("dhoondo", "find"), ("dhoond", "find"),
    ("check kar ke", "check"), ("check kar", "check"),
    ("hatao", "delete"),
)
#: Hindi possessives/pronouns that carry no routing information, in both
#: scripts. "उसको"/"इसमें" are references, not targets - keeping them made
#: the reordered sentence look like it named an unknown application.
_HINGLISH_FILLER = (
    "mere", "meri", "mera", "ka", "ke", "ki", "me", "mein", "par", "se", "aur", "ko",
    "मेरे", "मेरी", "मेरा", "का", "के", "की", "में", "पर", "से", "और", "को",
    "उसको", "उसमें", "उसे", "इसको", "इसमें", "इसे", "यह", "वह", "है", "हैं", "तो", "भी",
)


def normalise_hinglish(request: str) -> str:
    """Rewrite Hindi action verbs to their English equivalents so one
    classifier serves both languages. Returns the request unchanged when
    no Hindi verb is present."""
    lowered = request.lower()
    if not any(verb in lowered for verb, _ in _HINGLISH_VERBS):
        return request
    for verb, english in _HINGLISH_VERBS:
        lowered = lowered.replace(verb, english)
    # A Hindi sentence puts the verb last; the classifier expects it
    # first. Punctuation is stripped per word: "kholo." became "open.",
    # which no longer matched the verb set, so the reordering that puts
    # the verb first silently did nothing.
    words = [
        word.strip(".,!?;:।")
        for word in lowered.split()
        if word.strip(".,!?;:।") and word.strip(".,!?;:।") not in _HINGLISH_FILLER
    ]
    verbs = {english for _, english in _HINGLISH_VERBS}
    found = [word for word in words if word in verbs]
    rest = [word for word in words if word not in verbs]
    if not found:
        return " ".join(words)
    # Hindi puts the OPERATIVE verb last: "मेरा Chrome ओपन है ... उसको
    # क्लोज कर दो" describes a state ("is open") and then gives the
    # instruction ("close it"). Hoisting every verb produced "open open
    # chrome youtube close", which read as a launch and opened Chrome
    # again instead of closing it. The final verb is the instruction; the
    # earlier ones are context.
    operative = found[-1]
    return " ".join([operative, *rest])


class TaskClassifier:
    """Resolves a request into an executable profile.

    Two layers, in order:

    1. Explicit named workflows (the long `if` chain below) - unchanged.
    2. `_resolve_capability_intent`: a generic verb/target resolver that
       maps ordinary language onto the registered tool capabilities
       (filesystem, desktop apps, browser, terminal). This layer is what
       makes "list the files in my project" or "open Calculator" real
       actions rather than text answers.

    Only if BOTH layers decline does a request become a reasoning task
    for a model."""

    def classify(self, request: str) -> TaskProfile:
        # Spoken Hindi reaches the same free deterministic routes as English.
        # The ORIGINAL wording is kept: normalisation rewrites verbs and
        # drops particles, which is right for routing an instruction but
        # destroys a QUESTION - "स्क्रीन पर क्या ओपन है" became "open
        # स्क्रीन क्या" and stopped looking like a question about the
        # screen at all. Question phrases are matched against both forms.
        original = request.strip().lower()
        request = normalise_hinglish(request)
        text = request.strip().lower()
        self._original = original

        # Dated history questions contain hyphenated/slashed dates that
        # resemble arithmetic ("2016-08-20"). Resolve this command-level
        # intent before generic calculator/UI detection so the original
        # user record is read locally rather than sent to Calculator.
        from app.memory.history import is_historical_recall

        if is_historical_recall(original):
            return TaskProfile(
                domain=TaskDomain.PERSONAL, complexity=1, latency_priority="high",
                deterministic=True, intent="memory_history_recall", needs=set(),
            )

        if re.search(r"\brun\s+skill\s+[a-z0-9][a-z0-9-]{2,63}(?:\s+with\s+.+)?$", original):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, deterministic=True,
                intent="run_taught_skill", needs={"intelligence", "tools"},
            )

        if any(phrase in original for phrase in (
            "show my brain", "show vyom brain", "brain graph", "brain connections",
            "living core graph", "show what you know",
        )):
            return TaskProfile(
                domain=TaskDomain.ANALYSIS, complexity=1, deterministic=True,
                intent="show_brain_graph", needs={"intelligence"},
            )

        # A natural schedule owns a FUTURE command; the embedded words
        # ("show status", "open Chrome") must not execute immediately.
        from app.automation.natural_schedule import is_schedule_request

        if is_schedule_request(original):
            return TaskProfile(
                domain=TaskDomain.PLANNING, complexity=1, latency_priority="high",
                deterministic=True, intent="schedule_command", needs=set(),
            )

        if "what needs approval" in text or "show pending approvals" in text:
            return TaskProfile(domain=TaskDomain.AGENCY, complexity=1, deterministic=True, intent="approval_query", needs={"business"})
        if "send approved outreach" in text or "send the approved email" in text:
            return TaskProfile(domain=TaskDomain.COMMUNICATION, complexity=2, deterministic=True, intent="send_approved_outreach", needs={"business"})
        if "draft" in text and ("outreach" in text or "lead email" in text):
            return TaskProfile(domain=TaskDomain.AGENCY, complexity=2, deterministic=True, intent="draft_outreach", needs={"business"})
        if "find" in text and ("qualified companies" in text or "qualified leads" in text):
            return TaskProfile(domain=TaskDomain.AGENCY, complexity=3, deterministic=True, intent="lead_research", needs={"business"})
        if text in {"show agency", "show agency view"} or "show my agency" in text:
            return TaskProfile(domain=TaskDomain.AGENCY, complexity=2, deterministic=True, intent="show_agency", needs={"business"})
        if "show crm" in text or "crm status" in text:
            return TaskProfile(domain=TaskDomain.AGENCY, complexity=1, deterministic=True, intent="crm_summary", needs={"business"})
        if "show inbox" in text or "show me my inbox" in text or "search my email" in text:
            return TaskProfile(domain=TaskDomain.COMMUNICATION, complexity=1, deterministic=True, intent="email_inbox", needs={"business"})
        if "schedule" in text and ("meeting" in text or "calendar" in text):
            return TaskProfile(domain=TaskDomain.COMMUNICATION, complexity=2, deterministic=True, intent="schedule_meeting", needs={"business"})
        if "prepare me for" in text and "meeting" in text and "market briefing" not in text:
            return TaskProfile(domain=TaskDomain.COMMUNICATION, complexity=2, deterministic=True, intent="meeting_briefing", needs={"business"})
        if "calendar" in text and ("today" in text or "status" in text or "availability" in text):
            return TaskProfile(domain=TaskDomain.COMMUNICATION, complexity=1, deterministic=True, intent="calendar_status", needs={"business"})
        if "automate" in text and ("briefing" in text or "agency" in text):
            return TaskProfile(domain=TaskDomain.AGENCY, complexity=2, deterministic=True, intent="create_automation", needs={"business"})

        if "research the top competitors" in text or ("research" in text and "competitor" in text):
            return TaskProfile(domain=TaskDomain.RESEARCH, complexity=4, deterministic=True, intent="competitor_research", needs={"phase8"})
        if "can vyom connect to" in text or "connect to " in text and "?" in text:
            return TaskProfile(domain=TaskDomain.RESEARCH, complexity=2, deterministic=True, intent="mcp_discovery", needs={"phase8"})
        if ("find" in text or "compare" in text) and ("tool" in text or "api" in text or "subscription" in text) and "lead" not in text:
            return TaskProfile(domain=TaskDomain.RESEARCH, complexity=3, deterministic=True, intent="tool_discovery", needs={"phase8"})
        if "find me a" in text and ("restaurant" in text or "hotel" in text or "appointment" in text or "meeting room" in text):
            return TaskProfile(domain=TaskDomain.AGENCY, complexity=3, criticality="normal", deterministic=True, intent="booking_search", needs={"phase8"})
        if ("book" in text or "reserve" in text) and ("option" in text or "it" in text or "that" in text) and "outreach" not in text:
            return TaskProfile(domain=TaskDomain.AGENCY, complexity=2, criticality="normal", deterministic=True, intent="booking_reserve", needs={"phase8"})
        if "client report" in text or ("weekly" in text and "report" in text and "for" in text):
            return TaskProfile(domain=TaskDomain.CREATIVE, complexity=3, deterministic=True, intent="generate_client_report", needs={"phase8"})
        if "presentation" in text and ("turn" in text or "create" in text or "build" in text):
            return TaskProfile(domain=TaskDomain.CREATIVE, complexity=3, deterministic=True, intent="generate_presentation", needs={"phase8"})
        if "prepare everything ready to send" in text or ("prepare" in text and "delivery" in text):
            return TaskProfile(domain=TaskDomain.AGENCY, complexity=3, deterministic=True, intent="prepare_client_delivery", needs={"phase8"})
        if "research " in text and ("market" in text or "trend" in text or "technology" in text or "product" in text or "company" in text):
            return TaskProfile(domain=TaskDomain.RESEARCH, complexity=3, deterministic=True, intent="deep_research", needs={"phase8"})

        if "analyze" in text and "this project" not in text and "code" not in text and extract_symbol(request) is not None:
            return TaskProfile(domain=TaskDomain.FINANCE, complexity=3, deterministic=True, intent="analyze_market", needs={"phase10"})
        if "add" in text and "watchlist" in text:
            return TaskProfile(domain=TaskDomain.FINANCE, complexity=1, deterministic=True, intent="watchlist_add", needs={"phase10"})
        if "watchlist" in text and ("show" in text or "what" in text or "what's" in text or "whats" in text):
            return TaskProfile(domain=TaskDomain.FINANCE, complexity=1, deterministic=True, intent="watchlist_show", needs={"phase10"})
        if "risky" in text and "portfolio" in text:
            return TaskProfile(domain=TaskDomain.FINANCE, complexity=2, deterministic=True, intent="portfolio_risk", needs={"phase10"})
        if "portfolio" in text and "risk" in text:
            return TaskProfile(domain=TaskDomain.FINANCE, complexity=2, deterministic=True, intent="portfolio_risk", needs={"phase10"})
        if "paper" in text and ("trade setup" in text or "setup" in text) and "strategy" not in text:
            return TaskProfile(domain=TaskDomain.FINANCE, complexity=3, deterministic=True, intent="create_paper_trade_setup", needs={"phase10"})
        if "backtest" in text:
            return TaskProfile(domain=TaskDomain.FINANCE, complexity=3, deterministic=True, intent="run_backtest", needs={"phase10"})
        if "market briefing" in text or ("briefing" in text and ("market" in text or "trading" in text)):
            return TaskProfile(domain=TaskDomain.FINANCE, complexity=2, deterministic=True, intent="market_briefing", needs={"phase10"})
        if "why did" in text and "trade" in text and ("lose" in text or "lost" in text):
            return TaskProfile(domain=TaskDomain.FINANCE, complexity=2, deterministic=True, intent="trade_postmortem", needs={"phase10"})

        if ("enable" in text and ("auto-start" in text or "autostart" in text or "startup" in text)):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=1, deterministic=True, intent="desktop_startup_enable", needs={"phase9"})
        if ("disable" in text and ("auto-start" in text or "autostart" in text or "startup" in text)):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=1, deterministic=True, intent="desktop_startup_disable", needs={"phase9"})
        if "startup" in text and ("status" in text or "check" in text):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=1, deterministic=True, intent="desktop_startup_status", needs={"phase9"})
        # "Open the VYOM project" means the editor. If the user NAMES a
        # different application ("File Explorer me VYOM Project kholo")
        # they mean that application, and honouring the generic rule
        # opened the wrong program entirely.
        if "open" in text and "vyom project" in text and not any(
            app in text for app in ("explorer", "file explorer", "chrome", "terminal", "notepad")
        ):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=3, deterministic=True, intent="open_project", needs={"phase9"})
        if ("put" in text or "arrange" in text) and ("left" in text or "right" in text) and ("editor" in text or "browser" in text or "window" in text):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=2, deterministic=True, intent="window_arrangement", needs={"phase9"})
        if "what am i looking at" in text or "show me what you're doing" in text or "show me what you are doing" in text:
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=2, deterministic=True, intent="screen_context", needs={"phase9"})
        if "save a copy of this" in text or ("save this" in text and "project" in text):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=2, criticality="normal", deterministic=True, intent="contextual_save", needs={"phase9"})
        if "why is my pc slow" in text or "why is my computer slow" in text or ("system status" in text) or ("pc" in text and "slow" in text):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=1, deterministic=True, intent="system_status_explain", needs={"phase9"})

        # -- Phase 13 production/diagnostics intents ----------------------
        if ("run diagnostics" in text or "run a diagnostic" in text) or ("vyom" in text and "diagnostics" in text and "run" in text):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=1, deterministic=True, intent="run_diagnostics", needs={"phase13"})
        if "security audit" in text and ("run" in text or "vyom" in text or "check" in text):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=1, deterministic=True, intent="security_audit", needs={"phase13"})
        if "how much" in text and ("cost" in text or "costing" in text) and ("vyom" in text or "today" in text or "me" in text):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=1, deterministic=True, intent="cost_query", needs={"phase13"})
        if "why did you choose" in text or ("why" in text and "approach" in text and "choose" in text):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=1, deterministic=True, intent="explain_decision", needs={"phase13"})
        if ("why isn't vyom working" in text or "why is vyom not working" in text or "check system health" in text or "what's wrong with vyom" in text or "whats wrong with vyom" in text):
            return TaskProfile(domain=TaskDomain.SYSTEM, complexity=1, deterministic=True, intent="troubleshoot", needs={"phase13"})

        if text.startswith("remember that") or "remember that i prefer" in text:
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=1, deterministic=True, intent="remember_preference", needs={"intelligence"})
        if "what time do i prefer" in text or "what do i prefer" in text:
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=1, deterministic=True, intent="recall_preference", needs={"intelligence"})
        if text.startswith("forget") and ("preference" in text or "remember" in text):
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=1, deterministic=True, intent="forget_memory", needs={"intelligence"})
        if "why do you remember" in text or "how do you know" in text:
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=1, deterministic=True, intent="explain_memory", needs={"intelligence"})
        if text.startswith("no, that's wrong") or text.startswith("no that's wrong"):
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=1, deterministic=True, intent="correct_memory", needs={"intelligence"})
        if "inspect this project" in text and "remember how" in text and ("built" in text or "build" in text):
            return TaskProfile(domain=TaskDomain.CODING, complexity=3, deterministic=True, intent="inspect_project_memory", needs={"intelligence", "tools"})
        if "how do i build this project" in text or "how is this project built" in text:
            return TaskProfile(domain=TaskDomain.CODING, complexity=1, deterministic=True, intent="recall_project_build", needs={"intelligence"})
        if "show me everything related to" in text:
            return TaskProfile(domain=TaskDomain.ANALYSIS, complexity=2, deterministic=True, intent="show_related_memory", needs={"intelligence"})
        if "create a reusable skill" in text and ("build" in text or "builds correctly" in text):
            return TaskProfile(domain=TaskDomain.CODING, complexity=3, deterministic=True, intent="create_build_skill", needs={"intelligence"})
        if "run the build-check skill" in text or "run the build check skill" in text:
            return TaskProfile(domain=TaskDomain.CODING, complexity=3, deterministic=True, intent="run_build_skill", needs={"intelligence", "tools"})
        if "create a project health agent" in text:
            return TaskProfile(domain=TaskDomain.CODING, complexity=4, deterministic=True, intent="create_project_health_agent", needs={"intelligence", "tools"})
        if ("run" in text or "ask" in text) and "project health agent" in text:
            return TaskProfile(domain=TaskDomain.CODING, complexity=4, deterministic=True, intent="run_project_health_agent", needs={"intelligence", "tools"})
        if "lesson" in text and ("build" in text or "failure" in text):
            return TaskProfile(domain=TaskDomain.CODING, complexity=1, deterministic=True, intent="recall_failure_lesson", needs={"intelligence"})
        if (text.startswith("learn from") and "fail" in text) or "safe failing task" in text:
            return TaskProfile(domain=TaskDomain.CODING, complexity=2, deterministic=True, intent="learn_from_failure", needs={"intelligence"})

        if "inspect this project" in text and ("build" in text or "builds correctly" in text):
            return TaskProfile(domain=TaskDomain.CODING, complexity=3, deterministic=True, intent="inspect_project_build", needs={"tools"})
        if "inspect this project" in text or "inspect the project" in text:
            return TaskProfile(domain=TaskDomain.CODING, complexity=2, deterministic=True, intent="inspect_project", needs={"tools"})
        if text in {"run the tests", "run tests", "test this project"} or "run the tests" in text:
            return TaskProfile(domain=TaskDomain.CODING, complexity=2, deterministic=True, intent="run_tests", needs={"tools"})
        if "create" in text and "file" in text and ("project" in text or ".txt" in text):
            return TaskProfile(domain=TaskDomain.CODING, complexity=2, deterministic=True, intent="create_project_file", needs={"tools"})
        if ("delete" in text or "remove" in text) and "file" in text:
            return TaskProfile(domain=TaskDomain.CODING, complexity=2, criticality="critical", deterministic=True, intent="delete_project_file", needs={"tools"})
        if "show me what changed" in text or "show what changed" in text:
            return TaskProfile(domain=TaskDomain.CODING, complexity=1, deterministic=True, intent="show_changes", needs={"tools"})
        if "open" in text and ("local app" in text or "project in the browser" in text) and ("verify" in text or "home screen" in text or "browser" in text):
            return TaskProfile(domain=TaskDomain.CODING, complexity=3, deterministic=True, intent="open_local_app", needs={"tools"})

        if "close everything" in text or "clear everything" in text:
            return TaskProfile(
                domain=TaskDomain.SYSTEM,
                complexity=1,
                latency_priority="high",
                deterministic=True,
                intent="close_everything",
                needs=set(),
            )
        if "what is my status" in text or "status today" in text:
            return TaskProfile(
                domain=TaskDomain.PERSONAL,
                complexity=2,
                latency_priority="high",
                deterministic=True,
                intent="daily_status",
                needs={"business"},
            )
        if "plan my work" in text or "plan my day" in text or "what's the plan today" in text or "whats the plan today" in text or "what should i do today" in text:
            return TaskProfile(domain=TaskDomain.PLANNING, complexity=3, deterministic=True, intent="plan_today", needs={"phase11"})
        if "what should i work on" in text or "what should i do now" in text or "what should i do right now" in text:
            return TaskProfile(domain=TaskDomain.PLANNING, complexity=2, deterministic=True, intent="what_now", needs={"phase11"})
        if "how did today go" in text or "how did my day go" in text:
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=2, deterministic=True, intent="evening_review", needs={"phase11"})
        if "weekly review" in text:
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=2, deterministic=True, intent="weekly_review", needs={"phase11"})
        # "I want to ..." is a personal goal, unless it is a purchase
        # intent ("I want to buy a blue laptop bag"), which is shopping.
        if (
            text.startswith("i want to")
            and "remember" not in text
            and not any(word in text for word in ("buy", "order", "purchase", "shop"))
        ):
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=2, deterministic=True, intent="goal_create", needs={"phase11"})
        if "how am i doing on" in text and "goal" in text:
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=2, deterministic=True, intent="goal_status", needs={"phase11"})
        if "how are my habits" in text or ("habits" in text and "going" in text):
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=2, deterministic=True, intent="habits_status", needs={"phase11"})
        if "why do i keep" in text or "why am i" in text and ("wasting" in text or "procrastinat" in text):
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=2, deterministic=True, intent="bad_habit_query", needs={"phase11"})
        if "what do i owe" in text or "what have i promised" in text:
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=1, deterministic=True, intent="commitments_query", needs={"phase11"})
        if "start" in text and "focus" in text and ("mode" in text or "session" in text or "minutes" in text or "on " in text):
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=2, deterministic=True, intent="focus_start", needs={"phase11"})
        if "pause focus" in text or ("pause" in text and "focus" in text):
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=1, deterministic=True, intent="focus_pause", needs={"phase11"})
        if ("complete focus" in text) or ("how did that focus session go" in text) or ("end focus" in text) or ("stop focus" in text):
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=1, deterministic=True, intent="focus_complete", needs={"phase11"})
        if "don't disturb" in text or "do not disturb" in text or "quiet mode" in text:
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=1, deterministic=True, intent="quiet_mode_start", needs={"phase11"})
        if "run" in text and "routine" in text:
            return TaskProfile(domain=TaskDomain.PERSONAL, complexity=2, deterministic=True, intent="routine_run", needs={"phase11"})
        if "what model" in text or "model you chose" in text or "explain model" in text:
            return TaskProfile(
                domain=TaskDomain.ANALYSIS,
                complexity=1,
                latency_priority="high",
                deterministic=True,
                intent="explain_routing",
                needs={"general", "structured_output"},
            )

        # Layer 2: generic capability-backed actions. Runs before the
        # model-only fallback so ordinary phrasing reaches real tools.
        capability_profile = self._resolve_capability_intent(text, request)
        if capability_profile is not None:
            return capability_profile

        domain = TaskDomain.GENERAL
        complexity = 2
        needs = {"general", "structured_output"}
        if any(word in text for word in ("code", "bug", "repository", "typescript", "python")):
            domain, complexity, needs = TaskDomain.CODING, 4, {"coding", "reasoning", "structured_output"}
        elif any(word in text for word in ("research", "sources", "compare")):
            domain, complexity, needs = TaskDomain.RESEARCH, 3, {"research", "reasoning", "structured_output"}
        elif any(word in text for word in ("lead", "outreach", "agency", "client")):
            domain, complexity = TaskDomain.AGENCY, 3
        elif any(word in text for word in ("analyze", "analysis", "why")):
            domain, complexity, needs = TaskDomain.ANALYSIS, 3, {"reasoning", "structured_output"}
        elif any(word in text for word in ("email", "message", "reply")):
            domain, complexity = TaskDomain.COMMUNICATION, 2
        elif any(word in text for word in ("finance", "budget", "stock", "trade")):
            domain, complexity = TaskDomain.FINANCE, 4

        criticality = "critical" if any(word in text for word in ("payment", "trade", "delete all")) else "low"
        privacy = "highly_sensitive" if any(word in text for word in ("password", "secret", "credential")) else "normal"
        return TaskProfile(
            domain=domain,
            complexity=complexity,
            criticality=criticality,
            needs=needs,
            privacy=privacy,
            intent="general",
        )

    # -- layer 2: capability-backed generic actions ------------------------

    def _resolve_capability_intent(self, text: str, request: str) -> TaskProfile | None:
        """Map ordinary language onto a registered tool capability.

        Returns None when the request is genuinely a reasoning/answering
        task. Every profile returned here carries needs={"tools"}, which
        routes the task through ActionEngine (real tool execution +
        evidence + UI composition) instead of a model-only answer.

        Deliberately conservative: an ambiguous request stays a reasoning
        task rather than triggering an action the user did not ask for."""

        # -- capability truth comes from the live registry ----------------
        # Questions about VYOM itself must not go to a model that can invent
        # either an inability or a capability. They are answered from the
        # currently registered components.
        self_question = f"{text} {getattr(self, '_original', '')}".lower()
        if any(phrase in self_question for phrase in (
            "what can you do", "what tasks can you", "which tasks can you",
            "what are your capabilities", "what capability do you have",
            "tum kya kar sakti", "tum kya kar sakte", "kya kya kar sakti",
            "kya kya kar sakte", "तुम क्या कर सकती", "तुम क्या कर सकते",
            "kaun se kaun se task perform", "kon se task perform",
            "कौन से कौन से टास्क परफॉर्म", "कौन कौन से टास्क",
            "do you have personal memory", "do you have a personal memory",
            "you have the personal memory", "do you have memory",
            "kya tumhare paas memory", "क्या तुम्हारे पास मेमोरी",
        )):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                deterministic=True, intent="capability_query", needs={"tools"},
            )

        # -- play media in the user's visible browser ---------------------
        #
        # These requests previously fell into the general planner, which
        # merely listed open windows and then declared the song request
        # complete. A media request is one concrete, verifiable workflow:
        # search -> open a result -> observe real browser playback.
        media_text = f"{text} {getattr(self, '_original', '')}".lower()
        media_named = re.search(
            r"\b(?:song|music|gaana|gana|track|bhajan|video)\b|सॉन्ग|गाना|संगीत|भजन|वीडियो",
            media_text, re.I,
        )
        play_order = re.search(
            r"\b(?:play|start|chalao|chala\s*do|bajao|baja\s*do|laga\s*do)\b"
            r"|चलाओ|चलाना|चला\s*(?:दो|दूं)|बजाओ|बजाना|बजा\s*दो|लगा\s*दो",
            media_text, re.I,
        )
        # Natural speech often omits the final verb: "mere liye ek achcha
        # Bollywood song" and "ek kaam karo ... song" are still direct
        # requests, while questions such as "which song is this?" are not.
        elliptical_order = (
            any(phrase in media_text for phrase in (
                "mere liye", "for me", "ek kaam karo", "एक काम करो", "मेरे लिए",
            ))
            and not any(marker in media_text for marker in (
                "?", "which song", "what song", "kaunsa song", "konsa song",
                "कौन सा गाना", "कौनसा गाना",
            ))
        )
        if media_named and (play_order or elliptical_order):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, criticality="normal",
                deterministic=True, intent="play_media", needs={"tools"},
            )

        # -- shopping across retailers -------------------------------------
        # Checked before generic web browsing: "find me the best black
        # running shoes on Amazon and Flipkart" is a product comparison
        # across named retailers, not a single web search.
        shopping_verb = any(
            phrase in text
            for phrase in (
                "buy", "book me", "book a pair", "order", "shop for", "shopping for",
                "price of", "cheapest", "best deal", "compare price", "find me the best",
                "looking for a", "want to buy",
                # Plain "find <product>" ("blue shoes size 12 find karo",
                # "find blue shoes size 12") is ordinary Hinglish shopping
                # phrasing, not just the "find me the best ..." form above -
                # it was falling through to the general reasoning path
                # (a paid model call with no real multi-retailer search)
                # instead of the free, deterministic shop_compare workflow.
                "find",
                # "chahiye" ("pots chahiye blue colour ke hone chahiye") is
                # the ordinary Hindi way to want a product - not a request
                # verb like "buy"/"find" at all, so it was never recognised
                # as shopping language no matter how plainly a product was
                # named. Combined with product_noun below it is exactly as
                # safely scoped as "buy"/"find" already are: "help chahiye"
                # never matches because "help" is not a product noun.
                "chahiye", "चाहिए",
            )
        )
        product_noun = any(
            word in text
            for word in (
                "shoes", "sneakers", "shirt", "tshirt", "t-shirt", "jeans", "watch",
                "headphone", "earphone", "earbuds", "laptop", "phone", "mobile", "bag",
                "jacket", "dress", "kurta", "saree", "sandals", "slippers", "trousers",
                "pot", "pots",
                # Devanagari-script product words. normalise_hinglish only
                # rewrites known ACTION VERBS to English - a noun like
                # "शूज" (shoes) reaches this check completely unchanged, so
                # "मेरे लिए ब्लू कलर के शूज तुम फाइंड कर सकती हो?" fell
                # through to the general reasoning path despite naming a
                # real product just as plainly as its English spelling.
                "शूज", "जूते", "जूता", "गमला", "गमले",
            )
        )
        retailer_named = any(
            word in text
            for word in ("amazon", "flipkart", "meesho", "myntra", "ajio", "online store", "shopping site")
        )
        if (shopping_verb and product_noun) or (retailer_named and product_noun):
            return TaskProfile(
                domain=TaskDomain.RESEARCH, complexity=4, criticality="normal",
                deterministic=True, intent="shop_compare", needs={"tools"},
            )

        # -- browser / web -------------------------------------------------
        url_match = _URL.search(request)
        wants_web = any(
            phrase in text
            for phrase in (
                "search the web", "search online", "look it up online", "look up online",
                "on the web", "google ", "web search", "search for", "browse to",
                "go to the website", "open the website", "find online",
            )
        )
        wants_browser_app = any(app in text for app in _BROWSER_APPS) and any(
            verb in text for verb in ("open", "launch", "start", "use")
        )
        # THE VISIBLE BROWSER AND THE RESEARCH BROWSER ARE DIFFERENT WORLDS.
        #
        # `web_browse` runs a headless Playwright session the user cannot
        # see - correct for gathering information, and a lie when the user
        # asked to be SHOWN something. Naming a browser ("Chrome me
        # python.org kholo", "is tab me", "meri screen par") means the real
        # visible session, so it becomes an application launch carrying the
        # page as its target. Silently answering it with a hidden browser
        # and reporting success is the failure this closes.
        names_visible_browser = any(app in text for app in ("chrome", "edge", "firefox"))
        wants_to_see = any(
            phrase in text
            for phrase in (
                "kholo", "khol", "open", "show me", "dikhao", "dikha",
                "meri screen", "my screen", "is tab", "isi tab", "new tab",
                "naya tab", "is profile", "isi chrome", "is chrome",
            )
        )
        # A PROFILE can be named without the word "profile": "Chrome pe
        # Golly AI OS open karo" names one of this machine's real Chrome
        # identities. This check has to precede the generic browser launch
        # below, which would otherwise swallow it and hand the user an
        # empty Chrome window - which is exactly what happened, and why
        # they said "मेरे को नहीं दिख रहा कि गोली प्रोफाइल ओपन हुई है".
        #
        # It asks the REAL profile list, so it is semantic resolution
        # against live state rather than a hard-coded name, and it only
        # runs for a browser launch that named no destination of its own.
        # -- operating the PAGE inside the visible browser (Gate B) -------
        #
        # "search box me X likho", "pehla result kholo", "scroll down",
        # "page pe kya hai" - the human actions of USING a page. These
        # drive the visible browser's own exposed document through UI
        # Automation: elements found by name, never by pixel.
        lowered_page = text.lower()
        _page_words = ("page", "पेज", "first result", "pehla result", "pahla result",
                       "link", "search box", "searchbar", "omnibox", "address bar",
                       "addressbar", "सर्च बॉक्स")
        # A click verb alone can be a NATIVE app button ("Calculator me
        # equals dabao") - that stays with ui_interact. Only a click that
        # names no application is a page-level click.
        _names_an_app = any(word in lowered_page for word in _APP_WORDS)
        _click_verb = any(v in lowered_page for v in ("click", "dabao", "daba do", "दबाओ"))
        if (any(word in lowered_page for word in _page_words)
                or ((_click_verb or "scroll" in lowered_page or "स्क्रॉल" in lowered_page)
                    and not _names_an_app)):
            # A question about the page is a READING, not an action.
            if any(q in lowered_page for q in (
                    "kya hai", "kya dikh", "kya likha", "kya hai?",
                    "what's on", "what is on", "what does this page", "क्या है")) \
                    and ("page" in lowered_page or "पेज" in lowered_page):
                return TaskProfile(
                    domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                    deterministic=True, intent="browser_page_read", needs={"tools"},
                )
            if requests_external_action(text):
                if "scroll" in lowered_page or "स्क्रॉल" in lowered_page:
                    return TaskProfile(
                        domain=TaskDomain.SYSTEM, complexity=1,
                        deterministic=True, intent="browser_page_scroll", needs={"tools"},
                    )
                if "first result" in lowered_page or "pehla result" in lowered_page \
                        or "pahla result" in lowered_page:
                    return TaskProfile(
                        domain=TaskDomain.SYSTEM, complexity=1,
                        deterministic=True, intent="browser_first_result", needs={"tools"},
                    )
                if any(w in lowered_page for w in ("click", "dabao", "दबाओ", "daba")):
                    return TaskProfile(
                        domain=TaskDomain.SYSTEM, complexity=1,
                        deterministic=True, intent="browser_page_click", needs={"tools"},
                    )
                if any(w in lowered_page for w in ("likho", "type", "लिखो", "टाइप", "enter")):
                    return TaskProfile(
                        domain=TaskDomain.SYSTEM, complexity=1,
                        deterministic=True, intent="browser_page_type", needs={"tools"},
                    )

        # -- a NEW TAB inside the browser already in use -------------------
        #
        # "अभी जो मेरी Chrome की प्रोफ़ाइल ओपन है, उसमें न्यू टैब ओपन करो और
        # YouTube सर्च करो।" was classified app_launch: a generic Chrome
        # launch with a URL, opening a NEW window each time instead of a
        # tab in the window the user is looking at. A tab request names
        # the tab explicitly - route it to the tab capability, which
        # targets the EXISTING window.
        if _wants_new_tab(text) and requests_external_action(text):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, criticality="normal",
                deterministic=True, intent="browser_tab_open", needs={"tools"},
            )

        # Descriptions of browser state ("jo profile open hai...") are not
        # launch commands; see requests_external_action for the physical
        # session that proved this door needed closing.
        if (
            names_visible_browser
            and wants_to_see
            and requests_external_action(text)
            and not _URL.search(text)
            and not re.search(r"\b(?:[\w-]+\.)+(?:com|org|net|io|dev|space|in|co|ai)\b", text)
            and not _wants_new_tab(text)
        ):
            try:
                from app.desktop.app_launcher import ApplicationRegistry

                if ApplicationRegistry.resolve_browser_profile(text) is not None:
                    return TaskProfile(
                        domain=TaskDomain.SYSTEM, complexity=2, criticality="normal",
                        deterministic=True, intent="browser_profile_open", needs={"tools"},
                    )
            except Exception:
                pass  # profile discovery is best-effort; never blocks routing

        if names_visible_browser and wants_to_see and requests_external_action(text):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, criticality="normal",
                deterministic=True, intent="app_launch", needs={"tools"},
            )
        if url_match or wants_web or (wants_browser_app and (wants_web or url_match or "search" in text)):
            return TaskProfile(
                domain=TaskDomain.RESEARCH, complexity=3, deterministic=True,
                intent="web_browse", needs={"tools"},
            )

        # -- machine state answered natively (zero shell, zero model) -------
        #
        # "Python version bata", "kaunsa process sabse zyada RAM le raha
        # hai", "disk space kitna hai" are all direct OS reads. They used
        # to become `powershell -Command Get-Process` / `Get-Volume` /
        # `python --version` through a shell host, which is slower, can
        # fail on quoting, and was the single largest source of shell use
        # in ordinary operation.
        if any(
            phrase in text
            for phrase in (
                "python version", "version of python", "python ka version",
                "is python installed", "python installed", "python is installed",
                "node version", "is node installed", "node installed",
                "which python", "python kahan",
            )
        ):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                deterministic=True, intent="system_query", needs={"tools"},
            )
        if any(
            phrase in text
            for phrase in (
                "ram use", "ram usage", "memory use", "memory usage", "sabse zyada ram",
                "most memory", "highest memory", "top process", "which process",
                "kaunsa process", "konsa process", "cpu usage", "cpu use",
                "disk space", "disk usage", "free space", "storage kitna",
                "what time is it", "current date", "aaj ki date", "time kya",
            )
        ):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                deterministic=True, intent="system_query", needs={"tools"},
            )

        # -- terminal: genuine command-line work ----------------------------
        #
        # `powershell`/`command prompt` are deliberately NOT here. Asking
        # for PowerShell by name means "open the app" (handled by
        # app_launch above); it is never a reason to route ordinary work
        # through a shell.
        if any(
            phrase in text
            for phrase in (
                "run python", "use python", "execute python", "python script",
                "run the command", "run this command", "in the terminal",
                "run a command", "check the version", "what version of",
                "git version", "ffmpeg version", "ffmpeg",
                # Version control is genuine command-line work, and `git`
                # is a real executable VYOM runs directly - never through
                # a shell host.
                "git status", "git log", "git diff", "git branch",
            )
        ):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, criticality="normal", deterministic=True,
                intent="run_command", needs={"tools"},
            )
        if ("build" in text or "compile" in text) and ("project" in text or "this" in text):
            return TaskProfile(
                domain=TaskDomain.CODING, complexity=3, deterministic=True,
                intent="inspect_project_build", needs={"tools"},
            )
        if "test" in text and any(verb in text for verb in ("run", "execute", "check")):
            return TaskProfile(
                domain=TaskDomain.CODING, complexity=2, deterministic=True,
                intent="run_tests", needs={"tools"},
            )

        # -- live screen observation (zero model) ---------------------------
        # Placed before every other desktop rule: "screen pe kya hai?" is a
        # question about the world, and the only correct answer comes from
        # looking at it right now.
        asked = f"{text} {getattr(self, '_original', '')}"
        # "It didn't open" / "मुझे दिख नहीं रहा" is the user reporting that
        # the previous action failed. Answering it with a list of open
        # windows explains the problem back to them instead of fixing it;
        # the correct response is to find the target, bring it forward and
        # verify it is now visible. Checked BEFORE the screen questions,
        # which it would otherwise match.
        if any(phrase in asked for phrase in _NOT_VISIBLE_COMPLAINTS):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                criticality="normal", deterministic=True,
                intent="recover_visibility", needs={"tools"},
            )
        if any(phrase in asked for phrase in _SCREEN_QUESTIONS):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                deterministic=True, intent="screen_observe", needs={"tools"},
            )
        # "abhi jo screen open ki hai woh dikh rahi hai?" - the words are
        # spread across the sentence, so no fixed phrase catches it. Asking
        # about the SCREEN plus asking whether it can be SEEN is a request
        # for a reading, however the sentence is arranged.
        if ("screen" in asked or "स्क्रीन" in asked) and any(
            marker in asked for marker in
            ("dikh", "dekh", "दिख", "देख", "visible", "can you see", "you see", "show")
        ):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                deterministic=True, intent="screen_observe", needs={"tools"},
            )
        # "यह क्या है?" - a bare demonstrative with no subject of its own
        # points at what is in front of the user. It was answered from
        # business memory ("your website is Luxora") while a real window
        # reading taken twenty seconds earlier sat unused. A fresh
        # observation is the only honest answer.
        if is_bare_demonstrative_question(text) or is_bare_demonstrative_question(
                getattr(self, "_original", "")):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                deterministic=True, intent="screen_observe", needs={"tools"},
            )

        # -- Windows Settings pages ------------------------------------------
        # A named Settings page has its own protocol URI, so this never
        # needs a shell and never needs UI navigation.
        if "setting" in text and any(page in text for page in _SETTINGS_PAGES):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, criticality="normal",
                deterministic=True, intent="settings_open", needs={"tools"},
            )
        if any(f"{page} setting" in text or f"setting {page}" in text for page in _SETTINGS_PAGES):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, criticality="normal",
                deterministic=True, intent="settings_open", needs={"tools"},
            )

        # -- desktop applications -----------------------------------------
        launch_verb = any(
            text.startswith(verb) or f" {verb} " in f" {text} "
            for verb in ("open", "launch", "start", "run")
        )
        # Closing is as ordinary a PC command as opening. Its absence here
        # is why "Stop ho ja, close kar do app" fell through to the general
        # planner, which answered by OPENING Terminal, Chrome and Notepad -
        # the exact opposite of the instruction.
        # Speech-to-text mangles short words: the user said "close the
        # calculator" and the transcript read "the closer calculator". A
        # word that merely STARTS with a close verb still carries the
        # instruction, and refusing it sent a plain close to the general
        # planner, where it failed.
        close_verb = any(
            word.startswith(("close", "clos", "band", "quit", "exit", "shut"))
            for word in text.replace(".", " ").split()
        )
        names_app = any(app in text for app in _APP_WORDS)

        # BROWSER TARGET SEMANTICS. A browser is not one object:
        #   APP      "Chrome band karo"              -> close the browser
        #   PROFILE  "Goli AIOS profile kholo"       -> a signed-in identity
        #   TAB      "Chrome me YouTube close karo"  -> one page
        # Collapsing these closed the whole browser and lost every other
        # tab the user had open.
        wants_open = launch_verb or "switch" in text or "kholo" in text or "khol do" in text
        if "profile" in text and wants_open:
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, criticality="normal",
                deterministic=True, intent="browser_profile_open", needs={"tools"},
            )
        if close_verb and _names_browser_page(text):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, criticality="normal",
                deterministic=True, intent="browser_tab_close", needs={"tools"},
            )
        if any(phrase in text for phrase in ("kaun se tab", "kitne tab", "which tabs",
                                             "list tabs", "tabs dikhao", "show tabs",
                                             "show browser tabs", "open tabs")):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                deterministic=True, intent="browser_tab_list", needs={"tools"},
            )
        # "Close the app" / "close kar do app" / "isko band karo" names no
        # application, but it is still unambiguously a close instruction
        # about the window in front of the user. Leaving it unmatched sent
        # it to the general planner, which responded by OPENING Windows
        # Terminal, Chrome and Notepad.
        refers_to_current_app = any(
            word in text for word in ("app", "application", "window", "isko", "ise", "this", "yeh", "ye")
        )
        if close_verb and (names_app or refers_to_current_app):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, criticality="normal", deterministic=True,
                intent="app_close", needs={"tools"},
            )
        # Operating a control inside an application that is already open.
        # Checked before `app_launch` so "Calculator me 27 guna 43 karo"
        # drives the visible Calculator rather than launching a second one.
        # A calculation is a calculator job whether or not the user names
        # the app. "Calculate 1036 * 1036" only worked by accident - the
        # word "calculate" happens to contain "calc" - while "100 divided
        # by 4" fell through to a reasoning model to do arithmetic.
        if _arithmetic_request(text):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, criticality="normal", deterministic=True,
                intent="ui_interact", needs={"tools"},
            )
        if (names_app or " me " in f" {text} " or " mein " in f" {text} ") and any(
            verb in text for verb in _UI_VERBS
        ):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, criticality="normal", deterministic=True,
                intent="ui_interact", needs={"tools"},
            )
        if launch_verb and names_app and not _mentions_file_target(text):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=2, criticality="normal", deterministic=True,
                intent="app_launch", needs={"tools"},
            )
        # "XYZImpossibleApp kholo" is unmistakably an application launch,
        # just for something that may not exist. It still belongs to the
        # desktop capability, which resolves it natively and answers
        # NOT_FOUND. Letting it fall through to the general planner is how
        # a missing app turned into shell fishing and a whole-disk scan.
        if launch_verb and _looks_like_app_launch(text) and not _mentions_file_target(text):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, criticality="normal", deterministic=True,
                intent="app_launch", needs={"tools"},
            )

        # -- filesystem -----------------------------------------------------
        if _mentions_file_target(text) and any(verb in text for verb in _FILE_VERBS):
            if any(verb in text for verb in ("read", "contents of", "show me the content", "cat ")):
                return TaskProfile(
                    domain=TaskDomain.CODING, complexity=2, deterministic=True,
                    intent="fs_read", needs={"tools"},
                )
            if any(verb in text for verb in ("find", "search")):
                return TaskProfile(
                    domain=TaskDomain.CODING, complexity=2, deterministic=True,
                    intent="fs_search", needs={"tools"},
                )
            return TaskProfile(
                domain=TaskDomain.CODING, complexity=2, deterministic=True,
                intent="fs_list", needs={"tools"},
            )

        # -- the user's own profile (zero model) -----------------------------
        #
        # Asking VYOM what it remembers about you is an exact lookup in its
        # own database, and telling VYOM a fact about you is a write. Both
        # were routed to a reasoning model, so "Mera naam kya hai?" cost a
        # model call, and when the provider was rate limited VYOM could not
        # answer a question whose answer was sitting in its own store.
        _PROFILE_QUESTIONS = (
            "mera naam kya", "mera nam kya", "my name", "what is my name", "whats my name",
            "mera business kya", "mere business ka naam", "my business", "what is my business",
            "meri website kya", "my website", "what is my website",
            "mere baare me kya", "mere bare me kya", "what do you know about me",
            "kya yaad hai", "what do you remember about me",
            # Devanagari forms of the same questions.
            "मेरा नाम क्या", "मेरा नाम बता", "मेरे बिजनेस का नाम", "मेरा बिजनेस क्या",
            "मेरी वेबसाइट क्या", "मेरे बारे में क्या", "क्या याद है",
        )
        # A plain statement of a durable fact is a memory WRITE, already
        # performed deterministically before routing. Acknowledging it does
        # not need a model to compose a sentence.
        #
        # Checked BEFORE the question list: "My business is Alpha" contains
        # the phrase "my business", and reading a statement as a question
        # meant VYOM answered with what it already knew instead of
        # recording what it had just been told. The extractor itself
        # returns nothing for questions, so this cannot swallow one.
        from app.memory.consolidation import extract_durable_facts

        if extract_durable_facts(request):
            return TaskProfile(
                domain=TaskDomain.PERSONAL, complexity=1, latency_priority="high",
                deterministic=True, intent="profile_statement", needs=set(),
            )
        if any(phrase in asked for phrase in _PROFILE_QUESTIONS):
            return TaskProfile(
                domain=TaskDomain.PERSONAL, complexity=1, latency_priority="high",
                deterministic=True, intent="profile_recall", needs=set(),
            )

        # -- user feedback is not a tool request ----------------------------
        #
        # "You have also many mistake. I cannot like that." was routed to
        # the general planner, which chose filesystem_list and read the
        # contents of C:\VYOM Project\services\brain back to the user.
        # "गलत डाटा तुम ले रहे हो।" got a generic apology composed by the
        # model with no reference to what had actually happened.
        #
        # A complaint is about the work in flight. It is answered from
        # VYOM's OWN runtime state - active goal, last observation, last
        # failure - which is local, free and true.
        if any(
            phrase in text
            for phrase in (
                "you have mistake", "you have many mistake", "you have also many mistake",
                "many mistakes", "so many mistake", "lot of mistake",
                "i cannot like that", "i don't like that", "i dont like that",
                "you are wrong", "that is wrong", "wrong information", "wrong data",
                "galat data", "galat information", "galat kaam", "tum galat",
                "गलत डाटा", "गलत जानकारी", "गलत कर रहे", "तुम गलत",
                "you are not working", "kaam nahi kar rahe", "kaam nahi karta",
                "tum kuch nahi kar", "you did nothing", "nothing is working",
                "why you are saying", "you are lying", "jhooth bol",
                # 2026-08-19 physical session, verbatim. Each of these was
                # misrouted to the general planner, which "helpfully"
                # launched Calculator or recited the user's business back
                # at them. A complaint is feedback about the work in
                # flight - never an action request.
                "i cannot show", "i can't show", "cannot show on", "i cannot see",
                "i can't see", "not showing", "not visible on", "cannot display",
                "kyun open kiya", "kyu open kiya", "kyun kiya", "kyu kiya",
                "why did you open", "why did you launch", "why you open",
                "why did you start", "why you started",
                "bola hi nahi", "i did not ask", "i didn't ask", "i never asked",
                "you are not a perfect", "you are not perfect", "not perfect",
                "again and again you", "why again and again", "baar baar",
                "why you speech", "you speech to my",
                "तुम परफेक्ट नहीं", "क्यों खोला", "क्यूं खोला", "बोला ही नहीं",
                "मैंने नहीं बोला", "बार बार",
            )
        ):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                deterministic=True, intent="user_feedback", needs=set(),
            )

        # -- live runtime introspection (zero model) ------------------------
        if any(
            phrase in text
            for phrase in (
                "what are you doing", "what are you working on", "abhi kya kar rahe ho",
                "kya kar rahe ho", "abhi kya kar rahi ho", "tum kya kar rahe ho",
                "why is it taking", "itna time kyu", "itna time kyon", "kitna time",
                "kaunsi process", "kaun si process", "what is taking so long",
                "status of the task", "current task", "abhi kya chal raha",
                # Asking WHY something failed is a question about VYOM's own
                # runtime state. It was being routed to the reasoning
                # provider - so when that provider was the thing failing,
                # VYOM called the rate-limited model to ask why it was rate
                # limited, and failed again. The answer is in local state.
                "why is it failing", "why did that fail", "why did it fail",
                "why this request", "why are you failing", "again and again failed",
                # "Why he cannot play for me?" was answered by the model
                # with "I do not have the capability to play or perform
                # physical actions" - said by a runtime that had launched
                # Chrome four times in the preceding three minutes. The
                # live capability registry outranks the model's opinion of
                # itself, and the real reason is in local state: the
                # previous mission had been cancelled by supersession.
                "why cannot you", "why can't you", "why cant you", "why he cannot",
                "why she cannot", "why it cannot", "why you cannot", "why not working",
                "kyu nahi kar", "kyun nahi kar", "kyu nahi ho", "kyun nahi ho",
                "क्यों नहीं कर", "क्यों नहीं हो",
                "why failed", "kyu fail", "kyun fail", "क्यों फेल", "क्यों नहीं",
                "which provider", "rate limited", "rate limit", "quota",
                "why is it taking so long", "why so slow", "kitna time lagega",
                "क्या कर रहे हो", "क्या हो रहा है", "क्यों रुका",
            )
        ):
            return TaskProfile(
                domain=TaskDomain.SYSTEM, complexity=1, latency_priority="high",
                deterministic=True, intent="runtime_introspection", needs=set(),
            )

        # -- "what is going on" -> real local sources, never invented -------
        if any(
            phrase in text
            for phrase in (
                "what's happening today", "whats happening today", "what is happening today",
                "what's going on", "whats going on", "brief me", "catch me up",
                "what happened today", "give me an update",
            )
        ):
            return TaskProfile(
                domain=TaskDomain.PERSONAL, complexity=2, deterministic=True,
                intent="situation_report", needs={"tools"},
            )

        return None
