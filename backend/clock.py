"""서버 시계와 현지 날짜(2a-0).

근로자 '오늘'은 배정의 scheduled_day(현지 날짜, DATE)로 정한다. 현지 날짜는 APP_UTC_OFFSET_HOURS(기본 9, KST) 기준이다.
시험이 날짜를 옮길 수 있게 지금 시각은 이 모듈의 utcnow() 하나에서 읽는다(monkeypatch 대상).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone


def offset_hours() -> int:
    return int(os.getenv("APP_UTC_OFFSET_HOURS", "9"))


def utcnow() -> datetime:
    """naive UTC(DB 저장 형식)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_date(dt: datetime | None) -> date | None:
    """naive UTC(또는 시간대 있는) 시각의 현지 날짜."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return (dt + timedelta(hours=offset_hours())).date()


def local_today() -> date:
    return local_date(utcnow())
