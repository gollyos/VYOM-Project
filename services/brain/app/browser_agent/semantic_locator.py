from __future__ import annotations

import re


class SemanticLocator:
    """Resolves a human description of an element to a resilient selector
    instead of a brittle fixed coordinate or a single hard-coded selector."""

    ROLE_HINTS: dict[str, list[str]] = {
        "submit": ["button[type=submit]", "input[type=submit]", "[role=button]"],
        "button": ["button", "[role=button]", "input[type=submit]"],
        "email": ["input[type=email]", "input[name*=email i]", "input[id*=email i]"],
        "password": ["input[type=password]"],
        "search": ["input[type=search]", "input[name*=search i]", "[role=search] input"],
        "checkbox": ["input[type=checkbox]"],
        "link": ["a[href]"],
    }

    def locate(self, description: str) -> str:
        normalized = description.strip().lower()
        for role, selectors in self.ROLE_HINTS.items():
            if role in normalized:
                return selectors[0]
        text = re.sub(r"[\"']", "", description.strip())
        return f"text={text}"

    def alternatives(self, description: str) -> list[str]:
        normalized = description.strip().lower()
        text = re.sub(r"[\"']", "", description.strip())
        candidates = [self.locate(description), f"text={text}", f"[aria-label*='{text}' i]", f"[title*='{text}' i]"]
        # Preserve order while removing duplicates.
        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                ordered.append(candidate)
        return ordered
