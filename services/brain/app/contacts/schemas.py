from __future__ import annotations

from pydantic import BaseModel, Field


class Contact(BaseModel):
    id: str
    display_name: str
    emails: list[str] = Field(default_factory=list)
    company: str | None = None
    source: str = "crm"


class ContactResolution(BaseModel):
    query: str
    status: str
    contact: Contact | None = None
    candidates: list[Contact] = Field(default_factory=list)
    reason: str
