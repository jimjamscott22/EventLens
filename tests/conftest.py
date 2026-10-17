from datetime import datetime, timedelta, timezone

import pytest

from eventlens.models import Event, Level

BASE_TIME = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def build_event(
    provider: str,
    event_id: int,
    *,
    minutes: float = 0,
    level: Level = Level.ERROR,
    data: dict[str, str] | None = None,
    channel: str = "System",
    computer: str = "TEST-PC",
) -> Event:
    """An event ``minutes`` after BASE_TIME."""
    return Event(
        provider=provider,
        event_id=event_id,
        level=level,
        time=BASE_TIME + timedelta(minutes=minutes),
        channel=channel,
        computer=computer,
        data=data or {},
    )


@pytest.fixture
def make_event():
    return build_event
