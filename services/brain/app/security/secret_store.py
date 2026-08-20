from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from app.integrations.secrets import (
    InMemorySecretVault,
    SecretVault,
    UnavailableSecretVault,
    WindowsDPAPISecretVault,
)


class SecretStoreError(Exception):
    pass


@dataclass
class SecretMetadata:
    ref: str
    kind: str            # provider | oauth | mcp | integration | device | broker
    owner: str           # e.g. "openai", "gmail", "node:abc"
    created_at: datetime
    rotated_at: datetime | None = None
    last_used_at: datetime | None = None
    source: str = "vault"  # vault | environment


class SecretBackend(Protocol):
    def set(self, key: str, value: bytes) -> None: ...
    def get(self, key: str, ) -> bytes | None: ...
    def delete(self, key: str) -> None: ...


class SecretStore:
    """One interface for every secret in VYOM. Callers store and pass
    `secret_ref` strings (`provider/openai/default`); plaintext values
    exist only inside this trusted layer and the OS-secured backend.

    Backends: Windows DPAPI vault (default), an environment-variable
    backend for server deployments (`VYOM_SECRET_<KIND>_<OWNER>`), or
    the explicitly test-only in-memory vault. Secrets are never stored
    in React source, config YAML, application SQLite tables, memory,
    logs, or events."""

    def __init__(self, backend: SecretBackend | None = None, metadata_path=None):
        self.backend = backend
        self._metadata: dict[str, SecretMetadata] = {}
        self._metadata_path = metadata_path
        if self._metadata_path is not None:
            self._load_metadata()

    # -- construction helpers -------------------------------------------

    @classmethod
    def for_local_machine(cls, secrets_root, metadata_path=None) -> "SecretStore":
        try:
            backend = WindowsDPAPISecretVault(secrets_root)
        except RuntimeError:
            backend = UnavailableSecretVault()
        return cls(backend, metadata_path=metadata_path)

    @classmethod
    def for_server_environment(cls, mapping: dict[str, str] | None = None, metadata_path=None) -> "SecretStore":
        return cls(EnvironmentSecretBackend(mapping), metadata_path=metadata_path)

    @classmethod
    def for_tests(cls) -> "SecretStore":
        return cls(InMemorySecretVault())

    # -- ref helpers ------------------------------------------------------

    @staticmethod
    def build_ref(kind: str, owner: str, slot: str = "default") -> str:
        for part in (kind, owner, slot):
            if not part or "/" in part:
                raise SecretStoreError(f"Invalid secret ref component {part!r}")
        return f"{kind}/{owner}/{slot}"

    def _key(self, ref: str) -> str:
        return f"vyom:{ref}"

    # -- core API ----------------------------------------------------------

    def set_secret(self, ref: str, value: str, *, kind: str, owner: str) -> SecretMetadata:
        self._require_backend()
        self.backend.set(self._key(ref), value.encode("utf-8"))
        metadata = self._metadata.get(ref) or SecretMetadata(
            ref=ref, kind=kind, owner=owner, created_at=datetime.now(timezone.utc),
        )
        metadata.rotated_at = datetime.now(timezone.utc)
        self._metadata[ref] = metadata
        self._save_metadata()
        return metadata

    def get_secret(self, ref: str) -> str:
        """Retrieve inside the trusted execution layer only. Records a
        last-used stamp; never logs the value."""
        self._require_backend()
        raw = self.backend.get(self._key(ref))
        if raw is None:
            raise SecretStoreError(f"Secret {ref} is not stored")
        metadata = self._metadata.get(ref)
        if metadata is not None:
            metadata.last_used_at = datetime.now(timezone.utc)
            self._save_metadata()
        return raw.decode("utf-8")

    def has_secret(self, ref: str) -> bool:
        self._require_backend()
        return self.backend.get(self._key(ref)) is not None

    def delete_secret(self, ref: str) -> bool:
        self._require_backend()
        existed = self.has_secret(ref)
        self.backend.delete(self._key(ref))
        self._metadata.pop(ref, None)
        self._save_metadata()
        return existed

    def rotate_secret(self, ref: str, new_value: str) -> SecretMetadata:
        metadata = self._metadata.get(ref)
        if metadata is None:
            raise SecretStoreError(f"Cannot rotate unknown secret {ref}")
        return self.set_secret(ref, new_value, kind=metadata.kind, owner=metadata.owner)

    def list_secret_metadata(self) -> list[SecretMetadata]:
        """Metadata only — this API can never return secret values."""
        return sorted(self._metadata.values(), key=lambda item: item.ref)

    # -- metadata persistence ----------------------------------------------

    def _save_metadata(self) -> None:
        if self._metadata_path is None:
            return
        import json

        payload = [
            {
                "ref": item.ref, "kind": item.kind, "owner": item.owner,
                "created_at": item.created_at.isoformat(),
                "rotated_at": item.rotated_at.isoformat() if item.rotated_at else None,
                "last_used_at": item.last_used_at.isoformat() if item.last_used_at else None,
                "source": item.source,
            }
            for item in self._metadata.values()
        ]
        self._metadata_path.parent.mkdir(parents=True, exist_ok=True)
        self._metadata_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _load_metadata(self) -> None:
        import json

        if not self._metadata_path.exists():
            return
        try:
            payload = json.loads(self._metadata_path.read_text(encoding="utf-8"))
        except Exception:
            return
        for item in payload:
            self._metadata[item["ref"]] = SecretMetadata(
                ref=item["ref"], kind=item["kind"], owner=item["owner"],
                created_at=datetime.fromisoformat(item["created_at"]),
                rotated_at=datetime.fromisoformat(item["rotated_at"]) if item.get("rotated_at") else None,
                last_used_at=datetime.fromisoformat(item["last_used_at"]) if item.get("last_used_at") else None,
                source=item.get("source", "vault"),
            )

    def _require_backend(self) -> None:
        if self.backend is None:
            raise SecretStoreError("No secret backend configured for this process")


class EnvironmentSecretBackend:
    """Server deployment backend: secrets come from the process
    environment (set by a secret manager), never from disk."""

    def __init__(self, mapping: dict[str, str] | None = None):
        self.mapping = mapping if mapping is not None else dict(os.environ)

    def set(self, key: str, value: bytes) -> None:
        raise SecretStoreError("Environment secrets are read-only; rotate them in the secret manager")

    def get(self, key: str) -> bytes | None:
        env_name = "VYOM_SECRET_" + key.replace("vyom:", "").replace("/", "_").upper()
        value = self.mapping.get(env_name)
        return value.encode("utf-8") if value else None

    def delete(self, key: str) -> None:
        raise SecretStoreError("Environment secrets are read-only")
