from __future__ import annotations

from dataclasses import dataclass

from .redaction import REDACTED
from .secret_store import SecretStore, SecretStoreError


class UnknownCredentialError(Exception):
    pass


@dataclass
class CredentialSpec:
    """Describes one credential a consumer needs. Application data and
    provider config carry only the `secret_ref`, never values."""

    consumer: str        # e.g. "provider:openai", "integration:gmail"
    ref: str             # provider/openai/default
    env_fallback: str | None = None  # e.g. OPENAI_API_KEY


class CredentialManager:
    """Resolves secret references to values inside the trusted
    execution layer. Model prompts, tool inputs shown to users, logs,
    and events only ever see the ref."""

    def __init__(self, store: SecretStore, *, allow_env_fallback: bool = True):
        self.store = store
        self.allow_env_fallback = allow_env_fallback
        self._specs: dict[str, CredentialSpec] = {}

    def register(self, spec: CredentialSpec) -> CredentialSpec:
        self._specs[spec.consumer] = spec
        return spec

    def resolve(self, consumer: str) -> tuple[str, str]:
        """Returns (ref, value) or raises. Value never leaves the
        trusted layer; callers must not persist or log it."""
        spec = self._specs.get(consumer)
        ref = spec.ref if spec else self._default_ref(consumer)
        try:
            return ref, self.store.get_secret(ref)
        except SecretStoreError:
            env_name = spec.env_fallback if spec else None
            if self.allow_env_fallback and env_name:
                import os

                value = os.environ.get(env_name)
                if value:
                    return ref, value
            raise UnknownCredentialError(
                f"No credential stored for {consumer} (ref {ref}); configure it in setup"
            )

    def has_credentials(self, consumer: str) -> bool:
        spec = self._specs.get(consumer)
        ref = spec.ref if spec else self._default_ref(consumer)
        if self.store.has_secret(ref):
            return True
        if spec is not None and spec.env_fallback:
            import os

            return bool(os.environ.get(spec.env_fallback))
        return False

    @staticmethod
    def safe_describe(consumer: str, ref: str) -> dict[str, str]:
        """Log/audit-safe description — the value is never included."""
        return {"consumer": consumer, "secret_ref": ref, "value": REDACTED}

    @staticmethod
    def _default_ref(consumer: str) -> str:
        kind, _, owner = consumer.partition(":")
        return SecretStore.build_ref(kind or "integration", owner or "unknown", "default")
