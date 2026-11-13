"""2d 관리 화면 서버(scratchpad/p2/contract.md §6, tasks.md §7).

- 근로자 목록 열(오늘 배지·7일 완료·7일 도움·동의 상태)을 한 번에 계산한다(list_columns). 목록에는 전체 코드가 없다.
- 접속 코드 보기(reveal): 감사 `worker.code.reveal`을 매번 남기고, 사업주마다 분당 10번까지.
- 근로자 지우기는 이름을 그대로 다시 적어야 한다(POST /api/workers/{id}/delete). 옛 DELETE는 지웠다.
- 사업장 설정: 이름·호칭(한글 1~6자)·근로자 화면 기본값. 기본값은 새 근로자에게만 쓴다.
- 근로자 상세 '현황'(GET /api/employer/workers/{id}/stats).

이 모듈은 main을 import하지 않는다(main이 이 라우터를 include한다).
"""
from __future__ import annotations

import json
import os
import unicodedata
from datetime import date, datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import ai_client
import clock
import versions
from auth import decrypt_access_code, require_employer
from database import checkpoint_wal, get_db
from models import (
    Assignment,
    Employer,
    HelpRequest,
    PerformanceLog,
    Step,
    Task,
    TaskVersion,
    TaskVersionStep,
    Worker,
    WorkerConsent,
    WorkerPresence,
)
from privacy import CONSENT_PERSONAL_INFO, record_access, workers_with_active_consent
from ratelimit import LoginThrottle
from schemas import (
    AccessCodeRevealOut,
    AiUsageOut,
    WorkerDayStat,
    WorkerDeleteRequest,
    WorkerStatsOut,
    WorkerStepStat,
    WorkplaceOut,
    WorkplaceUpdate,
    merge_a11y_prefs,
    parse_a11y_prefs,
)
from text_clean import clean_one_line, has_visible

router = APIRouter()

DEFAULT_TEACHER_TITLE = "선생님"
TEACHER_TITLE_MAX = 6
ORG_NAME_MAX = 40
MSG_TEACHER_TITLE = "호칭은 한글 1~6자로 적어 주세요."
MSG_ORG_NAME = "사업장 이름을 1~40자로 적어 주세요."
MSG_NAME_MISMATCH = "이름이 맞지 않아요. 지울 근로자 이름을 그대로 적어 주세요."
MSG_REVEAL_LIMIT = "번호를 너무 자주 열었어요. 1분 뒤에 다시 눌러 주세요."
MSG_CODE_UNKNOWN = "이 근로자의 번호는 예전에 만들어 볼 수 없어요. [새 번호 만들기]를 눌러 주세요."
REVEAL_AUDIT_ACTION = "worker.code.reveal"
STATS_AUDIT_ACTION = "worker.stats"
STATS_MAX_DAYS = 31

# 접속 코드 보기 횟수(키 "reveal:{employer_id}"). 실패가 아니라 모든 보기를 센다 — 60초에 10번이 넘으면 429.
reveal_throttle = LoginThrottle(
    max_failures=int(os.getenv("CODE_REVEAL_MAX_PER_MIN", "10")),
    window_sec=60,
)


def _employer(db: Session, user: dict) -> Employer:
    employer = db.get(Employer, user["sub"])
    if employer is None:
        raise HTTPException(status_code=401, detail="사업주 정보를 찾을 수 없습니다. 다시 로그인해 주세요.")
    return employer


def _owned_worker(worker_id: str, employer_id: str, db: Session) -> Worker:
    worker = db.get(Worker, worker_id)
    if worker is None or worker.employer_id != employer_id:
        # 존재 여부를 노출하지 않도록 소유자 불일치도 404로 통일한다.
        raise HTTPException(status_code=404, detail="근로자를 찾을 수 없습니다.")
    return worker


# --- 호칭·기본값 ---------------------------------------------------------------------------

def valid_teacher_title(title: str) -> bool:
    """한글 음절(가~힣)만 1~6자. 공백·숫자·영문·낱자모는 안 된다(근로자 소리 문구에 조사와 함께 그대로 붙는다)."""
    return 1 <= len(title) <= TEACHER_TITLE_MAX and all("가" <= ch <= "힣" for ch in title)


def teacher_title_of(employer: Employer | None) -> str:
    """근로자 화면 호칭. 비었거나 규칙 밖 값이 저장돼 있어도 '선생님'으로 읽는다(읽기는 관용)."""
    title = (getattr(employer, "teacher_title", None) or "").strip()
    return title if valid_teacher_title(title) else DEFAULT_TEACHER_TITLE


def new_worker_prefs(employer: Employer | None) -> str:
    """새 근로자의 a11y_prefs JSON. 사업장 기본값이 비었으면 '{}'(= 앱 기본값) 그대로."""
    raw = (getattr(employer, "worker_defaults", None) or "{}").strip()
    if raw in ("", "{}"):
        return "{}"
    return json.dumps(parse_a11y_prefs(raw).model_dump(), ensure_ascii=False)


def device_link(workplace_code: str) -> str:
    """기기 연결 QR·주소. /worker가 site를 읽어 기기에 사업장 코드를 저장하고 주소에서 뺀다(프론트)."""
    # 비어 있으면(compose의 "${PUBLIC_FRONTEND_URL:-}"처럼 빈 값이 넘어와도) 로컬 개발 주소. 빈 값을 그대로 쓰면
    # '/worker?site=…'만 남아 QR이 아무 기기에서도 열리지 않는다.
    base = (os.getenv("PUBLIC_FRONTEND_URL") or "").strip().rstrip("/") or "http://localhost:5173"
    return f"{base}/worker?site={quote(workplace_code, safe='')}"


def workplace_out(employer: Employer) -> WorkplaceOut:
    return WorkplaceOut(workplace_code=employer.workplace_code, org_name=employer.org_name or "",
                        device_link=device_link(employer.workplace_code),
                        teacher_title=teacher_title_of(employer),
                        worker_defaults=parse_a11y_prefs(employer.worker_defaults))


@router.get("/api/workplace", response_model=WorkplaceOut)
def my_workplace(db: Session = Depends(get_db), user: dict = Depends(require_employer)) -> WorkplaceOut:
    """사업장 코드·이름·기기 연결 주소·호칭·근로자 화면 기본값. 근로자 관리·설정 화면에 보여 준다."""
    return workplace_out(_employer(db, user))


@router.get("/api/workplace/ai-usage", response_model=AiUsageOut)
def workplace_ai_usage(user: dict = Depends(require_employer)) -> AiUsageOut:
    """설정 화면 'AI 사용량 (이번 달)'. 서비스 전체의 GPT 사용 횟수·추정 요금(달러)·알림 기준.

    AI 하네스에 닿지 못하면 500 대신 available=False를 준다. 내용(문장)은 하네스도 기록하지 않는다.
    """
    body = ai_client.ai_usage()
    if body is None:
        return AiUsageOut(available=False, enabled=False)
    try:
        return AiUsageOut.model_validate({**body, "available": True})
    except ValueError:
        return AiUsageOut(available=False, enabled=False)


@router.patch("/api/workplace", response_model=WorkplaceOut)
def update_workplace(payload: WorkplaceUpdate, db: Session = Depends(get_db),
                     user: dict = Depends(require_employer)) -> WorkplaceOut:
    """사업장 이름·호칭·근로자 화면 기본값. 보낸 칸만 바꾼다. 한 칸이라도 틀리면 아무것도 저장하지 않는다."""
    employer = _employer(db, user)
    org_name = title = None
    if payload.org_name is not None:
        # 직무 제목과 같은 규칙: 제어 문자는 공백으로, 보이지 않는 글자는 지우고, 보이는 글자가 없으면 빈 이름이다
        # (빈칸처럼 보이는 이름이 저장되면 근로자 쪽 'org_name or name' 대체가 듣지 않아 사업장 이름이 빈칸으로 나온다).
        org_name = " ".join(clean_one_line(unicodedata.normalize("NFC", payload.org_name)).split())
        if not 1 <= len(org_name) <= ORG_NAME_MAX or not has_visible(org_name):
            raise HTTPException(status_code=422, detail=MSG_ORG_NAME)
    if payload.teacher_title is not None:
        title = unicodedata.normalize("NFC", payload.teacher_title).strip()
        if not valid_teacher_title(title):
            raise HTTPException(status_code=422, detail=MSG_TEACHER_TITLE)
    if org_name is not None:
        employer.org_name = org_name
    if title is not None:
        employer.teacher_title = title
    if payload.worker_defaults is not None:
        # 기본값만 바꾼다. 이미 있는 근로자의 화면 설정은 그대로다(근로자 상세에서 따로 바꾼다).
        employer.worker_defaults = merge_a11y_prefs(employer.worker_defaults, payload.worker_defaults)
    db.commit()
    db.refresh(employer)
    return workplace_out(employer)


# --- 근로자 목록 열 -------------------------------------------------------------------------

def _local_midnight_utc(day: date) -> datetime:
    """현지 날짜 0시를 naive UTC로(저장된 시각과 바로 비교)."""
    return datetime(day.year, day.month, day.day) - timedelta(hours=clock.offset_hours())


def list_columns(db: Session, worker_ids: list[str]) -> dict[str, dict]:
    """근로자 목록의 오늘 배지·7일 완료·7일 도움·동의 상태. 근로자 수와 상관없이 쿼리 몇 번으로 끝낸다.

    오늘 배지 순서: 도움 요청 열림(help) > 확인함·도움 가는 중(help_coming) > 다 함(오늘 배정 모두 done) >
    하는 중(완료 기록이 하나라도 있음) > 아직 시작 안 함 > 오늘 받은 일 없음(none).
    열린 도움은 어제 배정에서 누른 것도 보인다(아직 아무도 가지 않았다).
    """
    if not worker_ids:
        return {}
    today = clock.local_today()
    first = today - timedelta(days=6)
    since = _local_midnight_utc(first)
    out = {wid: {"today_badge": "none", "done_7d": [0] * 7, "help_7d": 0, "consent_state": "missing"}
           for wid in worker_ids}

    rows = db.execute(select(Assignment.id, Assignment.worker_id, Assignment.status, Assignment.scheduled_day)
                      .where(Assignment.worker_id.in_(worker_ids), Assignment.scheduled_day >= first,
                             Assignment.scheduled_day <= today)).all()
    todays: dict[str, list[tuple[str, str]]] = {}
    for aid, wid, status, day in rows:
        if status == "done":
            out[wid]["done_7d"][(day - first).days] += 1
        if day == today:
            todays.setdefault(wid, []).append((aid, status))
    today_ids = [aid for items in todays.values() for aid, _ in items]
    started = set(db.scalars(select(PerformanceLog.assignment_id).where(
        PerformanceLog.assignment_id.in_(today_ids),
        PerformanceLog.completed.is_(True))).all()) if today_ids else set()
    for wid, items in todays.items():
        if all(st == "done" for _, st in items):
            badge = "done"
        elif any(st == "done" or aid in started for aid, st in items):
            badge = "in_progress"
        else:
            badge = "not_started"
        out[wid]["today_badge"] = badge

    helps = db.execute(select(HelpRequest.worker_id, HelpRequest.state, HelpRequest.created_at)
                       .where(HelpRequest.worker_id.in_(worker_ids),
                              HelpRequest.state.in_(("open", "acknowledged"))
                              | (HelpRequest.created_at >= since))).all()
    for wid, state, created in helps:
        if created is not None and created.replace(tzinfo=None) >= since:
            out[wid]["help_7d"] += 1
        if state == "open":
            out[wid]["today_badge"] = "help"
        elif state == "acknowledged" and out[wid]["today_badge"] != "help":
            out[wid]["today_badge"] = "help_coming"

    personal = workers_with_active_consent(db, worker_ids, CONSENT_PERSONAL_INFO)
    ai = workers_with_active_consent(db, worker_ids)
    for wid in worker_ids:
        if wid in personal:
            out[wid]["consent_state"] = "complete" if wid in ai else "ai_missing"
    return out


# --- 접속 코드 보기 -------------------------------------------------------------------------

@router.post("/api/workers/{worker_id}/access-code/reveal", response_model=AccessCodeRevealOut)
def reveal_access_code(worker_id: str, request: Request, db: Session = Depends(get_db),
                       user: dict = Depends(require_employer)) -> AccessCodeRevealOut:
    """눈 단추를 누르면 5초 동안 보여 줄 전체 코드. 볼 때마다 감사 기록을 남긴다(폴링 묶기 없음)."""
    worker = _owned_worker(worker_id, user["sub"], db)
    key = f"reveal:{user['sub']}"
    wait = reveal_throttle.retry_after(key)
    if wait:
        raise HTTPException(status_code=429, detail=MSG_REVEAL_LIMIT, headers={"Retry-After": str(wait)})
    reveal_throttle.fail(key)
    record_access(db, request, user, REVEAL_AUDIT_ACTION, worker.id)
    code = decrypt_access_code(worker.employer_id, worker.access_code_cipher)
    if code is None:
        # 0005 이전 근로자는 평문을 모른다(그 근로자가 한 번 로그인하거나 재발급하면 생긴다).
        raise HTTPException(status_code=409, detail=MSG_CODE_UNKNOWN)
    return AccessCodeRevealOut(code=code)


# --- 근로자 지우기 --------------------------------------------------------------------------

def _norm_name(s: str) -> str:
    return " ".join(unicodedata.normalize("NFC", s or "").split())


@router.post("/api/workers/{worker_id}/delete")
def delete_worker(worker_id: str, payload: WorkerDeleteRequest, request: Request,
                  db: Session = Depends(get_db), user: dict = Depends(require_employer)) -> dict:
    """근로자를 지운다. 이름을 그대로 다시 적어야 한다(앞뒤·겹친 공백과 NFC 차이는 같은 것으로 본다).
    그 근로자의 배정·수행 로그·도움·동의 기록도 함께 지운다(직무는 사업주 데이터라 유지).

    개인정보 파기 요건: DB 행만 지우면 SQLite 파일의 빈 페이지와 WAL에 이름·메모가 남는다.
    secure_delete(database.py)로 지운 페이지를 0으로 덮고, 커밋 뒤 WAL을 체크포인트해 옛 프레임도 비운다.
    접근 감사 로그는 보존기간 동안 남기되 근로자 id만 담고 이름은 담지 않는다.

    직무 원문·제목·단계 문장에 이름을 적었다면 그건 사업주 데이터라 지우지 않는다. 대신 이름이 들어 있는 직무
    목록(name_mentions)을 돌려줘 사업주가 고치거나 지우게 한다.
    WAL 체크포인트가 다른 연결의 읽기 때문에 끝나지 않으면 wal_checkpointed=false로 알린다(purge가 다시 한다).
    """
    worker = _owned_worker(worker_id, user["sub"], db)
    typed = _norm_name(payload.confirm_name)
    if not typed or typed != _norm_name(worker.display_name):
        raise HTTPException(status_code=422, detail=MSG_NAME_MISMATCH)
    name_mentions = tasks_mentioning(db, user["sub"], worker.display_name)
    assignment_ids = list(db.scalars(select(Assignment.id).where(Assignment.worker_id == worker_id)).all())
    # 도움 요청은 배정·근로자를 가리키므로 먼저 지운다(남기면 FK 고아 + 근로자 기록이 남는다).
    db.execute(delete(HelpRequest).where(HelpRequest.worker_id == worker_id))
    if assignment_ids:
        db.execute(delete(PerformanceLog).where(PerformanceLog.assignment_id.in_(assignment_ids)))
        db.execute(delete(Assignment).where(Assignment.worker_id == worker_id))
    db.execute(delete(WorkerConsent).where(WorkerConsent.worker_id == worker_id))
    # (2c) 지금 보던 단계(worker_presence)도 근로자 기록이다(contract §1.7).
    db.execute(delete(WorkerPresence).where(WorkerPresence.worker_id == worker_id))
    db.delete(worker)
    record_access(db, request, user, "worker.delete", worker_id, commit=False)
    db.commit()
    checkpointed = checkpoint_wal(db)
    return {"ok": True, "wal_checkpointed": checkpointed, "name_mentions": name_mentions}


def tasks_mentioning(db: Session, employer_id: str, name: str) -> list[dict]:
    """이 사업장 직무 중 원문·제목·단계 문장에 이름이 그대로 들어 있는 것. 근로자 삭제 뒤 사업주 안내용."""
    name = (name or "").strip()
    if len(name) < 2:
        # 한 글자 이름은 거의 모든 문장에 걸려 목록이 의미가 없다.
        return []
    pattern = f"%{name}%"
    in_steps = select(Step.task_id).where(Step.sentence.like(pattern))
    # (2a-0) 보낸 버전의 문장·제목에도 이름이 남는다(편집기에서 고쳐도 옛 버전은 그대로다).
    in_versions = (select(TaskVersion.task_id)
                   .join(TaskVersionStep, TaskVersionStep.version_id == TaskVersion.id, isouter=True)
                   .where(TaskVersionStep.sentence.like(pattern) | TaskVersion.title.like(pattern)))
    tasks = db.scalars(select(Task).where(
        Task.employer_id == employer_id,
        (Task.title.like(pattern)) | (Task.raw_input.like(pattern)) | (Task.id.in_(in_steps))
        | (Task.id.in_(in_versions)),
    ).order_by(Task.created_at)).all()
    return [{"task_id": t.id, "title": t.title} for t in tasks]


# --- 근로자 상세 '현황' ---------------------------------------------------------------------

@router.get("/api/employer/workers/{worker_id}/stats", response_model=WorkerStatsOut)
def worker_stats(worker_id: str, request: Request, days: int = 7, db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> WorkerStatsOut:
    """최근 days일(현지 날짜, 오늘 포함) 날마다 받은·다 한 배정, 완료 단계, 도움, 일한 시간과 단계별 평균 시간.

    날짜는 배정의 scheduled_day 기준이다(도움은 누른 현지 날짜). 단계는 버전을 넘어 같은 단계면 하나로 모은다.
    """
    worker = _owned_worker(worker_id, user["sub"], db)
    if not 1 <= days <= STATS_MAX_DAYS:
        raise HTTPException(status_code=422, detail=f"기간은 1~{STATS_MAX_DAYS}일로 골라 주세요.")
    record_access(db, request, user, STATS_AUDIT_ACTION, worker.id)
    today = clock.local_today()
    first = today - timedelta(days=days - 1)
    span = [first + timedelta(days=i) for i in range(days)]
    daily = {d: {"assigned": 0, "done": 0, "steps_done": 0, "help": 0, "work_sec": 0.0} for d in span}

    assignments = db.scalars(select(Assignment).where(
        Assignment.worker_id == worker_id, Assignment.scheduled_day >= first,
        Assignment.scheduled_day <= today)).all()
    by_id = {a.id: a for a in assignments}
    for a in assignments:
        daily[a.scheduled_day]["assigned"] += 1
        if a.status == "done":
            daily[a.scheduled_day]["done"] += 1

    logs = db.scalars(select(PerformanceLog).where(
        PerformanceLog.assignment_id.in_(list(by_id)),
        PerformanceLog.completed.is_(True))).all() if by_id else []
    help_rows = db.scalars(select(HelpRequest).where(
        HelpRequest.worker_id == worker_id, HelpRequest.created_at >= _local_midnight_utc(first))).all()
    steps = versions.find_steps(db, {lg.step_id for lg in logs} | {h.step_id for h in help_rows if h.step_id})
    task_ids = {a.task_id for a in assignments}
    tasks = ({t.id: t for t in db.scalars(select(Task).where(Task.id.in_(task_ids))).all()}
             if task_ids else {})

    agg: dict[tuple[str, str], dict] = {}

    def bucket(task_id: str, st) -> dict:
        key = (task_id, versions.step_key(st))
        if key not in agg:
            task = tasks.get(task_id)
            agg[key] = {"task_id": task_id, "task_title": task.title if task else "", "samples": 0,
                        "total": 0.0, "replay_count": 0, "help_count": 0}
        # 같은 단계가 여러 버전에 있으면 문장·순서는 마지막에 본(가장 늦은) 것으로 둔다.
        agg[key]["order"], agg[key]["sentence"] = st.order_index, st.sentence
        return agg[key]

    total_sec = 0.0
    for lg in sorted(logs, key=lambda x: x.completed_at or datetime.min):
        a = by_id[lg.assignment_id]
        dur = float(lg.duration_sec or 0.0)
        daily[a.scheduled_day]["steps_done"] += 1
        daily[a.scheduled_day]["work_sec"] += dur
        total_sec += dur
        st = steps.get(lg.step_id)
        if st is not None:
            b = bucket(a.task_id, st)
            b["samples"] += 1
            b["total"] += dur
            b["replay_count"] += int(lg.replay_count or 0)
    for h in help_rows:
        d = clock.local_date(h.created_at)
        if d in daily:
            daily[d]["help"] += 1
        a = by_id.get(h.assignment_id)
        st = steps.get(h.step_id) if h.step_id else None
        if a is not None and st is not None:
            bucket(a.task_id, st)["help_count"] += 1

    step_out = [WorkerStepStat(task_id=b["task_id"], task_title=b["task_title"], order=b["order"],
                               sentence=b["sentence"], samples=b["samples"],
                               avg_duration_sec=round(b["total"] / b["samples"], 1) if b["samples"] else 0.0,
                               replay_count=b["replay_count"], help_count=b["help_count"])
                for b in sorted(agg.values(), key=lambda x: (x["task_title"], x["task_id"], x["order"]))]
    n = len(logs)
    return WorkerStatsOut(
        worker_id=worker.id, days=days,
        daily=[WorkerDayStat(day=d.isoformat(), assigned=v["assigned"], done=v["done"],
                             steps_done=v["steps_done"], help=v["help"], work_sec=round(v["work_sec"], 1))
               for d, v in daily.items()],
        steps=step_out, avg_step_sec=round(total_sec / n, 1) if n else 0.0)
