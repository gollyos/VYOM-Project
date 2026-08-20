from __future__ import annotations

from .schemas import ContentSection

STANDARD_REPORT_SECTIONS = [
    "Executive Summary", "Findings", "Data", "Recommendations", "Risks", "Evidence / Sources", "Next Actions",
]


def build_report_sections(data: dict[str, ContentSection | str]) -> list[ContentSection]:
    """Reusable professional report layout. Sections appear in a fixed,
    predictable order; only sections with content are included."""
    sections: list[ContentSection] = []
    for name in STANDARD_REPORT_SECTIONS:
        value = data.get(name)
        if value is None:
            continue
        sections.append(value if isinstance(value, ContentSection) else ContentSection(heading=name, body=str(value)))
    return sections
