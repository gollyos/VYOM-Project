from __future__ import annotations

from .schemas import BookingConstraints, BookingOption


class BookingComparator:
    """Compares researched options. Important constraints are never
    silently relaxed; when an exact match is unavailable, alternatives are
    surfaced with their relaxed_constraints explicitly labeled."""

    def rank(self, options: list[BookingOption], constraints: BookingConstraints) -> list[BookingOption]:
        def score(option: BookingOption) -> float:
            value = 1.0 if option.matches_constraints else 0.5
            value -= 0.1 * len(option.relaxed_constraints)
            if constraints.budget and option.price is not None:
                value += 0.2 if option.price <= constraints.budget else -0.3
            if option.rating:
                value += min(0.2, option.rating / 25)
            return value

        return sorted(options, key=score, reverse=True)

    @staticmethod
    def exact_matches(options: list[BookingOption]) -> list[BookingOption]:
        return [option for option in options if option.matches_constraints]

    @staticmethod
    def alternatives(options: list[BookingOption]) -> list[BookingOption]:
        return [option for option in options if not option.matches_constraints]
