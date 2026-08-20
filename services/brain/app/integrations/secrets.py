from __future__ import annotations

import ctypes
import hashlib
import os
from abc import ABC, abstractmethod
from ctypes import wintypes
from pathlib import Path


class SecretVault(ABC):
    @abstractmethod
    def set(self, key: str, value: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes | None: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...


class InMemorySecretVault(SecretVault):
    """Tests only. Production assembly never selects this vault."""

    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    def set(self, key: str, value: bytes) -> None:
        self._values[key] = bytes(value)

    def get(self, key: str) -> bytes | None:
        value = self._values.get(key)
        return bytes(value) if value is not None else None

    def delete(self, key: str) -> None:
        self._values.pop(key, None)


class UnavailableSecretVault(SecretVault):
    def set(self, key: str, value: bytes) -> None:
        raise RuntimeError("No OS-backed secret vault is available")

    def get(self, key: str) -> bytes | None:
        return None

    def delete(self, key: str) -> None:
        return None


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


class WindowsDPAPISecretVault(SecretVault):
    """Stores only Windows-current-user DPAPI ciphertext on disk."""

    CRYPTPROTECT_UI_FORBIDDEN = 0x1

    def __init__(self, root: Path) -> None:
        if os.name != "nt":
            raise RuntimeError("OS-backed secret storage is unavailable on this platform")
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    def _path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.dpapi"

    @staticmethod
    def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data)
        return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer

    def _protect(self, value: bytes) -> bytes:
        source, source_buffer = self._blob(value)
        output = _DataBlob()
        if not self._crypt32.CryptProtectData(
            ctypes.byref(source), "VYOM integration token", None, None, None,
            self.CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)
            del source_buffer

    def _unprotect(self, value: bytes) -> bytes:
        source, source_buffer = self._blob(value)
        output = _DataBlob()
        if not self._crypt32.CryptUnprotectData(
            ctypes.byref(source), None, None, None, None,
            self.CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(output),
        ):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(output.pbData, output.cbData)
        finally:
            self._kernel32.LocalFree(output.pbData)
            del source_buffer

    def set(self, key: str, value: bytes) -> None:
        sealed = self._protect(value)
        path = self._path(key)
        temporary = path.with_suffix(".tmp")
        temporary.write_bytes(sealed)
        temporary.replace(path)

    def get(self, key: str) -> bytes | None:
        path = self._path(key)
        return self._unprotect(path.read_bytes()) if path.exists() else None

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()
