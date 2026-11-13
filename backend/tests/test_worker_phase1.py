"""근로자 화면 0·1차 백엔드 테스트 (scratchpad/p01/contract.md).

지키는 것:
- 도움 요청은 단계 완료로 세지 않는다. 마지막 단계에서 [도와주세요]만 눌러도, 취소해도 직무가 '다 함'이 되지 않는다.
- 완료 기록이 지금 직무의 모든 단계를 덮을 때만 done이고, 그때 열린 도움 요청이 닫힌다.
- 오프라인 대기열이 같은 기록을 다시 보내면 한 번만 센다. 늦게 온 옛 기록은 새 값을 덮지 않는다.
- 오늘 할 일에 이어서 하기 정보(done_step_ids·resume_step_index·is_next·active_help)가 실린다.
- 그림 없는 단계가 있으면 보내기 422, 그림 4상태, 확인 API.
- 자동 접속 코드 4자리(사업장 안 유일), 사업장 단위 로그인 제한, 예전 6자리 코드 로그인 유지.
- 근로자 화면 설정(a11y_prefs) 기본·부분 병합·검증, GET /api/worker/me.
- 근로자·직무·단계 삭제, 보존기간 purge, 내보내기가 도움 요청을 함께 다룬다.
테스트는 네트워크·GPT를 부르지 않는다(conftest 목).
"""
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

import main  # noqa: E402
import ratelimit  # noqa: E402
import retention  # noqa: E402
from auth import hash_password, make_token  # noqa: E402
from conftest import TEST_AAC_IMAGE, auth, give_pictures, publish, delete_task, delete_worker  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import (  # noqa: E402
    AccessAuditLog,
    Assignment,
    Employer,
    HelpRequest,
    PerformanceLog,
    Step,
    Task,
    TaskVersion,
    Worker,
)


# --- 준비 ---------------------------------------------------------------------------------

@pytest.fixture()
def worker(client, employer_token):
    """데모 사업장의 새 근로자(자동 코드) + 로그인 토큰. 끝나면 지운다(다른 테스트의 '근로자 1명' 가정 보호)."""
    r = client.post("/api/workers", json={"display_name": "도움테스트"}, headers=auth(employer_token))
    assert r.status_code == 201, r.text
    w = r.json()
    login = client.post("/api/auth/worker-login",
                        json={"workplace_code": "DEMO01", "access_code": w["access_code"]})
    assert login.status_code == 200, login.text
    w["token"] = login.json()["token"]
    yield w
    delete_worker(client, w['id'], auth(employer_token))


@pytest.fixture()
def other_employer():
    """다른 사업장(남의 리소스 404 확인용)."""
    eid = f"emp-p1-{uuid.uuid4().hex[:6]}"
    with SessionLocal() as db:
        db.add(Employer(id=eid, name="다른 사업주", org_name="다른 작업장", login_id=eid,
                        password_hash=hash_password("pw")))
        db.commit()
    yield {"id": eid, "token": make_token(eid, "employer")}
    with SessionLocal() as db:
        for w in db.scalars(select(Worker).where(Worker.employer_id == eid)).all():
            db.delete(w)
        db.delete(db.get(Employer, eid))
        db.commit()


def _task(client, token, raw="상자를 옮기고 수량을 확인하세요"):
    r = client.post("/api/tasks", json={"raw_input": raw}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _assigned(client, employer_token, worker_id):
    """그림을 붙여 보낸 2단계 직무를 근로자에게 배정한다. (task, assignment_id, step_ids).

    (2a-0) step_ids는 배정에 고정된 버전 단계 id다(근로자 화면이 받는 id, 로그·도움이 가리키는 id). 보낼 때 만든
    버전 단계는 새 uuid라 편집 단계(task["steps"]) id와 다르다. 편집 API를 부를 때는 task["steps"]를 쓴다.
    """
    task = _task(client, employer_token)
    assert publish(client, employer_token, task["id"]).status_code == 200
    r = client.post(f"/api/tasks/{task['id']}/assignments", json={"worker_id": worker_id},
                    headers=auth(employer_token))
    assert r.status_code == 200, r.text
    aid = r.json()[0]["id"]
    return task, aid, _version_step_ids(aid)


def _version_step_ids(assignment_id):
    with SessionLocal() as db:
        a = db.get(Assignment, assignment_id)
        return [vs.id for vs in db.get(TaskVersion, a.task_version_id).steps]


def _log(client, token, assignment_id, step_id, **extra):
    body = {"assignment_id": assignment_id, "step_id": step_id, "duration_sec": 5.0,
            "replay_count": 0, "stuck": False}
    body.update(extra)
    return client.post("/api/performance-logs", headers=auth(token), json=body)


def _help(client, token, assignment_id, step_id=None, **extra):
    body = {"assignment_id": assignment_id, "step_id": step_id, **extra}
    return client.post("/api/worker/help", headers=auth(token), json=body)


def _today(client, token, include_done=None):
    url = "/api/worker/me/today" + ("" if include_done is None else f"?include_done={str(include_done).lower()}")
    r = client.get(url, headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _card(cards, assignment_id):
    return next(c for c in cards if c["assignment_id"] == assignment_id)


def _assignment_status(assignment_id):
    with SessionLocal() as db:
        return db.get(Assignment, assignment_id).status


# --- 버그 수정: 도움 요청은 완료가 아니다 -------------------------------------------------

def test_help_on_last_step_does_not_complete_assignment(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    assert _log(client, worker["token"], aid, s1).status_code == 201
    r = _help(client, worker["token"], aid, s2)
    assert r.status_code == 201, r.text
    assert r.json()["state"] == "open" and r.json()["step_order"] == 2

    assert _assignment_status(aid) == "assigned"
    card = _card(_today(client, worker["token"]), aid)
    assert card["status"] == "in_progress"
    assert card["done_step_ids"] == [s1]
    assert card["resume_step_index"] == 1
    assert card["active_help"]["id"] == r.json()["id"] and card["active_help"]["step_id"] == s2
    # 도움 요청은 수행 로그에 쓰이지 않는다.
    with SessionLocal() as db:
        assert db.scalar(select(PerformanceLog).where(PerformanceLog.assignment_id == aid,
                                                      PerformanceLog.step_id == s2)) is None


def test_help_on_only_step_left_keeps_status_new(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    assert _help(client, worker["token"], aid, s2).status_code == 201
    card = _card(_today(client, worker["token"]), aid)
    assert card["status"] == "new" and card["done_step_ids"] == [] and card["resume_step_index"] == 0


def test_stuck_signal_without_completion_does_not_complete(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    _log(client, worker["token"], aid, s1)
    r = _log(client, worker["token"], aid, s2, stuck=True, completed=False)
    assert r.status_code == 201
    assert r.json() == {"ok": True, "assignment_status": "assigned", "duplicate": False, "applied": True}
    assert _assignment_status(aid) == "assigned"
    hist = next(c for c in client.get("/api/worker/me/history", headers=auth(worker["token"])).json()
                if c["assignment_id"] == aid)
    assert [s["completed"] for s in hist["steps"]] == [True, False]
    # 끝낸 단계에 나중에 신호만 와도 완료가 내려가지 않는다(올리기만 한다).
    _log(client, worker["token"], aid, s1, stuck=True, completed=False)
    assert _card(_today(client, worker["token"]), aid)["done_step_ids"] == [s1]


def test_cancel_help_does_not_complete(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    _log(client, worker["token"], aid, s1)
    h = _help(client, worker["token"], aid, s2).json()
    r = client.post(f"/api/worker/help/{h['id']}/cancel", headers=auth(worker["token"]))
    assert r.status_code == 200 and r.json()["state"] == "cancelled" and r.json()["cancelled_at"]
    assert _assignment_status(aid) == "assigned"
    card = _card(_today(client, worker["token"]), aid)
    assert card["status"] == "in_progress" and card["active_help"] is None


def test_completing_all_steps_marks_done_and_resolves_open_help(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    _log(client, worker["token"], aid, s1)
    h = _help(client, worker["token"], aid, s2).json()
    r = _log(client, worker["token"], aid, s2)
    assert r.status_code == 201 and r.json()["assignment_status"] == "done"
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "resolved" and got["resolution"] == "step_done" and got["resolved_at"]

    # 기본(include_done 생략)은 예전처럼 끝낸 일을 뺀다.
    assert aid not in [c["assignment_id"] for c in _today(client, worker["token"])]
    card = _card(_today(client, worker["token"], include_done=True), aid)
    assert card["status"] == "done" and card["done_step_ids"] == [s1, s2]
    assert card["resume_step_index"] == 2 and card["is_next"] is False
    assert card["completed_at"] is not None and card["assigned_at"] is not None
    assert card["active_help"] is None


def test_step_completion_resolves_acknowledged_help_too(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s1).json()
    client.post(f"/api/employer/help/{h['id']}/acknowledge", headers=auth(employer_token))
    _log(client, worker["token"], aid, s1)
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "resolved" and got["resolution"] == "step_done"
    # 직무는 아직 1단계만 끝났다.
    assert _assignment_status(aid) == "assigned"


def test_done_is_judged_against_pinned_version(client, employer_token, worker):
    """(2a-0, 결정 5) 완료 판정은 배정에 고정된 버전 단계로 한다. 하는 중에 사업주가 단계를 더해도 그 단계는
    다음 배정부터라, 보낸 2단계를 다 끝내면 done이다. 예전(0006)에는 지금 단계 기준이라 더한 3단계가 남았다."""
    task, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    added = client.post(f"/api/tasks/{task['id']}/steps", json={"sentence": "정리하세요."},
                        headers=auth(employer_token))
    assert added.status_code == 201
    _log(client, worker["token"], aid, s1)
    assert _assignment_status(aid) == "assigned"
    assert _log(client, worker["token"], aid, s2).json()["assignment_status"] == "done"


# --- 오프라인 대기열: 멱등 -------------------------------------------------------------------

def test_duplicate_client_event_id_is_counted_once(client, employer_token, worker):
    task, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    first = _log(client, worker["token"], aid, s1, duration_sec=10.0, client_event_id="ev-1")
    assert first.status_code == 201 and first.json()["applied"] is True
    again = _log(client, worker["token"], aid, s1, duration_sec=99.0, client_event_id="ev-1")
    assert again.status_code == 200
    assert again.json() == {"ok": True, "assignment_status": "assigned", "duplicate": True, "applied": False}
    with SessionLocal() as db:
        logs = db.scalars(select(PerformanceLog).where(PerformanceLog.assignment_id == aid)).all()
    assert len(logs) == 1 and logs[0].duration_sec == 10.0
    dash = client.get(f"/api/dashboard/tasks/{task['id']}?worker_id={worker['id']}",
                      headers=auth(employer_token)).json()
    assert dash["completed_steps"] == 1


def test_late_old_record_does_not_overwrite_newer(client, employer_token, worker):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    now = datetime.now(timezone.utc)
    newer = _log(client, worker["token"], aid, s1, duration_sec=30.0, client_event_id="ev-new",
                 client_completed_at=now.isoformat())
    assert newer.status_code == 201
    older = _log(client, worker["token"], aid, s1, duration_sec=3.0, client_event_id="ev-old",
                 client_completed_at=(now - timedelta(seconds=20)).isoformat())
    assert older.status_code == 200
    assert older.json() == {"ok": True, "assignment_status": "assigned", "duplicate": False, "applied": False}
    with SessionLocal() as db:
        log = db.scalar(select(PerformanceLog).where(PerformanceLog.assignment_id == aid))
        assert log.duration_sec == 30.0 and log.client_event_id == "ev-new"


def test_client_time_is_clamped(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    future = datetime.now(timezone.utc) + timedelta(days=3)
    past = datetime.now(timezone.utc) - timedelta(days=3)
    _log(client, worker["token"], aid, s1, client_completed_at=future.isoformat())
    _log(client, worker["token"], aid, s2, client_completed_at=past.isoformat())
    limit = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=1)
    with SessionLocal() as db:
        a = db.get(Assignment, aid)
        logs = {log.step_id: log for log in
                db.scalars(select(PerformanceLog).where(PerformanceLog.assignment_id == aid)).all()}
        assert logs[s1].completed_at <= limit  # 미래 시각은 서버 시각으로
        assert logs[s2].completed_at == a.assigned_date  # 배정 전 시각은 배정 시각으로


def test_log_status_codes_unchanged_for_errors(client, employer_token, worker, worker_token):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    # 남의 배정 404, 다른 직무 단계 400, 너무 긴 키 422
    assert _log(client, worker_token, aid, s1).status_code == 404
    assert _log(client, worker["token"], aid, "nope").status_code == 400
    assert _log(client, worker["token"], aid, s1, client_event_id="x" * 65).status_code == 422


# --- 오늘 할 일 --------------------------------------------------------------------------------

def test_today_order_is_next_and_heartbeat(client, employer_token, worker):
    _, a1, (a1s1, a1s2) = _assigned(client, employer_token, worker["id"])
    _, a2, _ = _assigned(client, employer_token, worker["id"])
    cards = _today(client, worker["token"], include_done=True)
    assert [c["assignment_id"] for c in cards] == [a1, a2]  # 사업주가 보낸 순서
    assert [c["is_next"] for c in cards] == [True, False]
    assert all(s["picture_state"] == "confirmed" for s in cards[0]["steps"])
    with SessionLocal() as db:
        seen = db.get(Worker, worker["id"]).last_seen_at
    assert seen is not None

    _log(client, worker["token"], a1, a1s1)
    _log(client, worker["token"], a1, a1s2)
    cards = _today(client, worker["token"], include_done=True)
    assert [c["assignment_id"] for c in cards] == [a1, a2]  # 끝낸 카드를 아래로 내리는 일은 프론트가 한다
    assert [c["status"] for c in cards] == ["done", "new"]
    assert [c["is_next"] for c in cards] == [False, True]
    # 기본 응답에도 새 필드가 실린다.
    only = _today(client, worker["token"])
    assert [c["assignment_id"] for c in only] == [a2] and only[0]["is_next"] is True


def test_last_seen_is_not_rewritten_within_30_seconds(client, employer_token, worker):
    _today(client, worker["token"])
    with SessionLocal() as db:
        first = db.get(Worker, worker["id"]).last_seen_at
    _today(client, worker["token"])
    with SessionLocal() as db:
        assert db.get(Worker, worker["id"]).last_seen_at == first
        w = db.get(Worker, worker["id"])
        w.last_seen_at = first - timedelta(minutes=5)
        db.commit()
    _today(client, worker["token"])
    with SessionLocal() as db:
        assert db.get(Worker, worker["id"]).last_seen_at > first - timedelta(minutes=5)


# --- 도움 요청 API ---------------------------------------------------------------------------

def test_help_create_is_idempotent_while_active(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    first = _help(client, worker["token"], aid, s1, client_request_id="press-1")
    assert first.status_code == 201
    resend = _help(client, worker["token"], aid, s1, client_request_id="press-1")
    assert resend.status_code == 200 and resend.json()["id"] == first.json()["id"]
    other_step = _help(client, worker["token"], aid, s2)
    assert other_step.status_code == 200 and other_step.json()["id"] == first.json()["id"]
    assert other_step.json()["step_id"] == s2 and other_step.json()["state"] == "open"
    # 단계 없이(시작·완료 화면) 불러도 된다. 열린 요청이 있으면 그 요청이 돌아온다.
    no_step = _help(client, worker["token"], aid)
    assert no_step.status_code == 200 and no_step.json()["step_id"] == s2
    with SessionLocal() as db:
        assert len(db.scalars(select(HelpRequest).where(HelpRequest.assignment_id == aid)).all()) == 1


def test_help_without_step_and_on_done_assignment(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    r = _help(client, worker["token"], aid)
    assert r.status_code == 201 and r.json()["step_id"] is None and r.json()["step_order"] is None
    _log(client, worker["token"], aid, s1)
    _log(client, worker["token"], aid, s2)
    # 2차 검증: 다 끝낸 일에서는 새 도움 요청을 열지 않는다(사업주 화면에 새 호출로 뜨지 않게).
    r = _help(client, worker["token"], aid, s2, client_request_id="after-done")
    assert r.status_code == 409
    assert client.get("/api/employer/help", headers=auth(employer_token)).json() == []


def test_help_rejects_other_assignment_and_foreign_step(client, employer_token, worker, worker_token):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    assert _help(client, worker_token, aid, s1).status_code == 404  # 남의 배정
    assert _help(client, worker["token"], "no-such").status_code == 404
    other = _task(client, employer_token)
    r = _help(client, worker["token"], aid, other["steps"][0]["id"])
    assert r.status_code == 400 and r.json()["detail"] == "이 배정에 속하지 않는 단계입니다."
    # 남의 요청은 보거나 취소할 수 없다.
    h = _help(client, worker["token"], aid, s1).json()
    assert client.get(f"/api/worker/help/{h['id']}", headers=auth(worker_token)).status_code == 404
    assert client.post(f"/api/worker/help/{h['id']}/cancel", headers=auth(worker_token)).status_code == 404
    assert client.get(f"/api/worker/help/{h['id']}", headers=auth(employer_token)).status_code == 403


def test_help_state_transitions(client, employer_token, worker):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    tok, emp = auth(worker["token"]), auth(employer_token)

    # open → acknowledged → resolved(employer)
    h = _help(client, worker["token"], aid, s1).json()
    ack = client.post(f"/api/employer/help/{h['id']}/acknowledge", headers=emp)
    assert ack.status_code == 200 and ack.json()["state"] == "acknowledged" and ack.json()["acknowledged_at"]
    assert client.post(f"/api/employer/help/{h['id']}/acknowledge", headers=emp).json()["state"] == "acknowledged"
    assert client.get(f"/api/worker/help/{h['id']}", headers=tok).json()["state"] == "acknowledged"
    res = client.post(f"/api/employer/help/{h['id']}/resolve", headers=emp)
    assert res.status_code == 200 and res.json()["state"] == "resolved" and res.json()["resolution"] == "employer"
    assert client.post(f"/api/employer/help/{h['id']}/resolve", headers=emp).status_code == 200  # 멱등
    r = client.post(f"/api/employer/help/{h['id']}/acknowledge", headers=emp)
    assert r.status_code == 409 and r.json()["detail"] == "이미 끝난 도움 요청이에요."
    r = client.post(f"/api/worker/help/{h['id']}/cancel", headers=tok)
    assert r.status_code == 409 and r.json()["detail"] == "이미 끝난 도움 요청이에요."

    # 끝난 뒤 다시 부르면 새 요청이다. open → cancelled
    h2 = _help(client, worker["token"], aid, s1)
    assert h2.status_code == 201 and h2.json()["id"] != h["id"]
    h2 = h2.json()
    assert client.post(f"/api/worker/help/{h2['id']}/cancel", headers=tok).json()["state"] == "cancelled"
    assert client.post(f"/api/worker/help/{h2['id']}/cancel", headers=tok).status_code == 200  # 멱등
    for action in ("acknowledge", "resolve"):
        r = client.post(f"/api/employer/help/{h2['id']}/{action}", headers=emp)
        assert r.status_code == 409 and r.json()["detail"] == "근로자가 이미 취소한 요청이에요."

    # acknowledged → cancelled, open → resolved(employer)
    h3 = _help(client, worker["token"], aid, s1).json()
    client.post(f"/api/employer/help/{h3['id']}/acknowledge", headers=emp)
    assert client.post(f"/api/worker/help/{h3['id']}/cancel", headers=tok).json()["state"] == "cancelled"
    h4 = _help(client, worker["token"], aid, s1).json()
    assert client.post(f"/api/employer/help/{h4['id']}/resolve", headers=emp).json()["state"] == "resolved"


def test_other_employer_cannot_touch_help(client, employer_token, worker, other_employer):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s1).json()
    for action in ("acknowledge", "resolve"):
        r = client.post(f"/api/employer/help/{h['id']}/{action}", headers=auth(other_employer["token"]))
        assert r.status_code == 404 and r.json()["detail"] == "도움 요청을 찾을 수 없습니다."
    listed = client.get("/api/employer/help", headers=auth(other_employer["token"])).json()
    assert h["id"] not in [x["id"] for x in listed]
    # 근로자 토큰으로는 사업주 API를 못 부른다.
    assert client.get("/api/employer/help", headers=auth(worker["token"])).status_code == 403


def test_help_flood_is_throttled(client, employer_token, worker):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    for _ in range(10):
        h = _help(client, worker["token"], aid, s1)
        assert h.status_code == 201
        client.post(f"/api/worker/help/{h.json()['id']}/cancel", headers=auth(worker["token"]))
    r = _help(client, worker["token"], aid, s1)
    assert r.status_code == 429 and r.json()["detail"] == "잠깐 기다렸다가 다시 불러 주세요."
    assert int(r.headers["Retry-After"]) > 0


def test_employer_help_list_states_and_fields(client, employer_token, worker):
    task, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    emp = auth(employer_token)
    h = _help(client, worker["token"], aid, s2).json()
    active = client.get("/api/employer/help", headers=emp)
    assert active.status_code == 200
    row = next(x for x in active.json() if x["id"] == h["id"])
    assert row["worker_name"] == "도움테스트" and row["task_id"] == task["id"]
    assert row["task_title"] == task["title"] and row["step_order"] == 2
    assert row["step_sentence"] == task["steps"][1]["sentence"]
    assert row["step_symbol_url"].endswith(TEST_AAC_IMAGE)
    assert h["id"] in [x["id"] for x in client.get("/api/employer/help?state=open", headers=emp).json()]

    client.post(f"/api/employer/help/{h['id']}/acknowledge", headers=emp)
    assert h["id"] in [x["id"] for x in client.get("/api/employer/help", headers=emp).json()]
    assert h["id"] not in [x["id"] for x in client.get("/api/employer/help?state=open", headers=emp).json()]
    client.post(f"/api/employer/help/{h['id']}/resolve", headers=emp)
    assert h["id"] not in [x["id"] for x in client.get("/api/employer/help", headers=emp).json()]
    assert h["id"] in [x["id"] for x in client.get("/api/employer/help?state=today", headers=emp).json()]
    assert client.get("/api/employer/help?state=all", headers=emp).status_code == 422

    # 근로자 이름이 실리므로 접근 감사가 남는다.
    with SessionLocal() as db:
        assert db.scalar(select(AccessAuditLog).where(AccessAuditLog.action == "help.list",
                                                      AccessAuditLog.worker_id == worker["id"])) is not None


def test_help_list_audit_is_deduped():
    import privacy
    assert "help.list" in privacy.DEDUPED_ACTIONS


def test_notify_hook_is_called_on_new_help(client, employer_token, worker, monkeypatch):
    calls = []
    monkeypatch.setattr(main, "notify_help_opened", lambda db, h: calls.append(h.id))
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s1).json()
    _help(client, worker["token"], aid, s1)  # 이미 열린 요청 → 다시 알리지 않는다
    assert calls == [h["id"]]


def test_dashboard_shows_help_as_stuck_but_not_completed(client, employer_token, worker):
    task, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    _log(client, worker["token"], aid, s1)
    _help(client, worker["token"], aid, s2)
    dash = client.get(f"/api/dashboard/tasks/{task['id']}?worker_id={worker['id']}",
                      headers=auth(employer_token)).json()
    assert dash["completed_steps"] == 1 and dash["stuck_steps"] == [2]
    assert [(s["completed"], s["stuck"]) for s in dash["steps"]] == [(True, False), (False, True)]


# --- (0차) 보내기 검사·그림 4상태 ------------------------------------------------------------

def test_publish_blocked_when_step_has_no_picture(client, employer_token):
    task = _task(client, employer_token)
    assert [s["picture_state"] for s in task["steps"]] == ["none", "none"]
    r = client.post(f"/api/tasks/{task['id']}/publish", headers=auth(employer_token))
    assert r.status_code == 422
    # (2a-0) 보내기 검사와 같은 문구·code·step_ids(contract §1.4).
    assert r.json() == {"detail": "1단계와 2단계에 그림이 없어요. 그림을 고르거나 사진을 올려 주세요.",
                        "code": "send_blocked", "step_ids": [s["id"] for s in task["steps"]]}
    assert client.get(f"/api/tasks/{task['id']}", headers=auth(employer_token)).json()["status"] == "draft"

    client.patch(f"/api/tasks/{task['id']}/steps/{task['steps'][0]['id']}", headers=auth(employer_token),
                 json={"symbol_url": TEST_AAC_IMAGE, "symbol_source": "LOCAL_AAC"})
    r = client.post(f"/api/tasks/{task['id']}/publish", headers=auth(employer_token))
    assert r.status_code == 422 and r.json()["detail"].startswith("2단계에 그림이 없어요.")
    # 그림 없는 직무는 배정도 안 된다(게시된 직무만 배정).
    assert client.post(f"/api/tasks/{task['id']}/assignments",
                       headers=auth(employer_token)).status_code == 400

    give_pictures(client, employer_token, task["id"])
    ok = client.post(f"/api/tasks/{task['id']}/publish", headers=auth(employer_token))
    assert ok.status_code == 200 and ok.json()["status"] == "published"
    assert all(s["picture_state"] == "confirmed" for s in ok.json()["steps"])


def test_republish_checks_again(client, employer_token):
    task = _task(client, employer_token)
    assert publish(client, employer_token, task["id"]).status_code == 200
    with SessionLocal() as db:
        step = db.get(Step, task["steps"][1]["id"])
        step.symbol_url = None
        db.commit()
    r = client.post(f"/api/tasks/{task['id']}/publish", headers=auth(employer_token))
    assert r.status_code == 422 and r.json()["detail"].startswith("2단계에 그림이 없어요.")
    assert r.json()["step_ids"] == [task["steps"][1]["id"]]


def test_publish_blocked_when_task_has_no_steps(client, employer_token):
    with SessionLocal() as db:
        t = Task(employer_id="emp-demo", title="빈 직무", raw_input="", status="draft")
        db.add(t)
        db.commit()
        tid = t.id
    r = client.post(f"/api/tasks/{tid}/publish", headers=auth(employer_token))
    assert r.status_code == 422
    assert r.json() == {"detail": "단계가 하나도 없어요. 단계를 넣어 주세요.", "code": "no_steps", "step_ids": []}
    delete_task(client, tid, auth(employer_token))


def _set_step(step_id, **values):
    with SessionLocal() as db:
        step = db.get(Step, step_id)
        for k, v in values.items():
            setattr(step, k, v)
        db.commit()


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (40, 30), (10, 120, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_picture_states_and_confirm(client, employer_token):
    emp = auth(employer_token)
    task = _task(client, employer_token)
    s1, s2 = (s["id"] for s in task["steps"])
    url = f"/api/tasks/{task['id']}/steps"

    def state(step_id):
        steps = client.get(f"/api/tasks/{task['id']}", headers=emp).json()["steps"]
        return next(s["picture_state"] for s in steps if s["id"] == step_id)

    assert state(s1) == "none"
    r = client.post(f"{url}/{s1}/picture/confirm", headers=emp)
    assert r.status_code == 422
    assert r.json()["detail"] == "그림이 없는 단계는 확인할 수 없어요. 먼저 그림을 골라 주세요."

    _set_step(s1, symbol_url="http://localhost:8000" + TEST_AAC_IMAGE, needs_fallback=False)
    assert state(s1) == "auto_high"
    _set_step(s1, needs_fallback=True)
    assert state(s1) == "choose"
    r = client.post(f"{url}/{s1}/picture/confirm", headers=emp)
    assert r.status_code == 200 and r.json()["picture_state"] == "confirmed"
    # 문장만 고치면 확인은 그대로다.
    client.patch(f"{url}/{s1}", headers=emp, json={"sentence": "상자를 들어요."})
    assert state(s1) == "confirmed"

    # 사진 올리기 → 확인함, 사진 지우기 → 그림 없음
    up = client.post(f"{url}/{s2}/photo", headers=emp, files={"file": ("a.png", _png(), "image/png")})
    assert up.status_code == 200 and up.json()["picture_state"] == "confirmed"
    rm = client.delete(f"{url}/{s2}/photo", headers=emp)
    assert rm.status_code == 200 and rm.json()["picture_state"] == "none"
    with SessionLocal() as db:
        assert db.get(Step, s2).picture_confirmed is False

    assert client.post(f"{url}/nope/picture/confirm", headers=emp).status_code == 404


def test_confirm_requires_owner(client, employer_token, other_employer):
    task = _task(client, employer_token)
    r = client.post(f"/api/tasks/{task['id']}/steps/{task['steps'][0]['id']}/picture/confirm",
                    headers=auth(other_employer["token"]))
    assert r.status_code == 404


# --- 접속 코드 4자리·로그인 제한 ---------------------------------------------------------------

def test_auto_codes_are_four_digits_and_unique(client, employer_token):
    made = []
    try:
        for i in range(8):
            r = client.post("/api/workers", json={"display_name": f"코드{i}"}, headers=auth(employer_token))
            assert r.status_code == 201
            made.append(r.json())
        codes = [w["access_code"] for w in made]
        assert all(len(c) == 4 and c.isdigit() for c in codes)
        assert len(set(codes)) == len(codes) and "1234" not in codes  # 데모 근로자 코드와도 겹치지 않는다
    finally:
        for w in made:
            delete_worker(client, w['id'], auth(employer_token))


def test_auto_code_retries_on_collision(client, employer_token, monkeypatch):
    """처음 뽑은 코드가 사업장 안에서 이미 쓰이면(데모 근로자 1234) 다시 뽑는다."""
    digits = iter("1234" + "5678")
    monkeypatch.setattr(main.secrets, "choice", lambda seq: next(digits))
    r = client.post("/api/workers", json={"display_name": "충돌"}, headers=auth(employer_token))
    assert r.status_code == 201 and r.json()["access_code"] == "5678"
    delete_worker(client, r.json()['id'], auth(employer_token))


def test_legacy_six_digit_code_still_logs_in(client, employer_token):
    r = client.post("/api/workers", json={"display_name": "예전코드", "access_code": "135790"},
                    headers=auth(employer_token))
    assert r.status_code == 201
    try:
        login = client.post("/api/auth/worker-login", json={"workplace_code": "DEMO01", "access_code": "135790"})
        assert login.status_code == 200
    finally:
        delete_worker(client, r.json()['id'], auth(employer_token))


def test_worker_login_returns_workplace_name(client):
    r = client.post("/api/auth/worker-login", json={"workplace_code": "DEMO01", "access_code": "1234"})
    assert r.status_code == 200 and r.json()["workplace_name"] == "잇다 보호작업장"
    emp = client.post("/api/auth/login", json={"login_id": "demo", "password": "demo1234"})
    assert emp.json()["workplace_name"] is None


def test_ip_limit_still_blocks_after_30_failures(client):
    for i in range(30):
        r = client.post("/api/auth/worker-login", json={"workplace_code": "DEMO01", "access_code": f"9{i:03d}"})
        assert r.status_code == 401
    assert client.post("/api/auth/worker-login",
                       json={"workplace_code": "DEMO01", "access_code": "1234"}).status_code == 429


def test_workplace_limit_blocks_ip_rotation(client, monkeypatch):
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    for i in range(60):
        r = client.post("/api/auth/worker-login", json={"workplace_code": "demo-01", "access_code": f"8{i:03d}"},
                        headers={"X-Forwarded-For": f"10.1.{i // 200}.{i % 200}"})
        assert r.status_code == 401, i
    blocked = client.post("/api/auth/worker-login", json={"workplace_code": "DEMO01", "access_code": "1234"},
                          headers={"X-Forwarded-For": "10.9.9.9"})
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 0
    # 다른 사업장(있든 없든)은 영향이 없다.
    other = client.post("/api/auth/worker-login", json={"workplace_code": "ZZZZ99", "access_code": "1234"},
                        headers={"X-Forwarded-For": "10.9.9.10"})
    assert other.status_code == 401


def test_unknown_workplace_is_counted_too(client, monkeypatch):
    monkeypatch.setattr(ratelimit.worker_wp_throttle, "max_failures", 3)
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    for i in range(3):
        client.post("/api/auth/worker-login", json={"workplace_code": "NOPE77", "access_code": "1111"},
                    headers={"X-Forwarded-For": f"10.2.0.{i}"})
    r = client.post("/api/auth/worker-login", json={"workplace_code": "NOPE77", "access_code": "1111"},
                    headers={"X-Forwarded-For": "10.2.0.99"})
    assert r.status_code == 429


# --- 근로자 화면 설정 ---------------------------------------------------------------------------

DEFAULT_PREFS = {"font_size": "normal", "autoplay_sound": True, "tts_rate": 0.9, "sfx": True,
                 "vibration": False, "praise": "normal", "hand": "right", "contrast": "normal"}


def test_a11y_prefs_defaults_patch_and_validation(client, employer_token, worker):
    emp = auth(employer_token)
    listed = next(w for w in client.get("/api/workers", headers=emp).json() if w["id"] == worker["id"])
    assert listed["a11y_prefs"] == DEFAULT_PREFS

    r = client.patch(f"/api/workers/{worker['id']}", headers=emp, json={"a11y_prefs": {"autoplay_sound": False}})
    assert r.status_code == 200 and r.json()["a11y_prefs"] == {**DEFAULT_PREFS, "autoplay_sound": False}
    r = client.patch(f"/api/workers/{worker['id']}", headers=emp, json={"a11y_prefs": {"tts_rate": 0.8}})
    assert r.json()["a11y_prefs"] == {**DEFAULT_PREFS, "autoplay_sound": False, "tts_rate": 0.8}
    # 다른 필드만 고치면 설정은 그대로다.
    r = client.patch(f"/api/workers/{worker['id']}", headers=emp, json={"note": "메모"})
    assert r.json()["a11y_prefs"]["autoplay_sound"] is False

    for bad in ({"tts_rate": 0.7}, {"font_size": "huge"}, {"hand": "both"}, {"unknown": 1},
                {"autoplay_sound": "maybe"}):
        assert client.patch(f"/api/workers/{worker['id']}", headers=emp,
                            json={"a11y_prefs": bad}).status_code == 422, bad

    me = client.get("/api/worker/me", headers=auth(worker["token"]))
    assert me.status_code == 200
    assert me.json() == {"id": worker["id"], "display_name": "도움테스트", "workplace_name": "잇다 보호작업장",
                         "teacher_title": "선생님",
                         "a11y_prefs": {**DEFAULT_PREFS, "autoplay_sound": False, "tts_rate": 0.8}}


def test_a11y_prefs_read_is_tolerant(client, worker):
    with SessionLocal() as db:
        w = db.get(Worker, worker["id"])
        w.a11y_prefs = '{"tts_rate": 3, "sfx": false, "old_key": 1}'
        db.commit()
    prefs = client.get("/api/worker/me", headers=auth(worker["token"])).json()["a11y_prefs"]
    assert prefs == {**DEFAULT_PREFS, "sfx": False}
    with SessionLocal() as db:
        w = db.get(Worker, worker["id"])
        w.a11y_prefs = "깨진 값"
        db.commit()
    assert client.get("/api/worker/me", headers=auth(worker["token"])).json()["a11y_prefs"] == DEFAULT_PREFS


def test_worker_me_requires_worker(client, employer_token):
    assert client.get("/api/worker/me").status_code == 401
    assert client.get("/api/worker/me", headers=auth(employer_token)).status_code == 403


def test_other_employer_cannot_patch_prefs(client, worker, other_employer):
    r = client.patch(f"/api/workers/{worker['id']}", headers=auth(other_employer["token"]),
                     json={"a11y_prefs": {"autoplay_sound": False}})
    assert r.status_code == 404


# --- 삭제·보존·내보내기 연동 ------------------------------------------------------------------

def test_export_includes_help_requests(client, employer_token, worker):
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    _log(client, worker["token"], aid, s1)
    _help(client, worker["token"], aid, s2)
    data = client.get(f"/api/workers/{worker['id']}/export", headers=auth(employer_token)).json()
    assert len(data["help_requests"]) == 1
    h = data["help_requests"][0]
    assert h["assignment_id"] == aid and h["step_order"] == 2 and h["state"] == "open"
    assert set(h) == {"assignment_id", "step_order", "state", "resolution", "created_at",
                      "acknowledged_at", "cancelled_at", "resolved_at"}
    assert data["performance_logs"][0]["completed"] is True
    assert data["worker"]["a11y_prefs"]["autoplay_sound"] is True
    assert "last_seen_at" in data["worker"]


def test_delete_worker_removes_help_requests(client, employer_token):
    w = client.post("/api/workers", json={"display_name": "지울근로자"}, headers=auth(employer_token)).json()
    tok = client.post("/api/auth/worker-login",
                      json={"workplace_code": "DEMO01", "access_code": w["access_code"]}).json()["token"]
    _, aid, (s1, _) = _assigned(client, employer_token, w["id"])
    _help(client, tok, aid, s1)
    assert delete_worker(client, w['id'], auth(employer_token)).status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(HelpRequest).where(HelpRequest.worker_id == w["id"])).all() == []
        assert db.get(Assignment, aid) is None


def test_delete_task_removes_help_requests(client, employer_token, worker):
    task, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    _help(client, worker["token"], aid, s1)
    assert delete_task(client, task['id'], auth(employer_token)).status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(HelpRequest).where(HelpRequest.assignment_id == aid)).all() == []


def test_delete_step_keeps_help_and_its_step(client, employer_token, worker):
    """(2a-0) 도움은 버전 단계를 가리킨다. 사업주가 편집 단계를 지워도 도움의 단계(순서·문장·그림)는 그대로다.
    예전(0006)에는 step_id를 NULL로 끊었다."""
    task, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s2).json()
    r = client.delete(f"/api/tasks/{task['id']}/steps/{task['steps'][1]['id']}", headers=auth(employer_token))
    assert r.status_code == 200
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["step_id"] == s2 and got["step_order"] == 2 and got["state"] == "open"
    row = next(x for x in client.get("/api/employer/help", headers=auth(employer_token)).json()
               if x["id"] == h["id"])
    assert row["step_id"] == s2 and row["step_sentence"] == task["steps"][1]["sentence"]
    assert row["step_symbol_url"]


def test_purge_removes_expired_help_requests(client, employer_token, worker, monkeypatch, tmp_path):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    old = _help(client, worker["token"], aid, s1).json()
    client.post(f"/api/worker/help/{old['id']}/cancel", headers=auth(worker["token"]))
    fresh = _help(client, worker["token"], aid, s1).json()
    with SessionLocal() as db:
        db.get(HelpRequest, old["id"]).created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=400)
        db.commit()
    monkeypatch.setenv("PERFORMANCE_LOG_RETENTION_DAYS", "365")
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "tts"))
    monkeypatch.setenv("PHOTO_DIR", str(tmp_path / "photos"))
    with SessionLocal() as db:
        dry = retention.purge(db, dry_run=True)
        assert dry["help_requests"] >= 1
        assert db.get(HelpRequest, old["id"]) is not None
        report = retention.purge(db)
    assert report["help_requests"] >= 1
    with SessionLocal() as db:
        assert db.get(HelpRequest, old["id"]) is None
        assert db.get(HelpRequest, fresh["id"]) is not None


# --- 1차 검증 반영 ----------------------------------------------------------------------------

def test_assign_blocked_when_published_task_gains_pictureless_step(client, employer_token, worker):
    """보낸 뒤 그림 없는 단계를 더해도 status는 'published'다. 배정에서 다시 봐서 근로자에게 나가지 않게 한다."""
    task = _task(client, employer_token)
    assert publish(client, employer_token, task["id"]).status_code == 200
    r = client.post(f"/api/tasks/{task['id']}/steps", json={"sentence": "바닥을 닦아요"},
                    headers=auth(employer_token))
    assert r.status_code == 201
    new_step = r.json()["steps"][-1]
    _set_step(new_step["id"], symbol_url=None, symbol_media_id=None)
    r = client.post(f"/api/tasks/{task['id']}/assignments", json={"worker_id": worker["id"]},
                    headers=auth(employer_token))
    assert r.status_code == 422
    assert r.json()["detail"] == "3단계에 그림이 없어요. 그림을 고르거나 사진을 올려 주세요."
    assert r.json()["step_ids"] == [new_step["id"]]
    assert _today(client, worker["token"]) == []


def test_help_recall_after_ack_reopens_request(client, employer_token, worker):
    """선생님이 확인한 뒤 근로자가 다시 부르면(새 누름) 요청이 다시 '열림'이 되고 사업주 목록에 다시 뜬다."""
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    emp = auth(employer_token)
    first = _help(client, worker["token"], aid, s1, client_request_id="press-1").json()
    client.post(f"/api/employer/help/{first['id']}/acknowledge", headers=emp)
    assert client.get("/api/employer/help?state=open", headers=emp).json() == []

    again = _help(client, worker["token"], aid, s2, client_request_id="press-2")
    assert again.status_code == 200
    body = again.json()
    assert body["state"] == "open" and body["acknowledged_at"] is None and body["step_id"] == s2
    assert body["created_at"] >= first["created_at"]
    open_ids = [h["id"] for h in client.get("/api/employer/help?state=open", headers=emp).json()]
    assert open_ids == [first["id"]]
    # 같은 누름의 재전송은 그대로 한 건(다시 열지 않는다).
    resend = _help(client, worker["token"], aid, s2, client_request_id="press-2")
    assert resend.status_code == 200 and resend.json()["state"] == "open"


def test_help_recall_after_ack_calls_notify_hook(client, employer_token, worker, monkeypatch):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    calls = []
    monkeypatch.setattr(main, "notify_help_opened", lambda db, h: calls.append(h.id))
    h = _help(client, worker["token"], aid, s1, client_request_id="a").json()
    client.post(f"/api/employer/help/{h['id']}/acknowledge", headers=auth(employer_token))
    _help(client, worker["token"], aid, s1, client_request_id="b")
    assert calls == [h["id"], h["id"]]


def test_worker_login_daily_limit_per_workplace(client, monkeypatch):
    """10분 창이 풀려도 하루 창이 남는다: 사업장 하루 한도를 넘으면 IP를 바꿔도, 맞는 코드여도 429."""
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    monkeypatch.setattr(ratelimit.worker_wp_day_throttle, "max_failures", 5)
    for i in range(5):
        r = client.post("/api/auth/worker-login", json={"workplace_code": "DEMO01", "access_code": f"7{i:03d}"},
                        headers={"X-Forwarded-For": f"10.3.0.{i}"})
        assert r.status_code == 401
        ratelimit.worker_wp_throttle.clear()  # 10분 창이 지났다고 친다
    r = client.post("/api/auth/worker-login", json={"workplace_code": "DEMO01", "access_code": "1234"},
                    headers={"X-Forwarded-For": "10.3.9.9"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 600


def test_worker_login_daily_limit_per_ip(client, monkeypatch):
    monkeypatch.setattr(ratelimit.worker_day_throttle, "max_failures", 4)
    for i in range(4):
        assert client.post("/api/auth/worker-login",
                           json={"workplace_code": f"ZZ{i:04d}", "access_code": "1111"}).status_code == 401
        ratelimit.worker_throttle.clear()
        ratelimit.worker_wp_throttle.clear()
    assert client.post("/api/auth/worker-login",
                       json={"workplace_code": "DEMO01", "access_code": "1234"}).status_code == 429


def test_daily_limit_defaults_bound_guessing_budget():
    """기본 하루 예산: 사업장·IP 각각 하루 100번 이하(1만 개 코드 대입이 며칠 걸리게)."""
    assert ratelimit.worker_wp_day_throttle.max_failures <= 200
    assert ratelimit.worker_day_throttle.max_failures <= 200
    assert ratelimit.worker_wp_day_throttle.window_sec >= 24 * 60 * 60
    assert ratelimit.worker_day_throttle.window_sec >= 24 * 60 * 60


def test_concurrent_first_log_integrity_error_is_retried(client, employer_token, worker, monkeypatch):
    """두 기기가 같은 단계의 첫 기록을 동시에 보내 UNIQUE에 걸려도 500이 아니라 다시 처리한다."""
    from sqlalchemy.exc import IntegrityError

    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    original = main._create_log_once
    state = {"n": 0}

    def racing(payload, response, db, user):
        state["n"] += 1
        if state["n"] == 1:
            # 다른 기기의 기록이 먼저 들어갔다.
            with SessionLocal() as other:
                other.add(PerformanceLog(assignment_id=aid, step_id=s1, completed=True,
                                         completed_at=datetime(2020, 1, 1), duration_sec=1.0,
                                         replay_count=0, stuck=False, client_event_id="dev-b"))
                other.commit()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        return original(payload, response, db, user)

    monkeypatch.setattr(main, "_create_log_once", racing)
    r = _log(client, worker["token"], aid, s1, client_event_id="dev-a")
    assert r.status_code in (200, 201), r.text
    assert state["n"] == 2
    with SessionLocal() as db:
        rows = db.scalars(select(PerformanceLog).where(PerformanceLog.assignment_id == aid)).all()
    assert len(rows) == 1



# --- 2차 검증 -------------------------------------------------------------------------------------

def test_late_earlier_step_log_keeps_help_on_later_step_open(client, employer_token, worker):
    """2단계에서 부른 도움은, 대기열에 남았던 1단계 완료 기록이 늦게 닿아도 열려 있다."""
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s2, client_request_id="r1").json()
    assert _log(client, worker["token"], aid, s1).status_code == 201
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "open" and got["resolution"] is None
    assert [e["id"] for e in client.get("/api/employer/help", headers=auth(employer_token)).json()] == [h["id"]]
    # 그 단계를 끝내면(= 직무를 다 끝내면) 닫힌다.
    _log(client, worker["token"], aid, s2)
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "resolved" and got["resolution"] == "step_done"


def test_same_step_completion_still_closes_help(client, employer_token, worker):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s1).json()
    _log(client, worker["token"], aid, s1)
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "resolved" and _assignment_status(aid) != "done"


def test_cancel_by_client_id_closes_late_and_tombstones_unarrived(client, employer_token, worker):
    """8초 뒤 끊긴 누름: 이미 닿았으면 닫고, 아직 안 닿았으면 '취소됨'을 먼저 남겨 늦은 누름이 열리지 않게 한다."""
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    url = "/api/worker/help/cancel-by-client"
    h = _help(client, worker["token"], aid, s1, client_request_id="late-1").json()
    r = client.post(url, headers=auth(worker["token"]),
                    json={"assignment_id": aid, "step_id": s1, "client_request_id": "late-1"})
    assert r.status_code == 200 and r.json()["id"] == h["id"] and r.json()["state"] == "cancelled"
    r = client.post(url, headers=auth(worker["token"]),
                    json={"assignment_id": aid, "step_id": s2, "client_request_id": "late-2"})
    assert r.status_code == 200 and r.json()["state"] == "cancelled"
    late = _help(client, worker["token"], aid, s2, client_request_id="late-2")
    assert late.status_code == 200 and late.json()["state"] == "cancelled"
    assert client.get("/api/employer/help", headers=auth(employer_token)).json() == []
    assert client.post(url, headers=auth(worker["token"]),
                       json={"assignment_id": aid, "step_id": s1}).status_code == 422


def test_help_is_unique_per_press_and_per_assignment(client, employer_token, worker):
    """확인과 저장 사이에 겹친 두 누름이 열린 요청 두 건을 만들지 못한다(DB 색인)."""
    from sqlalchemy.exc import IntegrityError

    _, aid, _ = _assigned(client, employer_token, worker["id"])
    with SessionLocal() as db:
        db.add(HelpRequest(employer_id="emp-demo", worker_id=worker["id"], assignment_id=aid, state="open",
                           client_request_id="u1"))
        db.commit()
        db.add(HelpRequest(employer_id="emp-demo", worker_id=worker["id"], assignment_id=aid, state="open",
                           client_request_id="u2"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        db.add(HelpRequest(employer_id="emp-demo", worker_id=worker["id"], assignment_id=aid, state="cancelled",
                           client_request_id="u1"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        # 끝난 요청은 여럿이어도 된다.
        for i in range(2):
            db.add(HelpRequest(employer_id="emp-demo", worker_id=worker["id"], assignment_id=aid,
                               state="cancelled", client_request_id=None))
        db.commit()


def test_concurrent_help_integrity_error_returns_existing(client, employer_token, worker, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    original = main._create_help_once
    state = {"n": 0}

    def racing(payload, response, db, user):
        state["n"] += 1
        if state["n"] == 1:
            with SessionLocal() as other:  # 다른 기기의 요청이 먼저 들어갔다
                other.add(HelpRequest(employer_id="emp-demo", worker_id=worker["id"], assignment_id=aid,
                                      step_id=s1, state="open", client_request_id="dev-b"))
                other.commit()
            raise IntegrityError("INSERT", {}, Exception("UNIQUE constraint failed"))
        return original(payload, response, db, user)

    monkeypatch.setattr(main, "_create_help_once", racing)
    r = _help(client, worker["token"], aid, s1, client_request_id="dev-a")
    assert r.status_code == 200 and r.json()["state"] == "open"
    with SessionLocal() as db:
        assert len(db.scalars(select(HelpRequest).where(HelpRequest.assignment_id == aid)).all()) == 1


def test_help_on_yesterdays_assignment_is_refused(client, employer_token, worker):
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    with SessionLocal() as db:
        a = db.get(Assignment, aid)
        a.assigned_date = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=2)
        # (2a-0) 그 일을 하는 날은 scheduled_day다(보낸 시각만 바꾸면 날은 그대로 오늘).
        a.scheduled_day = a.scheduled_day - timedelta(days=2)
        db.commit()
    assert _help(client, worker["token"], aid, s1).status_code == 409
    assert client.get("/api/employer/help", headers=auth(employer_token)).json() == []


def test_negative_duration_is_clamped_not_dropped(client, employer_token, worker):
    """기기 시계가 뒤로 가 음수 시간이 와도 422로 버리지 않고 0으로 저장한다(대기열은 422를 지운다)."""
    _, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    r = _log(client, worker["token"], aid, s1, duration_sec=-42.5)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        log = db.scalar(select(PerformanceLog).where(PerformanceLog.assignment_id == aid))
        assert log.duration_sec == 0.0 and log.completed


def test_a11y_prefs_patch_is_strict_about_types(client, employer_token, worker):
    url = f"/api/workers/{worker['id']}"
    for bad in ({"tts_rate": True}, {"tts_rate": "0.9"}, {"autoplay_sound": "off"}, {"autoplay_sound": 0},
                {"praise": 1}):
        r = client.patch(url, json={"a11y_prefs": bad}, headers=auth(employer_token))
        assert r.status_code == 422, (bad, r.text)
    ok = client.patch(url, json={"a11y_prefs": {"tts_rate": 1, "autoplay_sound": False}},
                      headers=auth(employer_token))
    assert ok.status_code == 200 and ok.json()["a11y_prefs"]["tts_rate"] == 1.0
    assert ok.json()["a11y_prefs"]["autoplay_sound"] is False


def test_empty_help_list_writes_no_audit_rows(client, employer_token):
    with SessionLocal() as db:
        before = len(db.scalars(select(AccessAuditLog).where(AccessAuditLog.action == "help.list")).all())
    for _ in range(3):
        assert client.get("/api/employer/help", headers=auth(employer_token)).json() == []
    with SessionLocal() as db:
        after = len(db.scalars(select(AccessAuditLog).where(AccessAuditLog.action == "help.list")).all())
    assert after == before


def _login(client, code, ip, device_token=None, workplace="DEMO01"):
    body = {"workplace_code": workplace, "access_code": code}
    if device_token is not None:
        body["device_token"] = device_token
    return client.post("/api/auth/worker-login", json=body, headers={"X-Forwarded-For": ip})


def test_trusted_device_logs_in_after_workplace_day_lock(client, monkeypatch):
    """사업장 하루 한도에 닿아도(일부러든 잘못 누른 것이 쌓였든) 전에 들어왔던 기기의 근로자는 맞는 번호로 들어간다."""
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    first = _login(client, "1234", "10.5.0.1")
    assert first.status_code == 200
    device = first.json()["device_token"]
    assert device and device != first.json()["token"]
    for i in range(100):
        r = _login(client, f"6{i:03d}", f"10.6.{i // 200}.{i % 200}", workplace="demo-01")
        assert r.status_code == 401, i
        ratelimit.worker_wp_throttle.clear()  # 10분 창이 지났다고 친다
        ratelimit.worker_throttle.clear()
    # 믿지 않는 기기는 막힌다(대입 한도 그대로).
    blocked = _login(client, "1234", "9.9.9.9")
    assert blocked.status_code == 429 and int(blocked.headers["Retry-After"]) > 600
    # 전에 들어왔던 기기는 들어간다(같은 와이파이 IP여도).
    ok = _login(client, "1234", "10.6.0.1", device)
    assert ok.status_code == 200 and ok.json()["display_name"] == "김근로"


def test_trusted_device_failures_are_bounded_per_worker(client, monkeypatch):
    """믿는 기기라도 대입 한도가 있다: 근로자 몫 10분 30번. 다시 로그인해 새 표시를 받아도 같은 몫이다."""
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    device = _login(client, "1234", "10.7.0.1").json()["device_token"]
    for i in range(30):
        assert _login(client, f"5{i:03d}", f"10.7.1.{i}", device).status_code == 401
    assert _login(client, "1234", "10.7.2.1", device).status_code == 429
    # 틀린 번호는 사업장 공용 키에도 셌다(3차 검증) — 그래도 공용 10분 한도(60번) 안이라 다른 기기는 들어간다.
    assert ratelimit.worker_wp_throttle.retry_after("wp:DEMO01") == 0
    assert len(ratelimit.worker_wp_throttle._failures["wp:DEMO01"]) == 30
    assert _login(client, "1234", "10.7.3.1").status_code == 200


def test_trusted_device_wrong_codes_use_shared_budget_and_cannot_chain(client, employer_token, monkeypatch):
    """3차 검증: 믿는 기기는 주인 근로자에게만 믿음을 준다. 틀린 번호는 사업장 하루 한도에도 세고, 동료 번호로
    들어가려면 공용 잠금을 지나야 한다 — 잠겼으면 맞는 동료 번호도 틀린 번호와 같은 401이다."""
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    b = client.post("/api/workers", json={"display_name": "동료B", "access_code": "8642"},
                    headers=auth(employer_token)).json()
    dev_a = _login(client, "1234", "10.11.0.1").json()["device_token"]
    for i in range(99):
        assert _login(client, f"7{i:03d}", "10.11.0.2", dev_a).status_code == 401, i
        ratelimit.worker_throttle.clear()  # 10분 창이 지났다고 친다(하루 창은 남는다)
        ratelimit.worker_wp_throttle.clear()
    # A 기기의 틀린 번호도 사업장 하루 키에 쌓였다.
    assert len(ratelimit.worker_wp_day_throttle._failures["wp:DEMO01"]) == 99
    _login(client, "7999", "10.11.9.9")  # 믿지 않는 기기 한 번 더 → 사업장 하루 한도(100)
    assert ratelimit.worker_wp_day_throttle.retry_after("wp:DEMO01") > 0
    # 사업장이 잠긴 뒤 A 기기로 맞는 동료 번호를 넣어도 틀린 번호와 같은 401(맞았다는 신호가 없다), 새 표시도 없다.
    ratelimit.worker_day_throttle.clear()  # A 몫·IP 하루 키는 비워 둔다 — 공용 사업장 잠금만 본다
    r = _login(client, "8642", "10.11.0.3", dev_a)
    assert r.status_code == 401 and "device_token" not in r.json()
    # 주인 A는 사업장이 잠겨도 들어간다.
    assert _login(client, "1234", "10.11.0.4", dev_a).status_code == 200
    delete_worker(client, b['id'], auth(employer_token))


def test_trusted_device_other_worker_success_goes_through_shared_checks(client, employer_token, monkeypatch):
    """공용 잠금이 없을 때 A 기기로 동료 B가 들어가면 B 몫의 표시를 받는다(믿지 않는 기기와 같은 결과)."""
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    b = client.post("/api/workers", json={"display_name": "동료B", "access_code": "8642"},
                    headers=auth(employer_token)).json()
    dev_a = _login(client, "1234", "10.12.0.1").json()["device_token"]
    r = _login(client, "8642", "10.12.0.2", dev_a)
    assert r.status_code == 200 and r.json()["display_name"] == "동료B"
    # IP 키가 잠겨 있으면 A 기기로도 B는 못 들어간다(401).
    for i in range(30):
        _login(client, f"3{i:03d}", "10.12.0.9")
    assert _login(client, "8642", "10.12.0.9", dev_a).status_code == 401
    assert _login(client, "1234", "10.12.0.9", dev_a).status_code == 200  # 주인은 들어간다
    delete_worker(client, b['id'], auth(employer_token))


def test_device_token_of_deleted_or_reissued_worker_is_not_trusted(client, employer_token, monkeypatch):
    """3차 검증: 지운 근로자·코드를 다시 발급한 근로자의 기기 표시는 사업장 잠금을 건너뛰지 못한다."""
    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    b = client.post("/api/workers", json={"display_name": "지울", "access_code": "8642"},
                    headers=auth(employer_token)).json()
    c = client.post("/api/workers", json={"display_name": "재발급", "access_code": "8643"},
                    headers=auth(employer_token)).json()
    dev_b = _login(client, "8642", "10.13.0.1").json()["device_token"]
    dev_c = _login(client, "8643", "10.13.0.2").json()["device_token"]
    assert delete_worker(client, b['id'], auth(employer_token)).status_code in (200, 204)
    r = client.post(f"/api/workers/{c['id']}/access-code", headers=auth(employer_token))
    assert r.status_code == 200, r.text
    new_c = r.json()["access_code"]
    monkeypatch.setattr(ratelimit.worker_wp_throttle, "max_failures", 1)
    assert _login(client, "0000", "10.13.0.3").status_code == 401
    assert _login(client, "1234", "10.13.0.4").status_code == 429  # 사업장 공용 잠김
    assert _login(client, "1234", "10.13.0.5", dev_b).status_code == 429
    assert _login(client, new_c, "10.13.0.6", dev_c).status_code == 429
    delete_worker(client, c['id'], auth(employer_token))


def test_device_token_for_other_workplace_or_forged_is_ignored(client, other_employer, monkeypatch):
    from auth import make_device_token

    monkeypatch.setenv("TRUST_FORWARDED_FOR", "1")
    foreign = make_device_token(other_employer["id"], "someone")
    monkeypatch.setattr(ratelimit.worker_wp_throttle, "max_failures", 2)
    for i, tok in enumerate((foreign, "garbage.token")):
        assert _login(client, f"4{i:03d}", f"10.8.0.{i}", tok).status_code == 401
    # 두 번 모두 사업장 공용 키로 셌다.
    assert _login(client, "1234", "10.8.0.9").status_code == 429
    # 기기 표시는 로그인 토큰으로 쓸 수 없다.
    device = make_device_token("emp-demo", "x")
    assert client.get("/api/worker/me", headers=auth(device)).status_code == 401


def test_four_digit_code_cannot_be_prefix_of_longer_code(client, employer_token, monkeypatch):
    """/worker 키패드는 4번째 숫자에서 바로 보낸다: '1234'(데모)가 있으면 '123456'을 만들 수 없고, 그 반대도."""
    r = client.post("/api/workers", json={"display_name": "앞자리", "access_code": "123456"},
                    headers=auth(employer_token))
    assert r.status_code == 409 and "앞 4자리" in r.json()["detail"]
    long = client.post("/api/workers", json={"display_name": "긴코드", "access_code": "987650"},
                       headers=auth(employer_token))
    assert long.status_code == 201
    try:
        short = client.post("/api/workers", json={"display_name": "짧은코드", "access_code": "9876"},
                            headers=auth(employer_token))
        assert short.status_code == 409
        # 자동 코드도 긴 코드의 앞 4자리를 피한다.
        seq = iter("98761112")
        monkeypatch.setattr(main.secrets, "choice", lambda _: next(seq))
        with SessionLocal() as db:
            assert main._new_access_code(db, "emp-demo") == "1112"
        # 다시 뽑을 때 자기 자신의 옛 코드는 막지 않는다.
        seq2 = iter("9876")
        monkeypatch.setattr(main.secrets, "choice", lambda _: next(seq2))
        with SessionLocal() as db:
            assert main._new_access_code(db, "emp-demo", exclude_worker_id=long.json()["id"]) == "9876"
    finally:
        delete_worker(client, long.json()['id'], auth(employer_token))


def test_late_completion_does_not_close_help_called_after_it(client, employer_token, worker):
    """3차 검증: 대기열에 남은 옛 1단계 완료 기록이 늦게 닿아도, 그 뒤에 1단계에서 다시 부른 도움은 열려 있다."""
    _, aid, (s1, _s2) = _assigned(client, employer_token, worker["id"])
    old = (datetime.now(timezone.utc) - timedelta(minutes=3)).isoformat()
    h = _help(client, worker["token"], aid, s1, client_request_id="p2").json()
    r = _log(client, worker["token"], aid, s1, client_completed_at=old, client_event_id="e-old")
    assert r.status_code == 201, r.text
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "open"
    # 지금 누른 [다 했어요](기기 시각 = 지금)는 그 요청을 닫는다.
    assert _log(client, worker["token"], aid, s1, client_event_id="e-new").status_code == 201
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "resolved" and got["resolution"] == "step_done"


def test_completion_closes_help_even_when_device_clock_is_behind(client, employer_token, worker):
    """4차 검증: 기기 시계가 서버보다 20초 늦어도, 도움을 부른 뒤 누른 [다 했어요]는 그 도움을 닫는다."""
    _, aid, (s1, _s2) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s1, client_request_id="lag").json()
    device_now = (datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat()
    r = _log(client, worker["token"], aid, s1, client_completed_at=device_now, client_sent_at=device_now,
             client_event_id="e-lag")
    assert r.status_code == 201, r.text
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "resolved" and got["resolution"] == "step_done"
    active = client.get("/api/employer/help", headers=auth(employer_token)).json()
    assert h["id"] not in {x["id"] for x in (active if isinstance(active, list) else active.get("items", []))}


def test_completion_arriving_90s_after_later_help_does_not_close_it(client, employer_token, worker):
    """4차 검증: 끝낸 뒤에 부른 같은 단계 도움은, 옛 완료 기록이 그 도움보다 90초 늦게 닿아도 닫지 않는다."""
    _, aid, (s1, _s2) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s1, client_request_id="late90").json()
    with SessionLocal() as db:  # 도움은 90초 전에 서버에 닿았다
        row = db.get(HelpRequest, h["id"])
        row.created_at = row.created_at - timedelta(seconds=90)
        db.commit()
    now = datetime.now(timezone.utc)
    # 기기에서 100초 전에 끝냈고(도움보다 10초 앞), 지금에서야 보냈다.
    r = _log(client, worker["token"], aid, s1, client_completed_at=(now - timedelta(seconds=100)).isoformat(),
             client_sent_at=now.isoformat(), client_event_id="e-old90")
    assert r.status_code == 201, r.text
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "open"
    # 도움보다 뒤(30초 전)에 끝낸 기록은 늦게 닿아도 닫는다.
    r = _log(client, worker["token"], aid, s1, client_completed_at=(now - timedelta(seconds=30)).isoformat(),
             client_sent_at=now.isoformat(), client_event_id="e-after")
    assert r.status_code == 201, r.text
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "resolved" and got["resolution"] == "step_done"


def test_absurd_client_times_do_not_500(client, employer_token, worker):
    """4차 검증 2회: 기기 시각이 터무니없으면(0001년·9999년, 차이 수천 년) 날짜 계산이 넘쳐 500이 났고 대기열이 그 기록을
    5xx로 보고 끝없이 다시 보내 뒤 기록까지 막았다. 이제 201로 받고(완료는 남는다), 뒤에 부른 도움을 닫지도 않는다."""
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s1, client_request_id="absurd").json()
    now = datetime.now(timezone.utc)
    # 끝낸 시각과 보낸 시각이 100년 떨어져도(둘 다 받는 범위) 넘치지 않는다. 아주 옛 완료라 뒤에 부른 도움은 그대로 열림.
    r = _log(client, worker["token"], aid, s1, client_completed_at=(now - timedelta(days=36500)).isoformat(),
             client_sent_at=now.isoformat(), client_event_id="e-old100y")
    assert r.status_code == 201, r.text
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["state"] == "open"
    # 시간대 바꾸기·빼기가 넘치던 값(검증 재현값). 어려움 신호(완료 아님)와 완료 둘 다 500이 아니다.
    for i, (done, sent) in enumerate([
        ("2026-11-09T00:00:00Z", "9999-12-31T23:00:00-09:00"),
        ("0001-01-01T00:00:00+09:00", "2026-11-09T00:00:00Z"),
    ]):
        r = _log(client, worker["token"], aid, s2, completed=False, client_completed_at=done,
                 client_sent_at=sent, client_event_id=f"e-absurd-{i}")
        assert r.status_code == 201, r.text
    r = _log(client, worker["token"], aid, s2, client_completed_at="0001-01-02T00:00:00Z",
             client_sent_at="9999-12-30T00:00:00Z", client_event_id="e-absurd-done")
    assert r.status_code == 201, r.text
    assert r.json()["assignment_status"] == "done"


def test_cancel_by_client_precreate_is_throttled_and_refused_for_closed_jobs(client, employer_token, worker):
    """3차 검증: 아직 없는 누름 키로 '취소됨' 행을 미리 만드는 길도 도움 요청 몫(60초 10건)으로 센다."""
    _, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    url = "/api/worker/help/cancel-by-client"
    codes = [client.post(url, headers=auth(worker["token"]),
                         json={"assignment_id": aid, "client_request_id": f"x{i}"}).status_code
             for i in range(15)]
    assert codes[:10] == [200] * 10 and set(codes[10:]) == {429}
    with SessionLocal() as db:
        n = db.scalar(select(func.count()).select_from(HelpRequest).where(HelpRequest.assignment_id == aid))
    assert n == 10
    # 다 끝낸 일에는 미리 만들지 않는다(409).
    ratelimit.help_throttle.clear()
    _log(client, worker["token"], aid, s1)
    assert _log(client, worker["token"], aid, s2).json()["assignment_status"] == "done"
    r = client.post(url, headers=auth(worker["token"]), json={"assignment_id": aid, "client_request_id": "late"})
    assert r.status_code == 409
