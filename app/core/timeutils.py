"""Работа с часовым поясом бизнеса (даты осмотров считаются по местному времени)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.core.config import get_settings


@lru_cache
def business_tz() -> ZoneInfo:
    """Возвращает часовой пояс, в котором ведутся журналы."""
    return ZoneInfo(get_settings().business_timezone)


def to_local(value: datetime) -> datetime:
    """Переводит момент времени в часовой пояс бизнеса."""
    return value.astimezone(business_tz())


def local_date(value: datetime) -> date:
    """Возвращает календарную дату момента в часовом поясе бизнеса."""
    return to_local(value).date()


def local_day_bounds(
    start: date | None, end: date | None
) -> tuple[datetime | None, datetime | None]:
    """Границы местных суток: [начало первого дня; начало дня после последнего).

    Диапазон по `timestamptz` использует индекс, в отличие от выражения «дата по местному времени».
    """
    tz = business_tz()
    lower = datetime.combine(start, time.min, tzinfo=tz) if start else None
    upper = datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz) if end else None
    return lower, upper
