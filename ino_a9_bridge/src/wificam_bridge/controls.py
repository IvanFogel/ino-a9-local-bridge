"""Typed, non-secret values for the observed INO-A9 controls."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True, slots=True)
class IntrusionSchedule:
    """A non-crossing, minute-precision weekly intrusion schedule."""

    days: tuple[int, ...]
    start: time
    end: time

    def __post_init__(self) -> None:
        days = tuple(self.days)
        if not days:
            raise ValueError("schedule days must not be empty")
        if any(isinstance(day, bool) or not isinstance(day, int) or not 0 <= day <= 6 for day in days):
            raise ValueError("schedule days must contain unique values from 0 through 6")
        if days != tuple(sorted(set(days))):
            raise ValueError("schedule days must be unique and sorted")
        object.__setattr__(self, "days", days)
        for label, value in (("start", self.start), ("end", self.end)):
            if not isinstance(value, time):
                raise TypeError(f"schedule {label} must be a time")
            if value.tzinfo is not None or value.second or value.microsecond:
                raise ValueError(f"schedule {label} must have minute precision")
        if self.start > self.end:
            raise ValueError("schedule must not cross midnight")
