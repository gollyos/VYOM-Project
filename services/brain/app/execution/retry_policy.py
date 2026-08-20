from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 2
    base_delay_seconds: float = 0.15

    def delay_for(self, attempt: int) -> float:
        return self.base_delay_seconds * max(attempt, 1)
