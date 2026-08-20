from __future__ import annotations

from dataclasses import dataclass, field

MAX_BULLETS_PER_SLIDE = 5
MAX_BULLET_CHARS = 140


@dataclass
class Slide:
    title: str
    bullets: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class SlideDeckSpec:
    title: str
    audience: str
    purpose: str
    slides: list[Slide] = field(default_factory=list)


class PresentationBuilder:
    """audience -> purpose -> narrative -> slide structure. Bounded bullet
    counts and lengths keep decks from becoming giant text-heavy walls."""

    def build(self, *, title: str, audience: str, purpose: str, narrative: list[tuple[str, list[str]]]) -> SlideDeckSpec:
        slides = [
            Slide(title=slide_title, bullets=[bullet[:MAX_BULLET_CHARS] for bullet in bullets[:MAX_BULLETS_PER_SLIDE]])
            for slide_title, bullets in narrative
        ]
        return SlideDeckSpec(title=title, audience=audience, purpose=purpose, slides=slides)

    @staticmethod
    def validate(spec: SlideDeckSpec) -> list[str]:
        errors: list[str] = []
        if not spec.slides:
            errors.append("Presentation has no slides")
        for slide in spec.slides:
            if len(slide.bullets) > MAX_BULLETS_PER_SLIDE:
                errors.append(f"Slide '{slide.title}' exceeds the bounded bullet count")
        return errors
