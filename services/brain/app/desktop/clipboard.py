from __future__ import annotations

from .schemas import ClipboardEntry

try:
    import pyperclip
    PYPERCLIP_AVAILABLE = True
except ImportError:
    PYPERCLIP_AVAILABLE = False

SENSITIVE_HINTS = ("password", "secret", "api_key", "api key", "private key", "-----begin", "token=")


class ClipboardUnavailableError(Exception):
    pass


class ClipboardController:
    """clipboard.read / write / clear. Reads are deliberate, single-shot,
    and always event-emitting through the `desktop` tool -- this module
    never polls the clipboard continuously. Sensitive-looking content is
    flagged so callers never persist it into memory."""

    def read(self) -> tuple[str, ClipboardEntry]:
        if not PYPERCLIP_AVAILABLE:
            raise ClipboardUnavailableError("Clipboard access requires pyperclip")
        content = pyperclip.paste() or ""
        return content, ClipboardEntry(content_type="text", length=len(content))

    def write(self, content: str) -> ClipboardEntry:
        if not PYPERCLIP_AVAILABLE:
            raise ClipboardUnavailableError("Clipboard access requires pyperclip")
        pyperclip.copy(content)
        return ClipboardEntry(content_type="text", length=len(content))

    def clear(self) -> ClipboardEntry:
        return self.write("")

    @staticmethod
    def looks_sensitive(content: str) -> bool:
        lowered = content.lower()
        return any(hint in lowered for hint in SENSITIVE_HINTS)
