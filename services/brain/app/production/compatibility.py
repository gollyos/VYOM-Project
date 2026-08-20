from __future__ import annotations

from dataclasses import dataclass

APP_VERSION = "0.2.0"
BRAIN_VERSION = "0.2.0"
SCHEMA_VERSION = 1
PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class VersionInfo:
    app_version: str = APP_VERSION
    brain_version: str = BRAIN_VERSION
    schema_version: int = SCHEMA_VERSION
    protocol_version: int = PROTOCOL_VERSION

    def as_dict(self) -> dict:
        return {
            "app_version": self.app_version,
            "brain_version": self.brain_version,
            "schema_version": self.schema_version,
            "protocol_version": self.protocol_version,
        }


class CompatibilityError(Exception):
    pass


class CompatibilityChecker:
    """Deterministic version-compatibility matrix between this build
    and a database schema version or a node's reported versions."""

    MIN_SUPPORTED_SCHEMA = 1
    MAX_SUPPORTED_SCHEMA = 1
    MIN_SUPPORTED_PROTOCOL = 1
    MAX_SUPPORTED_PROTOCOL = 1

    def check_schema(self, schema_version: int) -> None:
        if not (self.MIN_SUPPORTED_SCHEMA <= schema_version <= self.MAX_SUPPORTED_SCHEMA):
            raise CompatibilityError(
                f"Database schema v{schema_version} is outside the supported range "
                f"[{self.MIN_SUPPORTED_SCHEMA}, {self.MAX_SUPPORTED_SCHEMA}]; "
                "restore a compatible backup or run the documented migration/rollback path"
            )

    def check_node(self, *, protocol_version: int, schema_version: int) -> None:
        if not (self.MIN_SUPPORTED_PROTOCOL <= protocol_version <= self.MAX_SUPPORTED_PROTOCOL):
            raise CompatibilityError(f"Node protocol v{protocol_version} incompatible with this coordinator")
        if not (self.MIN_SUPPORTED_SCHEMA <= schema_version <= self.MAX_SUPPORTED_SCHEMA):
            raise CompatibilityError(f"Node schema v{schema_version} incompatible with this coordinator")
