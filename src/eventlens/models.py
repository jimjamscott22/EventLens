"""Core data types shared across EventLens."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class Level(IntEnum):
    """Windows event levels. Lower numbers are more severe."""

    LOG_ALWAYS = 0
    CRITICAL = 1
    ERROR = 2
    WARNING = 3
    INFORMATION = 4
    VERBOSE = 5

    @classmethod
    def from_value(cls, value: int) -> Level:
        try:
            return cls(value)
        except ValueError:
            return cls.INFORMATION

    @property
    def label(self) -> str:
        if self is Level.LOG_ALWAYS:
            return "Information"
        return self.name.capitalize()


@dataclass(frozen=True)
class Event:
    """One entry from a Windows event log."""

    provider: str
    event_id: int
    level: Level
    time: datetime
    channel: str = ""
    computer: str = ""
    message: str = ""
    data: dict[str, str] = field(default_factory=dict, compare=False, hash=False)

    @property
    def is_problem(self) -> bool:
        """True for critical events and errors."""
        return self.level in (Level.CRITICAL, Level.ERROR)
