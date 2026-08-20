from __future__ import annotations

from .schemas import Contact, ContactResolution


class ContactResolver:
    def __init__(self, contacts: list[Contact] | None = None) -> None:
        self.contacts = list(contacts or [])

    def replace(self, contacts: list[Contact]) -> None:
        self.contacts = list(contacts)

    def resolve(self, query: str) -> ContactResolution:
        normalized = query.strip().casefold()
        exact = [item for item in self.contacts if normalized in {item.display_name.casefold(), *(email.casefold() for email in item.emails)}]
        matches = exact or [item for item in self.contacts if normalized in item.display_name.casefold() or any(normalized in email.casefold() for email in item.emails)]
        if len(matches) == 1:
            return ContactResolution(query=query, status="resolved", contact=matches[0], reason="One unique contact matched")
        if len(matches) > 1:
            return ContactResolution(query=query, status="ambiguous", candidates=matches, reason="Multiple contacts matched; user confirmation is required")
        return ContactResolution(query=query, status="not_found", reason="No contact matched")
