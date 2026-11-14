"""사용성 테스트 보고(3b-1, 명세 8.4 '지표') — `python manage.py usability-report`.

화면 측정 이벤트(client_events)와 배정·도움 요청 표로 명세 8.4의 지표 네 가지를 센다.

1. 혼자 끝낸 비율: 끝낸 직무(배정 status=done) 가운데 도움 요청(help_open 이벤트 또는 help_requests 행)과
   선생님 모드 개입(coach_override)이 0번인 직무의 비율. 통과 기준(명세 8.4)을 보려고 '혼자 끝낸 직무가 하나라도
   있는 사람 수 / 직무를 끝낸 사람 수'도 센다(사람 수만, 누구인지는 내지 않는다).
2. 잘못 누름: [다 했어요](step_done) 뒤 QUICK_BACK_SEC(2초) 안에 [이전](step_prev)을 누른 횟수(= step_back_quick,
   이벤트로 따로 두지 않고 여기서 시각으로 계산한다)와 600ms 중복 방지에 걸린 횟수(tap_debounced). 직무당 평균도.
3. 단계 수행: 단계당 시간(step_done의 value_num = 단계에 머문 초. 없으면 같은 단계 step_view부터의 시각 차이),
   다시 듣기 수(step_replay), 도움 요청 수(help_open), '멈출래요'를 고른 비율(exit_confirm / (exit_confirm + exit_cancel)).
4. 사업주: 새 직무를 보내기까지 걸린 시간(task_send_done의 value_num, 초), 클릭 수(send_click_count의 value_num),
   비활성 [보내기]를 누른 횟수(send_click_disabled).

개인정보: 출력에는 배정 id·근로자 id·이름·직무 제목을 넣지 않는다. 배정 id는 직무 한 번을 묶는 데만 쓴다
(docs/privacy/data-map.md '사용 측정(가명)'). 사용성 측정은 테스트 사업장에서만 하고, 보고서를 쓴 뒤 30일 안에
그 사업장의 측정 이벤트를 지운다(운영 절차).
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Assignment, ClientEvent, Employer, HelpRequest

# [다 했어요] 뒤 이 시간 안의 [이전]을 '잘못 누름'으로 센다(명세 8.4).
QUICK_BACK_SEC = 2.0
# 단계당 시간을 step_view 시각 차이로 잴 때, 이보다 길면(자리를 비움·다음 날) 빼고 센다.
MAX_STEP_SEC = 60 * 60


def _ratio(a: float, b: float) -> float | None:
    return round(a / b, 3) if b else None


def _summary(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None}
    return {"n": len(values), "mean": round(statistics.fmean(values), 1),
            "median": round(statistics.median(values), 1)}


def compute(db: Session, *, since: date | None = None, until: date | None = None,
            workplace_code: str | None = None) -> dict:
    """지표를 센다. since·until은 포함하는 날짜(UTC 기준 created_at). workplace_code는 사업장 하나로 좁힌다."""
    q = select(ClientEvent)
    if since:
        q = q.where(ClientEvent.created_at >= datetime.combine(since, time.min))
    if until:
        q = q.where(ClientEvent.created_at < datetime.combine(until + timedelta(days=1), time.min))
    if workplace_code:
        emp_id = db.scalar(select(Employer.id).where(Employer.workplace_code == workplace_code))
        if emp_id is None:
            raise ValueError(f"사업장 코드를 찾지 못했습니다: {workplace_code}")
        q = q.where(ClientEvent.employer_id == emp_id)
    rows = db.scalars(q.order_by(ClientEvent.created_at)).all()

    worker_rows = [e for e in rows if e.actor == "worker"]
    employer_rows = [e for e in rows if e.actor == "employer"]
    count = defaultdict(int)
    for e in worker_rows:
        count[e.name] += 1

    # --- 배정(직무 한 번)별로 묶기 ---
    by_job: dict[str, list[ClientEvent]] = defaultdict(list)
    for e in worker_rows:
        if e.assignment_id:
            by_job[e.assignment_id].append(e)
    job_ids = list(by_job)
    status: dict[str, tuple[str, str]] = {}
    help_rows: dict[str, int] = defaultdict(int)
    if job_ids:
        for a in db.execute(select(Assignment.id, Assignment.status, Assignment.worker_id)
                            .where(Assignment.id.in_(job_ids))).all():
            status[a.id] = (a.status, a.worker_id)
        for h in db.scalars(select(HelpRequest.assignment_id).where(HelpRequest.assignment_id.in_(job_ids))).all():
            help_rows[h] += 1

    done_jobs = 0
    alone_jobs = 0
    people_done: set[str] = set()
    people_alone: set[str] = set()
    quick_back = 0
    for aid, evs in by_job.items():
        names = [e.name for e in evs]
        # step_back_quick: 같은 배정에서 step_done 뒤 2초 안의 step_prev.
        last_done: datetime | None = None
        for e in evs:
            if e.name == "step_done":
                last_done = e.created_at
            elif e.name == "step_prev" and last_done is not None:
                if (e.created_at - last_done).total_seconds() <= QUICK_BACK_SEC:
                    quick_back += 1
                last_done = None
        st, worker = status.get(aid, (None, None))
        if st != "done":
            continue
        done_jobs += 1
        people_done.add(worker)
        helped = names.count("help_open") + help_rows.get(aid, 0) + names.count("coach_override")
        if helped == 0:
            alone_jobs += 1
            people_alone.add(worker)
    # 배정 id가 없는 옛 이벤트의 step_back_quick도 단계 기준으로 센다(같은 직무, 2초 안).
    last_by_task: dict[str | None, datetime] = {}
    for e in worker_rows:
        if e.assignment_id:
            continue
        if e.name == "step_done":
            last_by_task[e.task_id] = e.created_at
        elif e.name == "step_prev" and e.task_id in last_by_task:
            if (e.created_at - last_by_task.pop(e.task_id)).total_seconds() <= QUICK_BACK_SEC:
                quick_back += 1

    # --- 단계당 시간 ---
    step_secs: list[float] = []
    view_at: dict[tuple[str | None, str | None], datetime] = {}
    for e in worker_rows:
        key = (e.assignment_id or e.task_id, e.step_id)
        if e.name == "step_view":
            view_at[key] = e.created_at
        elif e.name == "step_done":
            if e.value_num is not None and e.value_num >= 0:
                step_secs.append(float(e.value_num))
            elif key in view_at:
                sec = (e.created_at - view_at[key]).total_seconds()
                if 0 <= sec <= MAX_STEP_SEC:
                    step_secs.append(sec)

    steps_done = count["step_done"]
    jobs = len(by_job)
    exits = count["exit_confirm"] + count["exit_cancel"]
    misclicks = quick_back + count["tap_debounced"]

    send_secs = [float(e.value_num) for e in employer_rows if e.name == "task_send_done" and e.value_num is not None]
    send_clicks = [float(e.value_num) for e in employer_rows if e.name == "send_click_count" and e.value_num is not None]

    return {
        "range": {"since": since.isoformat() if since else None, "until": until.isoformat() if until else None,
                  "workplace": bool(workplace_code)},
        "events": len(rows),
        "jobs": jobs,
        "independent_completion": {
            "jobs_done": done_jobs, "jobs_alone": alone_jobs, "rate": _ratio(alone_jobs, done_jobs),
            "people_done": len(people_done), "people_alone": len(people_alone),
        },
        "misclick": {
            "step_back_quick": quick_back, "tap_debounced": count["tap_debounced"],
            "per_job": _ratio(misclicks, jobs),
        },
        "step_performance": {
            "steps_done": steps_done,
            "seconds_per_step": _summary(step_secs),
            "replays": count["step_replay"], "replays_per_step": _ratio(count["step_replay"], steps_done),
            "help_requests": count["help_open"], "help_per_step": _ratio(count["help_open"], steps_done),
            "help_per_job": _ratio(count["help_open"], jobs),
            "help_cancel": count["help_cancel"],
            "exit_confirm": count["exit_confirm"], "exit_cancel": count["exit_cancel"],
            "stop_rate": _ratio(count["exit_confirm"], exits),
            "offline_queued": count["offline_queued"], "offline_flushed": count["offline_flushed"],
        },
        "employer": {
            "send_seconds": _summary(send_secs),
            "send_clicks": _summary(send_clicks),
            "send_click_disabled": sum(1 for e in employer_rows if e.name == "send_click_disabled"),
        },
    }


def _pct(v: float | None) -> str:
    return "-" if v is None else f"{v * 100:.0f}%"


def _num(v) -> str:
    return "-" if v is None else str(v)


def format_report(r: dict) -> str:
    """사람이 읽는 글. 숫자 합계만 있고 배정 id·근로자·이름·직무 제목은 없다."""
    rng = r["range"]
    ic, mc, sp, em = r["independent_completion"], r["misclick"], r["step_performance"], r["employer"]
    lines = [
        "사용성 측정 보고 (명세 8.4)",
        f"기간: {rng['since'] or '처음'} ~ {rng['until'] or '지금'}"
        + (" / 사업장 하나" if rng["workplace"] else " / 모든 사업장"),
        f"이벤트 {r['events']}건, 직무(배정) {r['jobs']}개",
        "",
        "1. 혼자 끝낸 비율 (도움 요청·선생님 개입 0번인 끝낸 직무)",
        f"   끝낸 직무 {ic['jobs_done']}개 중 혼자 {ic['jobs_alone']}개 = {_pct(ic['rate'])}",
        f"   혼자 끝낸 직무가 있는 사람 {ic['people_alone']}명 / 끝낸 사람 {ic['people_done']}명",
        "2. 잘못 누름",
        f"   [다 했어요] 뒤 {QUICK_BACK_SEC:g}초 안에 [이전](step_back_quick) {mc['step_back_quick']}번,"
        f" 중복 방지(tap_debounced) {mc['tap_debounced']}번, 직무당 {_num(mc['per_job'])}번",
        "3. 단계 수행",
        f"   끝낸 단계 {sp['steps_done']}개, 단계당 시간 평균 {_num(sp['seconds_per_step']['mean'])}초"
        f" / 중앙값 {_num(sp['seconds_per_step']['median'])}초",
        f"   다시 듣기 {sp['replays']}번(단계당 {_num(sp['replays_per_step'])}),"
        f" 도움 요청 {sp['help_requests']}번(단계당 {_num(sp['help_per_step'])}, 직무당 {_num(sp['help_per_job'])}),"
        f" 도움 취소 {sp['help_cancel']}번",
        f"   '멈출래요' {sp['exit_confirm']}번 / '계속할래요' {sp['exit_cancel']}번 = 멈춘 비율 {_pct(sp['stop_rate'])}",
        f"   끊긴 동안 쌓인 기록 {sp['offline_queued']}건, 다시 연결 뒤 보냄 {sp['offline_flushed']}번",
        "4. 사업주",
        f"   보내기까지 시간 평균 {_num(em['send_seconds']['mean'])}초 / 중앙값 {_num(em['send_seconds']['median'])}초"
        f" ({em['send_seconds']['n']}번), 클릭 수 평균 {_num(em['send_clicks']['mean'])},"
        f" 비활성 [보내기] {em['send_click_disabled']}번",
    ]
    return "\n".join(lines)
