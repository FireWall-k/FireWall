"""오늘 현황(2c, contract §5): 근로자 지금 단계(presence), 사업장 전체 실시간 현황, 타임라인, 규칙 코칭 카드.

- 배지 판정은 badge_of() 하나다(live·타임라인·코칭이 같은 기준을 쓴다). 막힘 의심·연결 끊김은 서버가 정한다.
  예전에는 근로자 화면(StepPlayer)이 120초를 혼자 셌다. 수행 로그의 stuck은 저장만 하고 판정에 쓰지 않는다.
- GET /api/employer/live는 사업장마다 4초 응답 캐시를 둔다. 탭이 몇 개여도 DB 계산은 사업장당 분당 15번 이하다.
  429는 세션(같은 토큰)이 분당 30번을 넘을 때만 준다(두 탭이 5초마다 불러도 분당 24번).
- 근로자 이름이 실리는 응답은 열람 기록(live.view·timeline.view·coaching.cards, 폴링 묶기)을 쿼리 한 번으로 남긴다.
- 이 모듈은 main을 import하지 않는다(main이 include한다).
"""
from __future__ import annotations

import hashlib
import threading
import time
from collections import defaultdict
from datetime import date as date_type, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, noload, selectinload

import clock
import media
import task_list
import versions
from auth import require_employer
from database import get_db
from deps import current_worker
from models import (
    Assignment,
    HelpRequest,
    MediaFile,
    PerformanceLog,
    Step,
    Task,
    TaskVersion,
    TaskVersionStep,
    Worker,
    WorkerPresence,
)
from privacy import record_access_batch
from ratelimit import LoginThrottle
from schemas import (
    CoachingAfterOut,
    CoachingCardOut,
    CoachingSignalsOut,
    EmployerHelpOut,
    LiveCurrentOut,
    LiveOut,
    LiveStepOut,
    LiveSummaryOut,
    LiveTodayOut,
    LiveWorkerOut,
    PresenceIn,
    TimelineAssignmentOut,
    TimelineEventOut,
    TimelineOut,
    TimelineStepOut,
)

router = APIRouter()

# --- 판정 기준(명세 5.2 지표 정의) -----------------------------------------------------------
OFFLINE_SEC = 120          # 하는 중인데 기기 신호가 이보다 오래 없으면 연결 끊김
STUCK_MIN_SEC = 120        # 막힘 의심: 머문 시간 > max(120초, 평균 × 2)
STUCK_AVG_FACTOR = 2.0
STUCK_REPLAY = 3           # 또는 그 단계에서 다시 듣기 3번 이상
AVG_SAMPLES = 20           # 같은 단계(source_step) 최근 완료 20건 평균
MIN_SAMPLES = 3            # 표본이 이보다 적으면 120초만 본다
CACHE_SEC = 4.0            # 사업장마다 응답 캐시
PRESENCE_SAME_SEC = 15     # 같은 내용의 presence는 15초 안에 다시 쓰지 않는다
HELP_LIMIT = 50
ACTIVE_HELP_STATES = ("open", "acknowledged")

# 세션(토큰)당 분당 30번. 넘으면 429(화면은 다음 주기에 다시 부른다).
live_session_throttle = LoginThrottle(max_failures=30, window_sec=60)
# 근로자 기기 presence는 단계를 넘길 때와 주기마다 온다. 고장 난 기기가 쏟아내는 것만 막는다(분당 120번).
presence_throttle = LoginThrottle(max_failures=120, window_sec=60)

# 시험이 시계를 옮길 수 있게 캐시의 단조 시계는 이 이름 하나로 읽는다.
_mono = time.monotonic


def stuck_threshold(avg_sec: float | None, samples: int) -> float:
    """막힘 의심 기준 초. 표본이 3건 미만이면 120초만 본다."""
    if avg_sec is None or samples < MIN_SAMPLES:
        return float(STUCK_MIN_SEC)
    return max(float(STUCK_MIN_SEC), avg_sec * STUCK_AVG_FACTOR)


def badge_of(*, help_state: str | None, has_today: bool, all_done: bool, active: bool,
             now: datetime, last_signal_at: datetime | None, dwell_sec: float | None,
             replay_count: int, avg_sec: float | None, samples: int) -> str:
    """근로자 배지 하나(contract §5.2 배지 판정 표). 위에서부터 먼저 맞는 것.

    help(열린 도움) > help_acked(확인했지만 아직 해결 전) > offline > stuck_suspect > in_progress/new/done/idle.
    done은 고정 버전 단계를 모두 끝냈을 때만이다(도움은 완료로 세지 않는다). active = 하는 중(완료 1개 이상이거나
    지금 단계를 보고 있음). offline·stuck_suspect는 하는 중일 때만 본다.
    """
    if help_state == "open":
        return "help"
    if help_state == "acknowledged":
        return "help_acked"
    if not has_today:
        return "idle"
    if all_done:
        return "done"
    if not active:
        return "new"
    if last_signal_at is None or (now - last_signal_at).total_seconds() > OFFLINE_SEC:
        return "offline"
    if dwell_sec is not None and dwell_sec > stuck_threshold(avg_sec, samples):
        return "stuck_suspect"
    if replay_count >= STUCK_REPLAY:
        return "stuck_suspect"
    return "in_progress"


# --- 근로자: 지금 단계 ------------------------------------------------------------------------

def _naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def server_started_at(started: datetime | None, sent: datetime | None, now: datetime) -> datetime:
    """기기 시계의 '보낸 시각 - 단계 시작 시각'만큼 서버 수신 시각에서 뺀다(1차 완료 기록과 같은 보정).

    기기 시계가 늦거나 빨라도 머문 시간은 맞다. 시각이 없거나 뒤집혔거나 하루를 넘으면 지금으로 본다.
    """
    if started is None or sent is None:
        return now
    try:
        elapsed = _naive(sent) - _naive(started)
    except (OverflowError, ValueError):
        return now
    if elapsed < timedelta(0) or elapsed > timedelta(days=1):
        return now
    return now - elapsed


@router.post("/api/worker/presence", status_code=204)
def post_presence(payload: PresenceIn, db: Session = Depends(get_db),
                  user: dict = Depends(current_worker)) -> Response:
    """근로자 기기가 지금 보는 단계. 남의 배정 404, 배정에 없는 단계 400. 같은 내용이면 15초 안에 다시 쓰지 않는다."""
    key = f"presence:{user['sub']}"
    if presence_throttle.retry_after(key):
        raise HTTPException(status_code=429, detail="잠깐 기다렸다가 다시 보내 주세요.")
    presence_throttle.fail(key)
    a = db.get(Assignment, payload.assignment_id)
    if a is None or a.worker_id != user["sub"]:
        raise HTTPException(status_code=404, detail="배정을 찾을 수 없습니다.")
    step_id = payload.step_id or None
    if step_id is not None and versions.step_of_assignment(db, a, step_id) is None:
        raise HTTPException(status_code=400, detail="이 배정에 속하지 않는 단계입니다.")
    now = clock.utcnow()
    started = server_started_at(payload.step_started_at, payload.client_sent_at, now)
    floor = _naive(a.assigned_date) if a.assigned_date is not None else None
    if floor is not None and started < floor:
        started = floor
    p = db.get(WorkerPresence, user["sub"])
    if p is None:
        p = WorkerPresence(worker_id=user["sub"])
        db.add(p)
    else:
        same_step = p.assignment_id == a.id and p.step_id == step_id
        same = (same_step and p.replay_count == payload.replay_count
                and p.prev_count == payload.prev_count)
        if same and p.updated_at is not None and (now - p.updated_at).total_seconds() < PRESENCE_SAME_SEC:
            return Response(status_code=204)
        if (same_step and p.step_started_at is not None
                and abs((started - p.step_started_at).total_seconds()) < 10):
            # 같은 단계를 계속 보는 중: 처음 잰 시작 시각을 지킨다(신호마다 몇 초씩 흔들리지 않게).
            started = p.step_started_at
    p.assignment_id = a.id
    p.step_id = step_id
    p.step_started_at = started if step_id is not None else None
    p.replay_count = payload.replay_count
    p.prev_count = payload.prev_count
    p.updated_at = now
    db.commit()
    return Response(status_code=204)


# --- 사업주: 오늘 현황 ------------------------------------------------------------------------

def _thumb(symbol_url: str | None, media_id: str | None) -> str | None:
    # versions._urls와 같은 규칙: 사진 레코드가 있으면 서명 URL, 없으면 그림 URL.
    if media_id:
        return media.signed_url(media_id)
    return symbol_url or None


class _VStep:
    """버전 단계 한 줄(필요한 칸만)."""
    __slots__ = ("id", "version_id", "source_step_id", "order_index", "sentence", "thumb")

    def __init__(self, id, version_id, source_step_id, order_index, sentence, thumb):
        self.id = id
        self.version_id = version_id
        self.source_step_id = source_step_id
        self.order_index = order_index
        self.sentence = sentence
        self.thumb = thumb


def _version_steps(db: Session, version_ids, extra_step_ids=()) -> dict[str, list[_VStep]]:
    """버전마다 단계 목록(순서대로) + extra_step_ids(도움이 가리키는 단계)를 쿼리 한 번으로."""
    version_ids = list({v for v in version_ids if v})
    extra = list({s for s in extra_step_ids if s})
    if not version_ids and not extra:
        return {}
    conds = []
    if version_ids:
        conds.append(TaskVersionStep.version_id.in_(version_ids))
    if extra:
        conds.append(TaskVersionStep.id.in_(extra))
    rows = db.execute(
        select(TaskVersionStep.id, TaskVersionStep.version_id, TaskVersionStep.source_step_id,
               TaskVersionStep.order_index, TaskVersionStep.sentence, TaskVersionStep.symbol_url,
               MediaFile.id)
        .outerjoin(MediaFile, MediaFile.id == TaskVersionStep.symbol_media_id)
        .where(or_(*conds))
        .order_by(TaskVersionStep.version_id, TaskVersionStep.order_index)
    ).all()
    out: dict[str, list[_VStep]] = defaultdict(list)
    for sid, vid, src, order, sentence, url, mid in rows:
        out[vid].append(_VStep(sid, vid, src, order, sentence, _thumb(url, mid)))
    return out


def _legacy_steps(db: Session, task_ids) -> dict[str, list[_VStep]]:
    """버전 없는 옛 배정(백필이 못 채운 경우)의 대체 경로: 직무의 지금 단계. 보통은 부르지 않는다."""
    if not task_ids:
        return {}
    rows = db.execute(
        select(Step.id, Step.task_id, Step.order_index, Step.sentence, Step.symbol_url, MediaFile.id)
        .outerjoin(MediaFile, MediaFile.id == Step.symbol_media_id)
        .where(Step.task_id.in_(list(task_ids))).order_by(Step.task_id, Step.order_index)
    ).all()
    out: dict[str, list[_VStep]] = defaultdict(list)
    for sid, tid, order, sentence, url, mid in rows:
        out[tid].append(_VStep(sid, None, sid, order, sentence, _thumb(url, mid)))
    return out


def averages(db: Session, source_ids) -> dict[str, tuple[float, int]]:
    """source_step마다 최근 완료 20건의 평균 시간과 표본 수(창 함수 쿼리 한 번)."""
    ids = list({s for s in source_ids if s})
    if not ids:
        return {}
    rn = func.row_number().over(partition_by=TaskVersionStep.source_step_id,
                                order_by=PerformanceLog.completed_at.desc()).label("rn")
    sub = (select(TaskVersionStep.source_step_id.label("src"), PerformanceLog.duration_sec.label("d"), rn)
           .join(TaskVersionStep, TaskVersionStep.id == PerformanceLog.step_id)
           .where(PerformanceLog.completed.is_(True), TaskVersionStep.source_step_id.in_(ids))
           .subquery())
    rows = db.execute(select(sub.c.src, func.avg(sub.c.d), func.count())
                      .where(sub.c.rn <= AVG_SAMPLES).group_by(sub.c.src)).all()
    return {src: (float(avg or 0.0), int(n)) for src, avg, n in rows}


def _needs_check_tasks(db: Session, employer_id: str) -> int:
    """확인이 필요한 직무 수(보관하지 않은 직무 중 task_list.needs_check_count > 0). 직무 목록 '확인 필요'와 같은 기준."""
    tasks = db.scalars(
        select(Task).where(Task.employer_id == employer_id, Task.archived_at.is_(None),
                           Task.status != "archived")
        .options(selectinload(Task.steps).options(noload(Step.tts_media)))
    ).all()
    return sum(1 for t in tasks if task_list.needs_check_count(t) > 0)


def _status(a: Assignment, steps: list[_VStep], done_ids: set[str]) -> str:
    if a.status == "done" or (steps and all(s.id in done_ids for s in steps)):
        return "done"
    return "in_progress" if any(s.id in done_ids for s in steps) else "new"


def _latest(*values):
    vals = [v for v in values if v is not None]
    return max(vals) if vals else None


def compute(db: Session, employer_id: str) -> LiveOut:
    """사업장 전체 오늘 현황. 근로자 수와 상관없이 쿼리 10번 이하(시험으로 고정)."""
    now = clock.utcnow()
    today = clock.local_today()
    # 1. 근로자 + 지금 단계
    worker_rows = db.execute(
        select(Worker, WorkerPresence).outerjoin(WorkerPresence, WorkerPresence.worker_id == Worker.id)
        .where(Worker.employer_id == employer_id).order_by(Worker.created_at, Worker.id)
    ).all()
    worker_ids = [w.id for w, _ in worker_rows]
    # 2. 오늘 배정 + 직무 제목 + 버전 번호·제목
    a_rows = db.execute(
        select(Assignment, Task.title, TaskVersion.version_no, TaskVersion.title)
        .join(Task, Task.id == Assignment.task_id)
        .outerjoin(TaskVersion, TaskVersion.id == Assignment.task_version_id)
        .where(Assignment.worker_id.in_(worker_ids), Assignment.scheduled_day == today)
        .order_by(Assignment.assigned_date, Assignment.id)
    ).all() if worker_ids else []
    # 3. 열린 도움(open·acknowledged) + 배정의 직무
    h_rows = db.execute(
        select(HelpRequest, Assignment.task_id, Task.title, TaskVersion.title)
        .join(Assignment, Assignment.id == HelpRequest.assignment_id)
        .join(Task, Task.id == Assignment.task_id)
        .outerjoin(TaskVersion, TaskVersion.id == Assignment.task_version_id)
        .where(HelpRequest.employer_id == employer_id, HelpRequest.state.in_(ACTIVE_HELP_STATES))
        .order_by(HelpRequest.created_at.desc()).limit(HELP_LIMIT)
    ).all()
    # 4. 버전 단계(오늘 배정의 버전 + 도움이 가리키는 단계)
    vsteps = _version_steps(db, [a.task_version_id for a, *_ in a_rows], [h.step_id for h, *_ in h_rows])
    legacy = _legacy_steps(db, {a.task_id for a, *_ in a_rows if not a.task_version_id})
    step_by_id = {s.id: s for lst in vsteps.values() for s in lst}

    def steps_of(a: Assignment) -> list[_VStep]:
        if a.task_version_id:
            return vsteps.get(a.task_version_id, [])
        return legacy.get(a.task_id, [])

    # 5. 오늘 배정의 수행 로그
    a_ids = [a.id for a, *_ in a_rows]
    done_by_a: dict[str, set[str]] = defaultdict(set)
    last_log_at: dict[str, datetime] = {}
    if a_ids:
        for aid, sid, completed, at in db.execute(
                select(PerformanceLog.assignment_id, PerformanceLog.step_id, PerformanceLog.completed,
                       PerformanceLog.completed_at).where(PerformanceLog.assignment_id.in_(a_ids))).all():
            if completed:
                done_by_a[aid].add(sid)
            if at is not None and (aid not in last_log_at or at > last_log_at[aid]):
                last_log_at[aid] = at

    by_worker: dict[str, list] = defaultdict(list)
    for row in a_rows:
        by_worker[row[0].worker_id].append(row)
    help_state: dict[str, str] = {}
    for h, *_ in h_rows:
        # 한 근로자에게 열린 요청과 확인한 요청이 함께 있으면 open이 앞선다.
        if h.state == "open" or h.worker_id not in help_state:
            help_state[h.worker_id] = h.state

    # 근로자마다 지금 배정·지금 단계를 먼저 정하고, 막힘 판정에 필요한 평균은 한 번에 읽는다(6).
    plans = []
    for w, p in worker_rows:
        today_items = []
        next_marked = False
        for a, task_title, vno, vtitle in by_worker.get(w.id, []):
            steps = steps_of(a)
            st = _status(a, steps, done_by_a.get(a.id, set()))
            is_next = st != "done" and not next_marked
            next_marked = next_marked or is_next
            today_items.append((a, vtitle or task_title, vno, steps, st, is_next))
        on_presence = None
        if p is not None and p.assignment_id:
            on_presence = next((it for it in today_items if it[0].id == p.assignment_id and it[4] != "done"),
                               None)
        current = on_presence or next((it for it in today_items if it[5]), None)
        cur_step = None
        dwell = None
        replay = 0
        active = False
        if current is not None:
            a, _title, _vno, steps, _st, _n = current
            done_ids = done_by_a.get(a.id, set())
            looking = bool(p is not None and p.assignment_id == a.id and p.step_id
                           and p.step_id not in done_ids)
            if looking:
                cur_step = next((s for s in steps if s.id == p.step_id), None)
            if cur_step is None:
                cur_step = next((s for s in steps if s.id not in done_ids), None)
            if looking and cur_step is not None and cur_step.id == p.step_id:
                if p.step_started_at is not None:
                    dwell = (now - p.step_started_at).total_seconds()
                replay = p.replay_count or 0
            # 하는 중은 근로자 단위다(명세 5.2): 오늘 배정 어디든 완료 기록이 하나라도 있으면 하는 중이다.
            # 직무 1을 끝내고 직무 2를 아직 시작하지 않은 사이에도 하는 중이라 '연결 끊김'을 알아챌 수 있다.
            active = looking or any(done_by_a.get(it[0].id) for it in today_items)
        plans.append((w, p, today_items, current, cur_step, dwell, replay, active))

    avgs = averages(db, [cs.source_step_id for (_w, _p, _t, _c, cs, dw, _r, act) in plans
                         if act and cs is not None and dw is not None])

    workers_out: list[LiveWorkerOut] = []
    working = 0
    # 막힘 의심은 '단계 수'다(명세 5.2 '막힘 의심 2단계'): 같은 단계에서 여러 명이 막혀도 한 단계로 센다.
    stuck_keys: set[str] = set()
    for w, p, today_items, current, cur_step, dwell, replay, active in plans:
        a_last = [last_log_at.get(it[0].id) for it in today_items]
        looking_at = (p.step_started_at if (p is not None and current is not None
                                            and p.assignment_id == current[0].id) else None)
        last_activity = _latest(*a_last, looking_at)
        last_signal = _latest(p.updated_at if p is not None else None, w.last_seen_at, *a_last)
        avg, n = avgs.get(cur_step.source_step_id, (None, 0)) if cur_step is not None else (None, 0)
        b = badge_of(help_state=help_state.get(w.id), has_today=bool(today_items),
                     all_done=bool(today_items) and all(it[4] == "done" for it in today_items),
                     active=active, now=now, last_signal_at=last_signal, dwell_sec=dwell,
                     replay_count=replay, avg_sec=avg, samples=n)
        if active:
            working += 1
        if b == "stuck_suspect" and cur_step is not None:
            stuck_keys.add(cur_step.source_step_id or cur_step.id)
        cur_out = None
        if current is not None:
            a, title, vno, steps, _st, _n = current
            done_ids = done_by_a.get(a.id, set())
            cur_out = LiveCurrentOut(
                assignment_id=a.id, task_id=a.task_id, task_title=title or "", version_no=vno,
                done=sum(1 for s in steps if s.id in done_ids), total=len(steps),
                step=(LiveStepOut(id=cur_step.id, source_step_id=cur_step.source_step_id,
                                  order=cur_step.order_index, sentence=cur_step.sentence,
                                  thumb_url=cur_step.thumb) if cur_step is not None else None))
        workers_out.append(LiveWorkerOut(
            worker_id=w.id, display_name=w.display_name, initials=task_list._initials(w.display_name),
            badge=b, last_activity_at=last_activity, last_signal_at=last_signal, current=cur_out,
            today=[LiveTodayOut(assignment_id=it[0].id, task_title=it[1] or "", status=it[4], is_next=it[5])
                   for it in today_items]))

    names = {w.id: w.display_name for w, _ in worker_rows}
    help_out: list[EmployerHelpOut] = []
    for h, task_id, task_title, vtitle in h_rows:
        if h.worker_id not in names:
            continue
        s = step_by_id.get(h.step_id) if h.step_id else None
        help_out.append(EmployerHelpOut(
            id=h.id, state=h.state, created_at=h.created_at, acknowledged_at=h.acknowledged_at,
            worker_id=h.worker_id, worker_name=names[h.worker_id], assignment_id=h.assignment_id,
            task_id=task_id, task_title=vtitle or task_title or "",
            step_id=s.id if s is not None else None, step_order=s.order_index if s is not None else None,
            step_sentence=s.sentence if s is not None else None,
            step_symbol_url=s.thumb if s is not None else None,
            source_step_id=s.source_step_id if s is not None else None,
            step_thumb_url=s.thumb if s is not None else None))

    summary = LiveSummaryOut(
        working=working, total_workers=len(worker_rows),
        open_help=sum(1 for h, *_ in h_rows if h.state == "open"),
        stuck_steps=len(stuck_keys), needs_check_tasks=_needs_check_tasks(db, employer_id))
    return LiveOut(server_now=now, summary=summary, workers=workers_out, help=help_out)


# 사업장마다 (계산한 단조 시각, 응답). 같은 사업장의 동시 요청은 잠금 하나로 줄 세워 한 번만 계산한다.
# 프로세스 안 메모리다(ratelimit.py와 같은 단일 프로세스 전제). 도움 요청이 생겨도 캐시를 버리지 않는다 — 버리면
# '사업장당 분당 15번' 상한이 깨진다. 띠는 늦어도 4초 + 폴링 5초 안에 뜨고, 웹 푸시는 바로 간다.
_cache: dict[str, tuple[float, LiveOut]] = {}
_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_locks_guard = threading.Lock()


def _lock_for(employer_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks[employer_id]


def clear_cache() -> None:
    _cache.clear()
    live_session_throttle.clear()
    presence_throttle.clear()


def cached_live(db: Session, employer_id: str) -> LiveOut:
    with _lock_for(employer_id):
        hit = _cache.get(employer_id)
        if hit is not None and _mono() - hit[0] < CACHE_SEC:
            return hit[1]
        out = compute(db, employer_id)
        _cache[employer_id] = (_mono(), out)
        return out


def _session_key(authorization: str | None) -> str:
    return "live:" + hashlib.sha256((authorization or "").encode("utf-8")).hexdigest()[:32]


@router.get("/api/employer/live", response_model=LiveOut)
def employer_live(request: Request, authorization: str | None = Header(default=None),
                  db: Session = Depends(get_db), user: dict = Depends(require_employer)) -> LiveOut:
    key = _session_key(authorization)
    wait = live_session_throttle.retry_after(key)
    if wait:
        raise HTTPException(status_code=429, detail="잠깐 뒤에 다시 불러올게요.",
                            headers={"Retry-After": str(wait)})
    live_session_throttle.fail(key)  # 실패가 아니라 '이 세션의 요청 한 번'을 센다
    out = cached_live(db, user["sub"])
    shown = {w.worker_id for w in out.workers} | {h.worker_id for h in out.help}
    record_access_batch(db, request, user, "live.view", shown)
    return out


# --- 타임라인 ---------------------------------------------------------------------------------

def _owned_worker(db: Session, worker_id: str, employer_id: str) -> Worker:
    w = db.get(Worker, worker_id)
    if w is None or w.employer_id != employer_id:
        raise HTTPException(status_code=404, detail="근로자를 찾을 수 없습니다.")
    return w


def _parse_day(value: str | None) -> date_type:
    if not value:
        return clock.local_today()
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="날짜를 다시 골라 주세요.") from None


@router.get("/api/employer/workers/{worker_id}/timeline", response_model=TimelineOut)
def worker_timeline(worker_id: str, request: Request, date: str | None = None,
                    db: Session = Depends(get_db), user: dict = Depends(require_employer)) -> TimelineOut:
    """그 날(기본 오늘) 근로자의 배정마다 고정 버전 단계별 시간·다시 듣기·이전 누름·도움과 시간 순 사건 목록."""
    w = _owned_worker(db, worker_id, user["sub"])
    day = _parse_day(date)
    a_rows = db.execute(
        select(Assignment, Task.title, TaskVersion.version_no, TaskVersion.title)
        .join(Task, Task.id == Assignment.task_id)
        .outerjoin(TaskVersion, TaskVersion.id == Assignment.task_version_id)
        .where(Assignment.worker_id == w.id, Assignment.scheduled_day == day)
        .order_by(Assignment.assigned_date, Assignment.id)
    ).all()
    vsteps = _version_steps(db, [a.task_version_id for a, *_ in a_rows])
    legacy = _legacy_steps(db, {a.task_id for a, *_ in a_rows if not a.task_version_id})
    a_ids = [a.id for a, *_ in a_rows]
    logs = db.scalars(select(PerformanceLog).where(PerformanceLog.assignment_id.in_(a_ids))).all() if a_ids else []
    helps = db.scalars(select(HelpRequest).where(HelpRequest.assignment_id.in_(a_ids))).all() if a_ids else []
    log_of = {(log.assignment_id, log.step_id): log for log in logs}
    help_count: dict[tuple[str, str | None], int] = defaultdict(int)
    for h in helps:
        help_count[(h.assignment_id, h.step_id)] += 1
    order_of: dict[str, int] = {}
    out_assignments = []
    for a, task_title, vno, vtitle in a_rows:
        steps = vsteps.get(a.task_version_id, []) if a.task_version_id else legacy.get(a.task_id, [])
        done_ids = {log.step_id for log in logs if log.assignment_id == a.id and log.completed}
        step_out = []
        for s in steps:
            order_of[s.id] = s.order_index
            log = log_of.get((a.id, s.id))
            step_out.append(TimelineStepOut(
                step_id=s.id, source_step_id=s.source_step_id, order=s.order_index, sentence=s.sentence,
                thumb_url=s.thumb, completed=bool(log and log.completed),
                completed_at=log.completed_at if log and log.completed else None,
                duration_sec=log.duration_sec if log else None,
                replay_count=log.replay_count if log else 0,
                prev_count=(log.prev_count or 0) if log else 0,
                help_count=help_count.get((a.id, s.id), 0)))
        out_assignments.append(TimelineAssignmentOut(
            assignment_id=a.id, task_id=a.task_id, task_title=vtitle or task_title or "", version_no=vno,
            status=_status(a, steps, done_ids), assigned_at=a.assigned_date, steps=step_out))
    events: list[TimelineEventOut] = []
    for log in logs:
        if log.completed and log.completed_at is not None:
            events.append(TimelineEventOut(at=log.completed_at, kind="step_done",
                                           assignment_id=log.assignment_id,
                                           step_order=order_of.get(log.step_id)))
    for h in helps:
        for at, kind in ((h.created_at, "help_open"), (h.acknowledged_at, "help_ack"),
                         (h.resolved_at, "help_resolved"), (h.cancelled_at, "help_cancelled")):
            if at is not None:
                events.append(TimelineEventOut(at=at, kind=kind, assignment_id=h.assignment_id,
                                               step_order=order_of.get(h.step_id) if h.step_id else None))
    events.sort(key=lambda e: e.at)
    record_access_batch(db, request, user, "timeline.view", [w.id])
    return TimelineOut(worker_id=w.id, display_name=w.display_name, date=day.isoformat(),
                       assignments=out_assignments, events=events)


# --- 코칭 카드(규칙만, contract §1.6) ----------------------------------------------------------
COACH_MAX = 6
COACH_MIN_RUNS = 3          # 완료 기록이 3건 이상인 단계만 본다(도움이 2번 이상이면 기록이 적어도 본다)
COACH_HELP = 2
COACH_REPLAY_AVG = 2.0      # 평균 다시 듣기 2번 이상
COACH_SLOW_SEC = 120.0      # 평균 2분 이상
COACH_LONG_SENTENCE = 20    # 이보다 긴 문장이면 쉬운 말 제안


def suggestion_of(sig: CoachingSignalsOut, sentence: str, has_photo: bool) -> str | None:
    """제안 하나(규칙만, 유료 모델 없음). 해당 없으면 None.

    - 오래 걸림(평균 2분 이상) → 두 단계로 나누기(split)
    - 다시 듣기가 많고 문장이 김(20자 넘음) → 쉬운 말로 바꾸기(easy_words)
    - 다시 듣기가 많거나 도움이 잦고 사진이 아님 → 사진으로 바꾸기(photo)
    - 이미 사진인데 다시 듣기·도움이 잦음 → 쉬운 말로 바꾸기
    """
    if sig.runs < COACH_MIN_RUNS and sig.help_count < COACH_HELP:
        return None
    if sig.duration_avg_sec >= COACH_SLOW_SEC:
        return "split"
    hard = sig.replay_avg >= COACH_REPLAY_AVG or sig.help_count >= COACH_HELP
    if not hard:
        return None
    if sig.replay_avg >= COACH_REPLAY_AVG and len((sentence or "").strip()) > COACH_LONG_SENTENCE:
        return "easy_words"
    return "easy_words" if has_photo else "photo"


def _signals(runs: list[tuple[float, int]], helps: int) -> CoachingSignalsOut:
    n = len(runs)
    return CoachingSignalsOut(
        replay_avg=round(sum(r for _d, r in runs) / n, 1) if n else 0.0,
        duration_avg_sec=round(sum(d for d, _r in runs) / n, 1) if n else 0.0,
        help_count=helps, runs=n)


def _content(vs: TaskVersionStep) -> tuple:
    return (vs.sentence or "", vs.symbol_url or None, vs.symbol_media_id or None)


@router.get("/api/employer/coaching", response_model=list[CoachingCardOut])
def employer_coaching(request: Request, days: int = 7, db: Session = Depends(get_db),
                      user: dict = Depends(require_employer)) -> list[CoachingCardOut]:
    """고치면 좋은 단계(최대 6). 최근 days일(1~30)의 완료 기록·도움을 버전을 넘어 source_step_id로 묶는다(§1.6).

    고친 뒤 비교(after): 마지막 보낸 버전의 그 단계 내용(문장·그림)이 앞 버전과 다르면, 바뀐 버전부터의 기록을 따로 센다
    (signals는 바뀌기 전 기록). 나누기·합치기로 새로 생긴 단계는 source_step_id가 새것이라 앞 버전이 없어 after가 없다.
    마지막 버전에 없는 단계(지웠거나 나눔·합침으로 사라짐)는 고칠 곳이 없어 카드를 만들지 않는다.
    """
    days = min(max(days, 1), 30)
    since = clock.utcnow() - timedelta(days=days)
    live_task = (Task.employer_id == user["sub"], Task.archived_at.is_(None), Task.status != "archived")
    log_rows = db.execute(
        select(PerformanceLog.duration_sec, PerformanceLog.replay_count, PerformanceLog.assignment_id,
               TaskVersionStep.source_step_id, TaskVersion.version_no, TaskVersion.task_id)
        .join(TaskVersionStep, TaskVersionStep.id == PerformanceLog.step_id)
        .join(TaskVersion, TaskVersion.id == TaskVersionStep.version_id)
        .join(Task, Task.id == TaskVersion.task_id)
        .where(*live_task, PerformanceLog.completed.is_(True), PerformanceLog.completed_at >= since,
               TaskVersionStep.source_step_id.is_not(None))
    ).all()
    help_rows = db.execute(
        select(TaskVersionStep.source_step_id, TaskVersion.version_no, TaskVersion.task_id,
               HelpRequest.assignment_id)
        .join(TaskVersionStep, TaskVersionStep.id == HelpRequest.step_id)
        .join(TaskVersion, TaskVersion.id == TaskVersionStep.version_id)
        .join(Task, Task.id == TaskVersion.task_id)
        .where(*live_task, HelpRequest.employer_id == user["sub"], HelpRequest.created_at >= since,
               TaskVersionStep.source_step_id.is_not(None))
    ).all()
    groups: dict[tuple[str, str], dict] = {}

    def group(tid, src):
        return groups.setdefault((tid, src), {"runs": [], "helps": [], "assignments": set()})

    for d, r, aid, src, vno, tid in log_rows:
        g = group(tid, src)
        g["runs"].append((vno, float(d or 0.0), int(r or 0)))
        g["assignments"].add(aid)
    for src, vno, tid, aid in help_rows:
        g = group(tid, src)
        g["helps"].append(vno)
        g["assignments"].add(aid)
    if not groups:
        return []
    task_ids = {tid for tid, _ in groups}
    sources = {src for _, src in groups}
    tasks = {t.id: t for t in db.scalars(select(Task).where(Task.id.in_(task_ids))).all()}
    latest_no = dict(db.execute(select(TaskVersion.task_id, func.max(TaskVersion.version_no))
                                .where(TaskVersion.task_id.in_(task_ids))
                                .group_by(TaskVersion.task_id)).all())
    by_group_versions: dict[tuple[str, str], dict[int, TaskVersionStep]] = defaultdict(dict)
    for vs, vno, tid in db.execute(
            select(TaskVersionStep, TaskVersion.version_no, TaskVersion.task_id)
            .join(TaskVersion, TaskVersion.id == TaskVersionStep.version_id)
            .where(TaskVersionStep.source_step_id.in_(sources), TaskVersion.task_id.in_(task_ids))
            .options(noload(TaskVersionStep.tts_media))).all():
        by_group_versions[(tid, vs.source_step_id)][vno] = vs
    live_steps = {s.id: s for s in db.scalars(
        select(Step).where(Step.id.in_(sources)).options(noload(Step.tts_media))).all()}

    cards: list[tuple[float, CoachingCardOut, set]] = []
    for (tid, src), g in groups.items():
        task = tasks.get(tid)
        vmap = by_group_versions.get((tid, src), {})
        last = latest_no.get(tid)
        latest_vs = vmap.get(last) if last is not None else None
        if task is None or latest_vs is None:
            continue
        # 마지막 버전과 내용이 같은 가장 이른 연속 버전(since_no). 그보다 앞에 그 단계가 있으면 '고쳤다'.
        since_no = last
        for vno in sorted(vmap, reverse=True):
            if _content(vmap[vno]) != _content(latest_vs):
                break
            since_no = vno
        changed = any(vno < since_no for vno in vmap)
        before_runs = [(d, r) for vno, d, r in g["runs"] if not changed or vno < since_no]
        before_helps = sum(1 for vno in g["helps"] if not changed or vno < since_no)
        after = None
        if changed:
            after_runs = [(d, r) for vno, d, r in g["runs"] if vno >= since_no]
            after_helps = sum(1 for vno in g["helps"] if vno >= since_no)
            if after_runs or after_helps:
                after = CoachingAfterOut(**_signals(after_runs, after_helps).model_dump(),
                                         since_version_no=since_no)
        if not before_runs and not before_helps:
            # 바뀐 뒤 기록만 있다(고치기 전 기록은 기간 밖): 그 기록을 신호로 쓰고 비교는 없다.
            if after is None:
                continue
            before_runs = [(d, r) for vno, d, r in g["runs"] if vno >= since_no]
            before_helps = after.help_count
            after = None
        sig = _signals(before_runs, before_helps)
        current = live_steps.get(src)
        if current is not None and current.task_id != tid:
            current = None
        sentence = current.sentence if current is not None else latest_vs.sentence
        has_photo = bool(current.symbol_media_id if current is not None else latest_vs.symbol_media_id)
        kind = suggestion_of(sig, sentence, has_photo)
        if kind is None:
            continue
        thumb = (versions.step_to_out(current).symbol_url if current is not None
                 else versions.version_step_to_out(latest_vs).symbol_url)
        score = sig.help_count * 2 + sig.replay_avg + sig.duration_avg_sec / 60.0
        cards.append((score, CoachingCardOut(
            task_id=tid, task_title=task.title or "", source_step_id=src,
            step_id=current.id if current is not None else None,
            sentence=sentence, thumb_url=thumb, signals=sig, suggestion=kind, after=after), g["assignments"]))
    cards.sort(key=lambda c: (-c[0], c[1].task_id, c[1].source_step_id))
    picked = cards[:COACH_MAX]
    used = set().union(*(c[2] for c in picked)) if picked else set()
    if used:
        # 카드에는 이름이 없지만 근로자 기록을 모아 보여 준다. 기록이 들어간 근로자마다 열람 기록을 남긴다.
        wids = set(db.scalars(select(Assignment.worker_id).where(Assignment.id.in_(list(used)))).all())
        record_access_batch(db, request, user, "coaching.cards", wids)
    return [c[1] for c in picked]
