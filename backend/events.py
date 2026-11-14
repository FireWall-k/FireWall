"""측정 이벤트(2c, contract §5.2, 명세 8.4). POST /api/events → 204.

- 근로자·사업주 토큰 모두 받는다. 이름은 역할마다 정한 목록만 받는다(다른 이름이 하나라도 있으면 422).
- 저장하는 칸: 사업장 id, 누가(worker|employer 종류만), 이름, 직무·단계 id, 숫자 값, 시각. 이름·문장·근로자 id 같은
  개인정보 칸은 없다. 직무 id는 이 사업장 직무일 때만 남기고, 아니면 비운다.
- 시각은 기기 시각(at)을 [지금 - 1일, 지금 + 5분] 안으로 자른다(엉터리 시각은 서버 시각).
- 화면은 이벤트 실패를 보여 주지 않고, 근로자 쪽은 오프라인 대기열에 넣지 않는다.
- (3b-1) 사용 측정 이벤트(명세 8.4)를 더했다: step_done, tap_debounced, help_cancel, exit_confirm/exit_cancel,
  offline_queued/offline_flushed, coach_override(선생님 모드는 3b-2 — 그때 화면에서 보낸다). step_back_quick은
  만들지 않는다(보고서가 step_done·step_prev 시각으로 계산). 옛 이름 step_prev·step_replay는 그대로다.
- (3b-1, 0012) 근로자 이벤트의 assignment_id는 이 근로자 본인의 배정일 때만 남긴다(가명 정보, 사업주 이벤트는 늘 비움).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

import clock
from database import get_db
from deps import any_user
from models import Assignment, ClientEvent, Task, Worker
from ratelimit import LoginThrottle
from schemas import EventsIn

router = APIRouter()

WORKER_EVENTS = frozenset({
    "step_view", "step_replay", "step_prev", "help_open",
    # (3b-1) 사용 측정(명세 8.4).
    "step_done", "tap_debounced", "help_cancel", "exit_confirm", "exit_cancel",
    "offline_queued", "offline_flushed", "coach_override",
})
EMPLOYER_EVENTS = frozenset({"task_create_start", "task_send_done", "send_click_disabled", "send_click_count"})
MSG_BAD_NAME = "보낼 수 없는 기록이에요."
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_AGE = timedelta(days=1)
_SKEW = timedelta(minutes=5)

# 토큰 주인마다 분당 60번(한 번에 50건까지). 넘으면 429(화면은 버린다).
events_throttle = LoginThrottle(max_failures=60, window_sec=60)


def _at(value: datetime | None, now: datetime) -> datetime:
    if value is None:
        return now
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    if value > now + _SKEW or value < now - _MAX_AGE:
        return now
    return value


def _clean_id(value: str | None) -> str | None:
    return value if value and _ID_RE.match(value) else None


@router.post("/api/events", status_code=204)
def post_events(payload: EventsIn, db: Session = Depends(get_db), user: dict = Depends(any_user)) -> Response:
    role = user.get("role")
    allowed = WORKER_EVENTS if role == "worker" else EMPLOYER_EVENTS
    if any(e.name not in allowed for e in payload.events):
        raise HTTPException(status_code=422, detail=MSG_BAD_NAME)
    key = f"events:{role}:{user['sub']}"
    if events_throttle.retry_after(key):
        raise HTTPException(status_code=429, detail="잠깐 뒤에 다시 보내 주세요.")
    events_throttle.fail(key)
    mine: set[str] = set()
    if role == "worker":
        w = db.get(Worker, user["sub"])
        employer_id = w.employer_id
        aids = {a for a in (_clean_id(e.assignment_id) for e in payload.events) if a}
        if aids:
            mine = set(db.scalars(select(Assignment.id).where(Assignment.id.in_(aids),
                                                              Assignment.worker_id == w.id)).all())
    else:
        employer_id = user["sub"]
    task_ids = {t for t in (_clean_id(e.task_id) for e in payload.events) if t}
    owned = set(db.scalars(select(Task.id).where(Task.id.in_(task_ids), Task.employer_id == employer_id)).all()
                ) if task_ids else set()
    now = clock.utcnow()
    for e in payload.events:
        tid = _clean_id(e.task_id)
        aid = _clean_id(e.assignment_id)
        db.add(ClientEvent(employer_id=employer_id, actor="worker" if role == "worker" else "employer",
                           name=e.name, task_id=tid if tid in owned else None, step_id=_clean_id(e.step_id),
                           assignment_id=aid if aid in mine else None,
                           value_num=e.value_num, created_at=_at(e.at, now)))
    db.commit()
    return Response(status_code=204)
