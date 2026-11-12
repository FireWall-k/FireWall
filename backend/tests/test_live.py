"""2c 오늘 현황 시험 (scratchpad/p2/contract.md §5, tasks.md §6).

지키는 것:
- 배지 판정은 서버 함수 하나(live.badge_of): 막힘 119/121초, 다시 듣기 2/3, 평균×2, 표본 3건 미만, 연결 끊김 119/121,
  도움은 완료로 세지 않음, 확인한 도움은 help_acked(open_help에는 세지 않음).
- presence 시계 보정(기기 시계가 늦음·빠름·엉터리 연도여도 500 없음), 남의 배정 404, 같은 내용 15초 안 다시 쓰지 않음.
- 두 탭이 5초마다 불러도 429 0건, DB 계산은 사업장당 분당 15번 이하. 31번째 요청은 429.
- 근로자 20명이어도 계산 쿼리 10번 이하. 열람 기록은 근로자마다 한 줄로 묶임.
- 타임라인(단계별 시간·다시 듣기·이전 누름·도움), 코칭 카드 3종과 '고친 뒤'(나눈 단계는 빠짐).
- 수행 로그 prev_count 저장, 근로자 삭제 때 presence도 지움, 0009 upgrade·downgrade·다시 올리기, VAPID 키 명령.
"""
import base64
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from sqlalchemy import event, func, inspect, select, text  # noqa: E402

import live  # noqa: E402
from database import SessionLocal, engine  # noqa: E402
from live_site import FakeClock, Site  # noqa: E402
from models import (  # noqa: E402
    AccessAuditLog,
    Assignment,
    PerformanceLog,
    WorkerPresence,
)

NOW = datetime(2026, 11, 10, 3, 0, 0)


def _badge(**kw):
    base = dict(help_state=None, has_today=True, all_done=False, active=True, now=NOW,
                last_signal_at=NOW, dwell_sec=10.0, replay_count=0, avg_sec=None, samples=0)
    base.update(kw)
    return live.badge_of(**base)


# --- 1. 배지 함수 경계값 ----------------------------------------------------------------------

def test_badge_stuck_boundary_119_121():
    assert _badge(dwell_sec=119) == "in_progress"
    assert _badge(dwell_sec=120) == "in_progress"
    assert _badge(dwell_sec=121) == "stuck_suspect"


def test_badge_replay_2_and_3():
    assert _badge(replay_count=2) == "in_progress"
    assert _badge(replay_count=3) == "stuck_suspect"


def test_badge_average_times_two():
    # 평균 100초, 표본 3건 → 기준 200초
    assert _badge(dwell_sec=199, avg_sec=100, samples=3) == "in_progress"
    assert _badge(dwell_sec=201, avg_sec=100, samples=3) == "stuck_suspect"
    # 평균이 짧아도 120초 아래로 내려가지 않는다
    assert _badge(dwell_sec=119, avg_sec=10, samples=20) == "in_progress"
    assert _badge(dwell_sec=121, avg_sec=10, samples=20) == "stuck_suspect"


def test_badge_fewer_than_three_samples_uses_120_only():
    assert _badge(dwell_sec=150, avg_sec=100, samples=2) == "stuck_suspect"
    assert _badge(dwell_sec=150, avg_sec=100, samples=3) == "in_progress"


def test_badge_offline_boundary_and_order():
    assert _badge(last_signal_at=NOW - timedelta(seconds=119)) == "in_progress"
    assert _badge(last_signal_at=NOW - timedelta(seconds=121)) == "offline"
    # 연결 끊김이 막힘보다 앞서고, 도움이 모두보다 앞선다
    assert _badge(last_signal_at=NOW - timedelta(seconds=121), dwell_sec=500) == "offline"
    assert _badge(help_state="open", last_signal_at=None) == "help"
    assert _badge(help_state="acknowledged", dwell_sec=500) == "help_acked"
    # 하는 중이 아니면 연결 끊김·막힘을 보지 않는다
    assert _badge(active=False, last_signal_at=None, dwell_sec=500) == "new"
    assert _badge(all_done=True, last_signal_at=None) == "done"
    assert _badge(has_today=False) == "idle"


# --- 2. 실제 경로: presence → live ---------------------------------------------------------

@pytest.fixture()
def clk(monkeypatch):
    return FakeClock(monkeypatch)


def test_live_stuck_boundary_end_to_end(client, clk):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    aid, s1 = card["assignment_id"], card["steps"][0]["id"]
    assert site.presence(w, aid, s1).status_code == 204
    clk.at(100)
    # 같은 단계를 계속 보는 중(같은 내용, 15초 지남 → 신호 시각만 갱신, 시작 시각은 그대로)
    assert site.presence(w, aid, s1, started=datetime(2026, 1, 1), sent=datetime(2026, 1, 1, 0, 1, 40)).status_code == 204
    clk.at(119)
    me = site.worker_live(w)
    assert me["badge"] == "in_progress"
    assert me["current"]["step"]["id"] == s1 and me["current"]["done"] == 0 and me["current"]["total"] == 2
    clk.at(121)
    assert site.worker_live(w)["badge"] == "stuck_suspect"
    assert site.live()["summary"]["stuck_steps"] == 1


def test_live_replay_three_is_stuck(client, clk):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    aid, s1 = card["assignment_id"], card["steps"][0]["id"]
    site.presence(w, aid, s1, replay=2)
    assert site.worker_live(w)["badge"] == "in_progress"
    site.presence(w, aid, s1, replay=3)
    assert site.worker_live(w)["badge"] == "stuck_suspect"


def _seed_history(source_step_id: str, durations: list[float], version_step_id: str, aid: str):
    """다른 배정(같은 단계 source)의 완료 기록을 직접 넣는다(평균 표본)."""
    with SessionLocal() as db:
        a = db.get(Assignment, aid)
        for i, d in enumerate(durations):
            other = Assignment(task_id=a.task_id, worker_id=a.worker_id, task_version_id=a.task_version_id,
                               scheduled_day=a.scheduled_day - timedelta(days=1 + i), status="done")
            db.add(other)
            db.flush()
            db.add(PerformanceLog(assignment_id=other.id, step_id=version_step_id, duration_sec=d,
                                  completed=True, completed_at=datetime(2026, 11, 1) + timedelta(hours=i)))
        db.commit()


def test_live_average_times_two_and_sample_floor(client, clk):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    aid, s1 = card["assignment_id"], card["steps"][0]["id"]
    _seed_history(None, [100, 100], s1, aid)  # 표본 2건 → 120초만
    site.presence(w, aid, s1)
    clk.at(110)
    site.presence(w, aid, s1, started=datetime(2026, 1, 1), sent=datetime(2026, 1, 1, 0, 1, 50))
    clk.at(150)
    assert site.worker_live(w)["badge"] == "stuck_suspect"
    _seed_history(None, [100], s1, aid)  # 표본 3건, 평균 100 → 기준 200초
    assert site.worker_live(w)["badge"] == "in_progress"
    clk.at(190)
    site.presence(w, aid, s1, started=datetime(2026, 1, 1), sent=datetime(2026, 1, 1, 0, 3, 10))
    clk.at(201)
    assert site.worker_live(w)["badge"] == "stuck_suspect"


def test_live_offline_boundary(client, clk):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    aid, s1 = card["assignment_id"], card["steps"][0]["id"]
    site.presence(w, aid, s1)
    clk.at(119)
    me = site.worker_live(w)
    assert me["badge"] == "in_progress"
    clk.at(121)
    me = site.worker_live(w)
    assert me["badge"] == "offline"
    assert me["last_signal_at"] is not None
    assert site.live()["summary"]["working"] == 1


def test_between_tasks_is_in_progress_then_offline(client, clk):
    """직무 1을 끝내고 직무 2를 아직 시작하지 않은 근로자도 하는 중이다(하는 중은 근로자 단위, 명세 5.2).
    그래서 기기 신호가 121초 없으면 '연결 끊김'이 되고, '지금 일하는 사람'에도 센다."""
    site = Site(client)
    w = site.workers[0]
    t2 = site.new_task()
    site.send(t2["id"], [w["id"]])
    card = site.card(w)
    for st in card["steps"]:
        site.log(w, card["assignment_id"], st["id"])
    data = site.live()
    me = next(x for x in data["workers"] if x["worker_id"] == w["id"])
    assert sorted(t["status"] for t in me["today"]) == ["done", "new"]
    assert me["badge"] == "in_progress" and data["summary"]["working"] == 1
    clk.at(119)
    assert site.worker_live(w)["badge"] == "in_progress"
    clk.at(121)
    data = site.live()
    me = next(x for x in data["workers"] if x["worker_id"] == w["id"])
    assert me["badge"] == "offline" and data["summary"]["working"] == 1


def test_stuck_steps_counts_distinct_steps_not_workers(client, clk):
    """'막힘 의심 n단계'는 단계 수다. 두 사람이 같은 단계에서 막히면 1, 다른 단계면 2."""
    site = Site(client, n_workers=3)
    a, b, c = site.workers
    for w in (a, b):
        card = site.card(w)
        site.presence(w, card["assignment_id"], card["steps"][0]["id"], replay=3)
    data = site.live()
    assert sorted(x["badge"] for x in data["workers"]) == ["new", "stuck_suspect", "stuck_suspect"]
    assert data["summary"]["stuck_steps"] == 1
    card = site.card(c)
    site.log(c, card["assignment_id"], card["steps"][0]["id"])
    site.presence(c, card["assignment_id"], card["steps"][1]["id"], replay=3)
    assert site.live()["summary"]["stuck_steps"] == 2


def test_new_worker_is_not_offline_and_idle_without_work(client, clk):
    site = Site(client, n_workers=1)
    idle = site.add_worker("쉬는 사람")
    clk.at(1000)
    data = site.live()
    by = {x["worker_id"]: x for x in data["workers"]}
    assert by[site.workers[0]["id"]]["badge"] == "new"
    assert by[idle["id"]]["badge"] == "idle" and by[idle["id"]]["current"] is None
    assert data["summary"]["total_workers"] == 2 and data["summary"]["working"] == 0


def test_done_does_not_count_help_and_help_badges(client, clk):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    aid, s1, s2 = card["assignment_id"], card["steps"][0]["id"], card["steps"][1]["id"]
    site.log(w, aid, s1)
    h = site.help(w, aid, s2)
    data = site.live()
    me = next(x for x in data["workers"] if x["worker_id"] == w["id"])
    assert me["badge"] == "help"
    assert me["today"][0]["status"] == "in_progress"  # 도움은 완료로 세지 않는다
    assert data["summary"]["open_help"] == 1
    band = data["help"][0]
    assert band["worker_name"] == w["display_name"] and band["task_id"] == site.task["id"]
    assert band["step_order"] == 2 and band["source_step_id"] == site.task["steps"][1]["id"]
    assert band["step_thumb_url"] == band["step_symbol_url"] and band["step_thumb_url"]
    r = client.post(f"/api/employer/help/{h['id']}/acknowledge", headers=site.h)
    assert r.status_code == 200
    data = site.live()
    assert next(x for x in data["workers"] if x["worker_id"] == w["id"])["badge"] == "help_acked"
    assert data["summary"]["open_help"] == 0 and data["help"][0]["state"] == "acknowledged"
    client.post(f"/api/employer/help/{h['id']}/resolve", headers=site.h)
    site.log(w, aid, s2)
    me = site.worker_live(w)
    assert me["badge"] == "done" and me["current"] is None
    assert site.live()["help"] == []


def test_employer_help_list_has_source_step_and_thumb(client):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    site.help(w, card["assignment_id"], card["steps"][0]["id"])
    rows = client.get("/api/employer/help", headers=site.h).json()
    assert rows[0]["source_step_id"] == site.task["steps"][0]["id"]
    assert rows[0]["step_thumb_url"] == rows[0]["step_symbol_url"]


def test_live_has_no_percent_fields(client):
    site = Site(client)
    body = client.get("/api/employer/live", headers=site.h).text
    assert "rate" not in body and "percent" not in body and "%" not in body


# --- 3. presence ------------------------------------------------------------------------------

def _stored(worker_id):
    with SessionLocal() as db:
        return db.get(WorkerPresence, worker_id)


def test_presence_clock_correction_slow_fast_and_absurd(client, clk):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    aid, s1, s2 = card["assignment_id"], card["steps"][0]["id"], card["steps"][1]["id"]
    clk.at(600)  # 보낸 지 10분 뒤(단계 시작 시각은 보낸 시각보다 앞설 수 없다)
    # 기기 시계가 한 시간 늦음: 30초 전에 연 단계
    slow = datetime(2026, 11, 10, 1, 0, 0)
    assert site.presence(w, aid, s1, started=slow, sent=slow + timedelta(seconds=30)).status_code == 204
    p = _stored(w["id"])
    assert abs((clk.now() - p.step_started_at).total_seconds() - 30) < 1
    # 기기 시계가 하루 빠름: 45초 전에 연 단계
    fast = clk.now() + timedelta(days=1)
    assert site.presence(w, aid, s2, started=fast, sent=fast + timedelta(seconds=45)).status_code == 204
    p = _stored(w["id"])
    assert p.step_id == s2 and abs((clk.now() - p.step_started_at).total_seconds() - 45) < 1
    # 엉터리 연도·읽지 못하는 값: 500 없이 지금으로 본다
    for raw in ({"step_started_at": "0001-01-01T00:00:00", "client_sent_at": "9999-12-31T23:00:00-09:00"},
                {"step_started_at": "엉터리", "client_sent_at": 12},
                {"step_started_at": None, "client_sent_at": None}):
        clk.at(clk.offset + 20)
        r = site.presence(w, aid, s1, raw=raw)
        assert r.status_code == 204, r.text
        assert _stored(w["id"]).step_started_at == clk.now()
    # 시작이 보낸 시각보다 뒤(뒤집힘)·하루 넘게 앞: 지금으로 본다
    clk.at(clk.offset + 20)
    t = datetime(2026, 5, 5)
    site.presence(w, aid, s2, started=t + timedelta(seconds=10), sent=t)
    assert _stored(w["id"]).step_started_at == clk.now()


def test_presence_other_assignment_404_and_wrong_step_400(client):
    a = Site(client)
    b = Site(client)
    card_b = b.card(b.workers[0])
    r = a.presence(a.workers[0], card_b["assignment_id"], card_b["steps"][0]["id"])
    assert r.status_code == 404
    card_a = a.card(a.workers[0])
    r = a.presence(a.workers[0], card_a["assignment_id"], card_b["steps"][0]["id"])
    assert r.status_code == 400
    r = client.post("/api/worker/presence", headers=a.h, json={"assignment_id": card_a["assignment_id"]})
    assert r.status_code == 403  # 사업주 토큰은 안 됨


def test_presence_same_content_not_rewritten_within_15s(client, clk):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    aid, s1 = card["assignment_id"], card["steps"][0]["id"]
    t0 = datetime(2026, 1, 1)
    site.presence(w, aid, s1, started=t0, sent=t0)
    first = _stored(w["id"]).updated_at
    clk.at(10)
    site.presence(w, aid, s1, started=t0, sent=t0 + timedelta(seconds=10))
    assert _stored(w["id"]).updated_at == first
    site.presence(w, aid, s1, started=t0, sent=t0 + timedelta(seconds=10), replay=1)  # 내용이 다르면 바로 쓴다
    assert _stored(w["id"]).updated_at == clk.now() and _stored(w["id"]).replay_count == 1
    clk.at(30)
    site.presence(w, aid, s1, started=t0, sent=t0 + timedelta(seconds=30.4), replay=1)
    assert _stored(w["id"]).updated_at == clk.now()
    # 시작 시각은 처음 잰 값을 지킨다(같은 단계)
    assert _stored(w["id"]).step_started_at == clk.base


def test_presence_without_step_clears_dwell(client):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    assert site.presence(w, card["assignment_id"], None).status_code == 204
    p = _stored(w["id"])
    assert p.step_id is None and p.step_started_at is None
    assert site.worker_live(w)["badge"] == "new"


# --- 4. 캐시·세션 제한·쿼리 수·열람 기록 ----------------------------------------------------------

def test_two_tabs_no_429(client, monkeypatch):
    site = Site(client, n_workers=2)
    t = {"now": 1000.0}
    monkeypatch.setattr(live, "_mono", lambda: t["now"])
    calls = []
    real = live.compute
    monkeypatch.setattr(live, "compute", lambda db, eid: calls.append(t["now"]) or real(db, eid))
    # 같은 토큰을 쓰는 두 탭이 5초마다, 2.5초 어긋나게 1분 동안 부른다.
    ticks = sorted([("a", i * 5.0) for i in range(12)] + [("b", 2.5 + i * 5.0) for i in range(12)],
                   key=lambda x: x[1])
    statuses = []
    for _tab, at in ticks:
        t["now"] = 1000.0 + at
        statuses.append(client.get("/api/employer/live", headers=site.h).status_code)
    assert statuses.count(429) == 0 and len(statuses) == 24
    assert len(calls) <= 15
    # 다른 로그인(다른 세션) 탭이 하나 더 있어도 계산 수는 같은 캐시를 쓴다
    other = live._session_key("Bearer other")
    assert other != live._session_key(site.h["Authorization"])


def test_db_compute_at_most_15_per_minute_with_many_tabs(client, monkeypatch):
    site = Site(client)
    from auth import make_token
    tabs = [{"Authorization": f"Bearer {make_token(site.employer_id, 'employer', ttl=3600 + i)}"} for i in range(4)]
    t = {"now": 5000.0}
    monkeypatch.setattr(live, "_mono", lambda: t["now"])
    calls = []
    real = live.compute
    monkeypatch.setattr(live, "compute", lambda db, eid: calls.append(1) or real(db, eid))
    for step in range(120):  # 0.5초마다 네 탭 중 하나(세션마다 분당 30번)
        t["now"] = 5000.0 + step * 0.5
        r = client.get("/api/employer/live", headers=tabs[step % 4])
        assert r.status_code == 200
    assert len(calls) <= 15


def test_session_429_after_30_per_minute(client):
    site = Site(client, task=False)
    codes = [client.get("/api/employer/live", headers=site.h).status_code for _ in range(31)]
    assert codes[:30] == [200] * 30
    assert codes[30] == 429


def _count_queries(fn):
    n = {"q": 0}

    def before(*_a, **_k):
        n["q"] += 1

    event.listen(engine, "before_cursor_execute", before)
    try:
        out = fn()
    finally:
        event.remove(engine, "before_cursor_execute", before)
    return out, n["q"]


def test_query_count_cap_with_20_workers(client):
    site = Site(client, n_workers=20)
    for w in site.workers[:10]:
        card = site.card(w)
        site.presence(w, card["assignment_id"], card["steps"][0]["id"])
        site.log(w, card["assignment_id"], card["steps"][0]["id"])
    site.help(site.workers[0], site.card(site.workers[0])["assignment_id"], site.card(site.workers[0])["steps"][1]["id"])
    with SessionLocal() as db:
        out, q = _count_queries(lambda: live.compute(db, site.employer_id))
    assert len(out.workers) == 20
    assert q <= 10, q
    live._cache.clear()
    r, q_req = _count_queries(lambda: client.get("/api/employer/live", headers=site.h))
    assert r.status_code == 200
    assert q_req <= 13, q_req  # 계산 + 열람 기록(묶음 조회 1 + 쓰기)


def test_live_audit_one_row_per_worker_deduped(client):
    site = Site(client, n_workers=3)
    for _ in range(3):
        site.live()
    with SessionLocal() as db:
        rows = db.scalars(select(AccessAuditLog.worker_id).where(
            AccessAuditLog.actor_id == site.employer_id, AccessAuditLog.action == "live.view")).all()
    assert sorted(rows) == sorted(w["id"] for w in site.workers)


# --- 5. 타임라인 ------------------------------------------------------------------------------

def test_timeline_steps_and_events(client):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    aid, s1, s2 = card["assignment_id"], card["steps"][0]["id"], card["steps"][1]["id"]
    site.log(w, aid, s1, duration_sec=42.0, replay_count=2, prev_count=1)
    h = site.help(w, aid, s2)
    client.post(f"/api/employer/help/{h['id']}/resolve", headers=site.h)
    r = client.get(f"/api/employer/workers/{w['id']}/timeline", headers=site.h)
    assert r.status_code == 200, r.text
    tl = r.json()
    a = tl["assignments"][0]
    assert a["status"] == "in_progress" and a["version_no"] == 1
    st1, st2 = a["steps"]
    assert (st1["completed"], st1["duration_sec"], st1["replay_count"], st1["prev_count"]) == (True, 42.0, 2, 1)
    assert st1["source_step_id"] == site.task["steps"][0]["id"]
    assert (st2["completed"], st2["help_count"]) == (False, 1)
    kinds = [e["kind"] for e in tl["events"]]
    assert kinds == ["step_done", "help_open", "help_resolved"]
    assert tl["events"][1]["step_order"] == 2
    # 다른 날은 비어 있고, 남의 근로자는 404, 날짜가 이상하면 422
    assert client.get(f"/api/employer/workers/{w['id']}/timeline?date=2020-01-01",
                      headers=site.h).json()["assignments"] == []
    other = Site(client, task=False)
    assert client.get(f"/api/employer/workers/{w['id']}/timeline", headers=other.h).status_code == 404
    assert client.get(f"/api/employer/workers/{w['id']}/timeline?date=어제", headers=site.h).status_code == 422


def test_performance_log_stores_prev_count(client):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    site.log(w, card["assignment_id"], card["steps"][0]["id"], prev_count=4)
    with SessionLocal() as db:
        log = db.scalar(select(PerformanceLog).where(PerformanceLog.assignment_id == card["assignment_id"]))
        assert log.prev_count == 4
    # 옛 기기(prev_count 없음)는 0
    site.log(site.workers[0], card["assignment_id"], card["steps"][1]["id"])
    with SessionLocal() as db:
        assert db.scalar(select(func.min(PerformanceLog.prev_count)).where(
            PerformanceLog.assignment_id == card["assignment_id"])) == 0


def test_delete_worker_removes_presence(client):
    site = Site(client)
    w = site.workers[0]
    card = site.card(w)
    site.presence(w, card["assignment_id"], card["steps"][0]["id"])
    assert _stored(w["id"]) is not None
    assert client.delete(f"/api/workers/{w['id']}", headers=site.h).status_code == 200
    assert _stored(w["id"]) is None


# --- 6. 코칭 카드 ------------------------------------------------------------------------------

def _runs(site, w, step_index, n, *, duration=10.0, replay=0, task_id=None):
    """같은 직무를 n번 보내고(다 하면 새 배정) 그 단계에 완료 기록을 남긴다. 나머지 단계도 끝낸다."""
    tid = task_id or site.task["id"]
    for _ in range(n):
        card = site.card(w, tid)
        if card["status"] == "done":
            site.send(tid, [w["id"]])
            card = site.card(w, tid)
        for i, s in enumerate(card["steps"]):
            if i == step_index:
                site.log(w, card["assignment_id"], s["id"], duration_sec=duration, replay_count=replay)
            else:
                site.log(w, card["assignment_id"], s["id"])


def _coaching(site):
    r = site.client.get("/api/employer/coaching?days=7", headers=site.h)
    assert r.status_code == 200, r.text
    return r.json()


def _set_sentence(site, step_index, sentence):
    sid = site.client.get(f"/api/tasks/{site.task['id']}", headers=site.h).json()["steps"][step_index]["id"]
    r = site.client.patch(f"/api/tasks/{site.task['id']}/steps/{sid}", headers=site.h, json={"sentence": sentence})
    assert r.status_code == 200, r.text


def test_coaching_three_kinds(client):
    site = Site(client)
    w = site.workers[0]
    # 1단계: 오래 걸림 → split
    _runs(site, w, 0, 3, duration=200.0)
    cards = _coaching(site)
    assert [(c["suggestion"], c["step_id"]) for c in cards] == [("split", site.task["steps"][0]["id"])]
    c = cards[0]
    assert c["signals"] == {"replay_avg": 0.0, "duration_avg_sec": pytest.approx(200.0), "help_count": 0, "runs": 3}
    assert c["after"] is None and c["thumb_url"] and c["task_title"]

    # 2단계: 다시 듣기 많음 + 짧은 문장 + 그림(사진 아님) → photo
    site2 = Site(client)
    _runs(site2, site2.workers[0], 1, 3, replay=3)
    assert [c["suggestion"] for c in _coaching(site2)] == ["photo"]

    # 긴 문장 + 다시 듣기 많음 → easy_words
    site3 = Site(client)
    _set_sentence(site3, 0, "선반 아래 칸에 있는 파란 상자를 꺼내서 바닥에 놓으세요")
    site3.send(site3.task["id"], [site3.workers[0]["id"]])
    _runs(site3, site3.workers[0], 0, 3, replay=4)
    assert [c["suggestion"] for c in _coaching(site3)] == ["easy_words"]


def test_coaching_needs_three_runs_or_two_helps(client):
    site = Site(client)
    w = site.workers[0]
    _runs(site, w, 0, 2, duration=300.0)
    assert _coaching(site) == []
    card = site.card(w)
    if card["status"] == "done":
        site.send(site.task["id"], [w["id"]])
        card = site.card(w)
    for _ in range(2):
        h = site.help(w, card["assignment_id"], card["steps"][1]["id"])
        client.post(f"/api/employer/help/{h['id']}/resolve", headers=site.h)
    cards = _coaching(site)
    two = [c for c in cards if c["source_step_id"] == site.task["steps"][1]["id"]]
    assert two and two[0]["signals"]["help_count"] == 2 and two[0]["suggestion"] == "photo"


def test_coaching_after_compares_fixed_version(client):
    site = Site(client)
    w = site.workers[0]
    _runs(site, w, 0, 3, duration=200.0)
    _set_sentence(site, 0, "상자를 드세요")
    site.send(site.task["id"], [w["id"]])
    _runs(site, w, 0, 2, duration=30.0)
    cards = _coaching(site)
    c = next(x for x in cards if x["source_step_id"] == site.task["steps"][0]["id"])
    assert c["signals"]["runs"] == 3 and c["signals"]["duration_avg_sec"] == pytest.approx(200.0)
    assert c["after"]["runs"] == 2 and c["after"]["duration_avg_sec"] == pytest.approx(30.0)
    assert c["after"]["since_version_no"] >= 2
    assert c["sentence"] == "상자를 드세요"


def test_coaching_after_excludes_split_steps(client, monkeypatch):
    site = Site(client)
    w = site.workers[0]
    _runs(site, w, 0, 3, duration=200.0)
    # 1단계를 두 단계로 나눈다(rewrite → 새 단계 id = 새 source_step_id)
    import ai_client
    monkeypatch.setattr(ai_client, "split_hint", lambda sentence: True)  # 가짜 분해가 두 단계를 준다
    sid = site.task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{site.task['id']}/steps/{sid}/rewrite", headers=site.h,
                    json={"sentence": "상자를 들고 옮기세요"})
    assert r.status_code == 200, r.text
    assert len(r.json()["split_step_ids"]) == 2
    from conftest import give_pictures
    give_pictures(client, site.token, site.task["id"])
    site.send(site.task["id"], [w["id"]])
    new_steps = client.get(f"/api/tasks/{site.task['id']}", headers=site.h).json()["steps"]
    assert sid not in {s["id"] for s in new_steps}
    _runs(site, w, 0, 3, duration=300.0)
    cards = _coaching(site)
    # 나뉜 원래 단계는 마지막 버전에 없어 카드가 없고, 새 단계는 앞 버전이 없어 after가 없다
    assert all(c["source_step_id"] != sid for c in cards)
    fresh = [c for c in cards if c["source_step_id"] == new_steps[0]["id"]]
    assert fresh and fresh[0]["after"] is None and fresh[0]["signals"]["runs"] == 3


def test_coaching_max_six_and_other_employer_empty(client):
    site = Site(client)
    other = Site(client, task=False)
    _runs(site, site.workers[0], 0, 3, duration=200.0)
    assert _coaching(other) == []
    assert len(_coaching(site)) <= 6


# --- 7. 마이그레이션·관리 명령 ----------------------------------------------------------------

def test_0009_upgrade_downgrade_upgrade_again():
    import tempfile

    from sqlalchemy import create_engine

    import db_migrate
    eng = create_engine(f"sqlite:///{tempfile.mkdtemp()}/v9.db")
    db_migrate.upgrade_to_head(eng)
    assert {"worker_presence", "push_subscriptions", "client_events"} <= set(inspect(eng).get_table_names())
    assert "prev_count" in {c["name"] for c in inspect(eng).get_columns("performance_logs")}
    log_indexes = {i["name"] for i in inspect(eng).get_indexes("performance_logs")}
    db_migrate.downgrade(eng, "0008_step_review")  # 한 단계 아래(0009 → 0008)
    tables = set(inspect(eng).get_table_names())
    assert not ({"worker_presence", "push_subscriptions", "client_events"} & tables)
    assert "prev_count" not in {c["name"] for c in inspect(eng).get_columns("performance_logs")}
    assert {i["name"] for i in inspect(eng).get_indexes("performance_logs")} == log_indexes
    db_migrate.upgrade_to_head(eng)
    assert db_migrate.is_at_head(eng)
    with eng.begin() as conn:
        conn.execute(text("INSERT INTO client_events (id, employer_id, actor, name, created_at) "
                          "VALUES ('x', 'e', 'worker', 'step_view', '2026-01-01')"))


def test_manage_vapid_keys(tmp_path, capsys):
    import manage
    out = tmp_path / "vapid.pem"
    manage.main(["vapid-keys", "--out", str(out)])
    printed = capsys.readouterr().out
    assert out.read_text().startswith("-----BEGIN PRIVATE KEY-----")
    assert "PRIVATE KEY-----" not in printed  # 개인 키는 화면에 내지 않는다
    pub = next(line.split("=", 1)[1] for line in printed.splitlines() if line.startswith("VAPID_PUBLIC_KEY="))
    raw = base64.urlsafe_b64decode(pub + "=" * (-len(pub) % 4))
    assert len(raw) == 65 and raw[0] == 4
    with pytest.raises(SystemExit):
        manage.main(["vapid-keys", "--out", str(out)])
    manage.main(["vapid-keys", "--out", str(out), "--force"])
