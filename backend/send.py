"""보내기: 서버 보내기 검사·보내기·받는 사람(2a-0, contract §1.4).

- send-check: 그림 없는 단계(no_picture), 확인 안 한 자동 그림(unconfirmed_auto: auto_high·choose), 단계 없음(no_steps).
  화면 문구는 사업주 화면 copy.ts가 code와 숫자로 만든다(서버는 label을 보내지 않는다).
- send: 한 트랜잭션에서 검사 → 같은 내용이 아니면 새 버전 → 근로자마다 배정(규칙 5가지) → 감사 task.assign(근로자마다).
- publish(POST …/publish)와 옛 배정(POST …/assignments)도 같은 검사(ensure_sendable)·같은 배정 함수(send_to_workers)를 쓴다.
- 이 모듈은 main을 import하지 않는다(main이 이 라우터를 include한다).
"""
from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

import clock
import versions
from auth import require_employer
from database import get_db
from models import Assignment, HelpRequest, PerformanceLog, Task, Worker
from privacy import record_access, record_access_for_workers
from schemas import (
    RecipientsOut,
    SendBlockOut,
    SendCheckOut,
    SendRequest,
    SendResultItemOut,
    SendResultOut,
    SendWarnOut,
)

router = APIRouter()

# 내일 이후로 보낼 수 있는 가장 먼 날(현지 날짜 기준, 오늘 + 60일까지).
MAX_DAYS_AHEAD = 60

MSG_NO_STEPS = "단계가 하나도 없어요. 단계를 넣어 주세요."
MSG_ARCHIVED = "보관한 직무는 보낼 수 없어요. 보관함에서 꺼낸 뒤 보내 주세요."
MSG_NO_WORKER = "받는 사람을 찾지 못했어요. 목록을 새로 고친 뒤 다시 골라 주세요."
MSG_EMPTY_WORKERS = "받는 사람을 한 명 이상 골라 주세요."
MSG_PAST_DAY = "지난 날짜에는 보낼 수 없어요. 오늘이나 그 뒤 날짜를 골라 주세요."
MSG_FAR_DAY = "60일 안의 날짜를 골라 주세요."
MSG_BAD_DAY = "날짜를 다시 골라 주세요."


class ApiError(Exception):
    """{"detail", "code", "step_ids"} 모양 오류(contract §0). main이 처리기를 등록한다."""

    def __init__(self, status_code: int, detail: str, code: str | None = None,
                 step_ids: list[str] | None = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code
        self.step_ids = step_ids

    def body(self) -> dict:
        out: dict = {"detail": self.detail}
        if self.code is not None:
            out["code"] = self.code
        if self.step_ids is not None:
            out["step_ids"] = self.step_ids
        return out


def _owned_task(task_id: str, employer_id: str, db: Session) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.employer_id != employer_id:
        raise HTTPException(status_code=404, detail="직무를 찾을 수 없습니다.")
    return task


def _is_archived(task: Task) -> bool:
    return task.archived_at is not None or task.status == "archived"


# --- 검사 ------------------------------------------------------------------------------------

def send_check(task: Task) -> SendCheckOut:
    steps = sorted(task.steps, key=lambda s: s.order_index)
    states = [(s, versions.picture_state(s)) for s in steps]
    no_picture = [s.id for s, st in states if st == "none"]
    with_picture = [(s, st) for s, st in states if st != "none"]
    unconfirmed = [s.id for s, st in with_picture if st in ("auto_high", "choose")]
    blocking: list[SendBlockOut] = []
    if _is_archived(task):
        blocking.append(SendBlockOut(code="archived", done=0, total=1))
    if not steps:
        # 단계가 없을 때만 싣는다(있으면 통과한 줄이라 화면에 보일 것이 없다).
        blocking.append(SendBlockOut(code="no_steps", done=0, total=1))
    blocking.append(SendBlockOut(code="no_picture", done=len(steps) - len(no_picture), total=len(steps),
                                 step_ids=no_picture))
    blocking.append(SendBlockOut(code="unconfirmed_auto", done=len(with_picture) - len(unconfirmed),
                                 total=len(with_picture), step_ids=unconfirmed))
    # 나누기 검토(2b-1)는 아직 없다. total=0이라 화면에 보이지 않는다.
    blocking.append(SendBlockOut(code="unreviewed_split", done=0, total=0))
    warnings = [SendWarnOut(code=c, count=0) for c in ("too_long", "command_tone", "auto_caution")]
    ok = all(b.done >= b.total for b in blocking)
    return SendCheckOut(ok=ok, blocking=blocking, warnings=warnings)


def _orders_text(orders: list[int]) -> str:
    names = [f"{n}단계" for n in orders]
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + "와 " + names[-1]


def ensure_sendable(task: Task) -> None:
    """send-check가 막는 것이 있으면 오류를 낸다. 보내기·publish·옛 배정이 같이 쓴다."""
    if _is_archived(task):
        raise ApiError(409, MSG_ARCHIVED, code="archived", step_ids=[])
    steps = sorted(task.steps, key=lambda s: s.order_index)
    if not steps:
        raise ApiError(422, MSG_NO_STEPS, code="no_steps", step_ids=[])
    states = [(s, versions.picture_state(s)) for s in steps]
    missing = [s for s, st in states if st == "none"]
    if missing:
        raise ApiError(422, f"{_orders_text([s.order_index for s in missing])}에 그림이 없어요. "
                            "그림을 고르거나 사진을 올려 주세요.",
                       code="send_blocked", step_ids=[s.id for s in missing])
    unconfirmed = [s for s, st in states if st in ("auto_high", "choose")]
    if unconfirmed:
        raise ApiError(422, f"{_orders_text([s.order_index for s in unconfirmed])}의 그림을 아직 확인하지 "
                            "않았어요. 확인한 뒤 다시 보내 주세요.",
                       code="send_blocked", step_ids=[s.id for s in unconfirmed])


# --- 날짜 ------------------------------------------------------------------------------------

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def resolve_day(day: str | None, today: date | None = None) -> date:
    """"today"|"tomorrow"|"YYYY-MM-DD"(현지 날짜)를 날짜로. 지난 날짜·60일 넘게 뒤면 422."""
    today = today or clock.local_today()
    value = (day or "today").strip()
    if value == "today":
        return today
    if value == "tomorrow":
        return today + timedelta(days=1)
    if not _DAY_RE.match(value):
        raise ApiError(422, MSG_BAD_DAY, code="bad_day")
    try:
        picked = date.fromisoformat(value)
    except ValueError:
        raise ApiError(422, MSG_BAD_DAY, code="bad_day") from None
    if picked < today:
        raise ApiError(422, MSG_PAST_DAY, code="past_day")
    if picked > today + timedelta(days=MAX_DAYS_AHEAD):
        raise ApiError(422, MSG_FAR_DAY, code="day_too_far")
    return picked


def new_batch_id(now: datetime) -> str:
    """시각 순으로 정렬되는 묶음 id(가장 큰 값 = 마지막 보내기)."""
    return f"{now:%Y%m%d%H%M%S%f}-{uuid.uuid4().hex[:8]}"


# --- 배정 규칙(contract §1.4) ------------------------------------------------------------------

def _latest_same_day(db: Session, task_id: str, worker_id: str, day: date) -> Assignment | None:
    return db.scalar(select(Assignment).where(
        Assignment.task_id == task_id, Assignment.worker_id == worker_id, Assignment.scheduled_day == day,
    ).order_by(Assignment.assigned_date.desc(), Assignment.id.desc()).limit(1))


def _count(db: Session, model, *where) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*where)) or 0


def assign_one(db: Session, task: Task, version, worker_id: str, day: date, now: datetime,
               batch_id: str) -> tuple[str, Assignment]:
    """같은 근로자·직무·날의 가장 최근 배정을 보고 결과(outcome)와 배정을 돌려준다.

    | 그 날 배정이                         | 결과 |
    | 없음                                 | created(어제 못 끝낸 배정은 그대로 두고 새로 만든다) |
    | 아직 받지 않음(first_seen·로그·도움 0) | 버전이 다르면 repinned, 같으면 unchanged |
    | 받았지만 완료 로그 0건                 | kept(화면에 이미 떴을 수 있다 — 옛 버전 그대로) |
    | 하는 중(완료 로그 1건 이상)            | kept_in_progress(결정 5) |
    | 다 함                                 | created(한 번 더 하라는 뜻) |
    last_seen_at은 30초 간격으로만 바뀌어 이 판정에 쓰지 않는다. 배정마다 정확한 first_seen_at을 쓴다.
    """
    a = _latest_same_day(db, task.id, worker_id, day)
    if a is not None and a.status != "done":
        logs = _count(db, PerformanceLog, PerformanceLog.assignment_id == a.id)
        helps = _count(db, HelpRequest, HelpRequest.assignment_id == a.id)
        a.send_batch_id = batch_id
        if a.first_seen_at is None and logs == 0 and helps == 0:
            if a.task_version_id != version.id:
                a.task_version_id = version.id
                a.pinned_at = now
                return "repinned", a
            return "unchanged", a
        done_logs = _count(db, PerformanceLog, PerformanceLog.assignment_id == a.id,
                           PerformanceLog.completed.is_(True))
        return ("kept_in_progress" if done_logs else "kept"), a
    a = Assignment(task_id=task.id, worker_id=worker_id, status="assigned", assigned_date=now,
                   scheduled_day=day, task_version_id=version.id, pinned_at=now, send_batch_id=batch_id)
    db.add(a)
    db.flush()
    return "created", a


def _resolve_workers(db: Session, employer_id: str, worker_ids: list[str]) -> list[Worker]:
    ids = list(dict.fromkeys(w for w in worker_ids if w))
    if not ids:
        raise ApiError(422, MSG_EMPTY_WORKERS, code="no_workers")
    found = {w.id: w for w in db.scalars(select(Worker).where(Worker.id.in_(ids))).all()}
    workers = []
    for wid in ids:
        w = found.get(wid)
        if w is None or w.employer_id != employer_id:
            raise HTTPException(status_code=404, detail=MSG_NO_WORKER)
        workers.append(w)
    return workers


def send_to_workers(db: Session, request: Request, user: dict, task: Task, worker_ids: list[str],
                    day: str | None) -> tuple[SendResultOut, list[Assignment]]:
    """보내기 본체(커밋까지). 검사 → (내용이 바뀌었으면) 새 버전 → 근로자마다 배정 → 감사 task.assign."""
    picked = resolve_day(day)
    workers = _resolve_workers(db, user["sub"], worker_ids)
    # 쓰기 잠금을 먼저 잡고(값을 바꾸지 않는 UPDATE) 그 뒤에 읽는다. 근로자 기기의 /me/today가 first_seen_at을 쓰는
    # 것과 겹쳐도, 판정에 쓰는 값이 커밋까지 바뀌지 않는다(받은 배정을 모르고 옮기는 일을 막는다).
    db.execute(update(Task).where(Task.id == task.id).values(status=Task.status)
               .execution_options(synchronize_session=False))
    db.expire_all()
    ensure_sendable(task)
    now = clock.utcnow()
    version = versions.latest_version(db, task)
    created = False
    if not versions.same_content(task, version):
        version = versions.snapshot(db, task, user["sub"])
        created = True
    task.status = "published"
    batch_id = new_batch_id(now)
    results: list[SendResultItemOut] = []
    assignments: list[Assignment] = []
    for w in workers:
        outcome, a = assign_one(db, task, version, w.id, picked, now, batch_id)
        results.append(SendResultItemOut(worker_id=w.id, display_name=w.display_name, outcome=outcome))
        assignments.append(a)
        record_access(db, request, user, "task.assign", w.id, commit=False)
    db.commit()
    return SendResultOut(version_no=version.version_no, version_created=created, day=picked.isoformat(),
                         results=results), assignments


# --- 라우트 ----------------------------------------------------------------------------------

@router.get("/api/tasks/{task_id}/send-check", response_model=SendCheckOut)
def get_send_check(task_id: str, db: Session = Depends(get_db),
                   user: dict = Depends(require_employer)) -> SendCheckOut:
    return send_check(_owned_task(task_id, user["sub"], db))


@router.post("/api/tasks/{task_id}/send", response_model=SendResultOut)
def send_task(task_id: str, payload: SendRequest, request: Request, db: Session = Depends(get_db),
              user: dict = Depends(require_employer)) -> SendResultOut:
    task = _owned_task(task_id, user["sub"], db)
    out, _ = send_to_workers(db, request, user, task, payload.worker_ids, payload.day)
    return out


@router.get("/api/tasks/{task_id}/recipients", response_model=RecipientsOut)
def task_recipients(task_id: str, request: Request, db: Session = Depends(get_db),
                    user: dict = Depends(require_employer)) -> RecipientsOut:
    """보내기 시트의 받는 사람 고르기 도움: 지난번 받은 사람, 받은 적 있는 사람, 사업장의 마지막 보내기, 오늘 상태.

    오늘 상태(not_started·in_progress·done)는 수행 기록에서 나온 근로자별 정보라, 대시보드처럼 오늘 배정이 있는
    근로자마다 열람 기록(task.recipients)을 남긴다. 시트를 여러 번 열어도 짧은 창 안에서는 한 줄로 묶인다."""
    task = _owned_task(task_id, user["sub"], db)
    rows = db.scalars(select(Assignment).where(Assignment.task_id == task.id)
                      .order_by(Assignment.assigned_date, Assignment.id)).all()
    all_ever = list(dict.fromkeys(a.worker_id for a in rows))
    batches = [a.send_batch_id for a in rows if a.send_batch_id]
    if batches:
        last = max(batches)
        last_batch = list(dict.fromkeys(a.worker_id for a in rows if a.send_batch_id == last))
    elif rows:
        # 0007 이전 배정(묶음 id 없음): 가장 늦은 날의 배정을 마지막 보내기로 본다.
        last_day = max(a.scheduled_day for a in rows)
        last_batch = list(dict.fromkeys(a.worker_id for a in rows if a.scheduled_day == last_day))
    else:
        last_batch = []
    wp_last = db.scalar(select(func.max(Assignment.send_batch_id))
                        .join(Task, Task.id == Assignment.task_id)
                        .where(Task.employer_id == user["sub"]))
    wp_batch = (list(dict.fromkeys(db.scalars(select(Assignment.worker_id)
                                              .where(Assignment.send_batch_id == wp_last)
                                              .order_by(Assignment.assigned_date)).all()))
                if wp_last else [])
    today = clock.local_today()
    status: dict[str, str] = {}
    worker_ids = db.scalars(select(Worker.id).where(Worker.employer_id == user["sub"])
                            .order_by(Worker.created_at)).all()
    todays = {}
    for a in rows:
        if a.scheduled_day == today:
            todays[a.worker_id] = a  # 정렬이 보낸 순서라 마지막 것이 남는다
    for wid in worker_ids:
        a = todays.get(wid)
        if a is None:
            status[wid] = "none"
        elif a.status == "done":
            status[wid] = "done"
        elif _count(db, PerformanceLog, PerformanceLog.assignment_id == a.id, PerformanceLog.completed.is_(True)):
            status[wid] = "in_progress"
        else:
            status[wid] = "not_started"
    seen = [wid for wid, st in status.items() if st != "none"]
    if seen:
        record_access_for_workers(db, request, user, "task.recipients", seen)
    return RecipientsOut(last_batch_worker_ids=last_batch, all_ever_worker_ids=all_ever,
                         workplace_last_batch_worker_ids=wp_batch, today_status=status)
