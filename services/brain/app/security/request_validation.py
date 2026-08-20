from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Base for security-relevant request models: unknown fields are
    rejected instead of silently passing through."""

    model_config = ConfigDict(extra="forbid")


class PayloadTooLargeError(Exception):
    pass


class RequestValidator:
    """Body-size limits and strict schema enforcement for external
    inputs (API requests, remote commands)."""

    def __init__(self, max_body_bytes: int = 1_000_000, max_fields: int = 200):
        self.max_body_bytes = max_body_bytes
        self.max_fields = max_fields

    def check_size(self, body: bytes | str) -> None:
        size = len(body) if isinstance(body, (bytes, bytearray)) else len(body.encode("utf-8"))
        if size > self.max_body_bytes:
            raise PayloadTooLargeError(f"Payload {size} bytes exceeds limit {self.max_body_bytes}")

    def check_field_count(self, data: dict[str, Any]) -> None:
        if len(data) > self.max_fields:
            raise ValueError(f"Payload has {len(data)} fields; limit is {self.max_fields}")

    def validate(self, model_class: type[BaseModel], data: dict[str, Any]) -> BaseModel:
        self.check_field_count(data)
        return model_class.model_validate(data)
