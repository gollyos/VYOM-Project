"""Decoding for subprocess output captured on Windows.

Child processes emit whatever encoding their session uses, not always
UTF-8: localized Windows tools and node/npm write cp1252 or the OEM
codepage. Decoding implicitly as UTF-8 turned those bytes into U+FFFD
mojibake, and one strict `bytes.decode()` in the Git tool raised
UnicodeDecodeError and failed the whole call. UTF-8 is tried first -
it is the overwhelmingly common case for developer tooling - and the
machine's local codepage is the fallback, with replacement characters
only where even that fails. The honest best effort for mixed output.
"""
from __future__ import annotations

import locale

_FALLBACK_ENCODING: str | None = None


def fallback_encoding() -> str:
    """The machine's real ANSI codepage (e.g. cp1252), computed once.

    `locale.getpreferredencoding()` reports utf-8 whenever Python runs in
    UTF-8 mode, which would make the fallback identical to the primary
    decode and useless - so on Windows the actual codepage is read from
    the OS instead."""
    global _FALLBACK_ENCODING
    if _FALLBACK_ENCODING is None:
        encoding = ""
        import sys

        if sys.platform == "win32":
            try:
                import ctypes

                encoding = f"cp{ctypes.windll.kernel32.GetACP()}"
            except Exception:
                encoding = ""
        if not encoding or encoding.lower() in {"utf-8", "utf8"}:
            encoding = locale.getpreferredencoding(False) or "cp1252"
        if encoding.lower() in {"utf-8", "utf8"}:
            # UTF-8 mode masked the real codepage; the ANSI default is the
            # honest guess for localized Windows tool output.
            encoding = "cp1252"
        _FALLBACK_ENCODING = encoding
    return _FALLBACK_ENCODING


def decode_output(data: bytes) -> str:
    """Decode captured subprocess output: UTF-8 first, local codepage
    fallback. Never raises."""
    if not data:
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode(fallback_encoding(), errors="replace")
