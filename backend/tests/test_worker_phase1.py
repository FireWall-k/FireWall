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
from sqlalchemy import select  # noqa: E402

import main  # noqa: E402
import ratelimit  # noqa: E402
import retention  # noqa: E402
from auth import hash_password, make_token  # noqa: E402
from conftest import TEST_AAC_IMAGE, auth, give_pictures, publish  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import (  # noqa: E402
    AccessAuditLog,
    Assignment,
    Employer,
    HelpRequest,
    PerformanceLog,
    Step,
    Task,
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
    client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


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
    """그림을 붙여 보낸 2단계 직무를 근로자에게 배정한다. (task, assignment_id, step_ids)."""
    task = _task(client, employer_token)
    assert publish(client, employer_token, task["id"]).status_code == 200
    r = client.post(f"/api/tasks/{task['id']}/assignments", json={"worker_id": worker_id},
                    headers=auth(employer_token))
    assert r.status_code == 200, r.text
    return task, r.json()[0]["id"], [s["id"] for s in task["steps"]]


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


def test_done_is_judged_against_current_steps(client, employer_token, worker):
    """진행 중에 단계가 지워져도 지금 단계를 모두 끝냈으면 done이다(옛 단계 기록에 기대지 않는다)."""
    task, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    added = client.post(f"/api/tasks/{task['id']}/steps", json={"sentence": "정리하세요."},
                        headers=auth(employer_token)).json()
    s3 = added["steps"][-1]["id"]
    _log(client, worker["token"], aid, s1)
    _log(client, worker["token"], aid, s2)
    assert _assignment_status(aid) == "assigned"  # 새로 더한 3단계가 남았다
    client.delete(f"/api/tasks/{task['id']}/steps/{s3}", headers=auth(employer_token))
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
    _log(client, worker["token"], aid, s1)
    _log(client, worker["token"], aid, s2)
    r = _help(client, worker["token"], aid)
    assert r.status_code == 201 and r.json()["step_id"] is None and r.json()["step_order"] is None


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
    assert r.json()["detail"] == ("그림이 없는 단계가 있어요(1, 2단계). "
                                  "그림을 고르거나 사진을 올린 뒤 보내 주세요.")
    assert client.get(f"/api/tasks/{task['id']}", headers=auth(employer_token)).json()["status"] == "draft"

    client.patch(f"/api/tasks/{task['id']}/steps/{task['steps'][0]['id']}", headers=auth(employer_token),
                 json={"symbol_url": TEST_AAC_IMAGE, "symbol_source": "LOCAL_AAC"})
    r = client.post(f"/api/tasks/{task['id']}/publish", headers=auth(employer_token))
    assert r.status_code == 422 and "(2단계)" in r.json()["detail"]
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
    assert r.status_code == 422 and "(2단계)" in r.json()["detail"]


def test_publish_blocked_when_task_has_no_steps(client, employer_token):
    with SessionLocal() as db:
        t = Task(employer_id="emp-demo", title="빈 직무", raw_input="", status="draft")
        db.add(t)
        db.commit()
        tid = t.id
    r = client.post(f"/api/tasks/{tid}/publish", headers=auth(employer_token))
    assert r.status_code == 422 and r.json()["detail"] == "단계가 없는 직무는 보낼 수 없어요."
    client.delete(f"/api/tasks/{tid}", headers=auth(employer_token))


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
            client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


def test_auto_code_retries_on_collision(client, employer_token, monkeypatch):
    """처음 뽑은 코드가 사업장 안에서 이미 쓰이면(데모 근로자 1234) 다시 뽑는다."""
    digits = iter("1234" + "5678")
    monkeypatch.setattr(main.secrets, "choice", lambda seq: next(digits))
    r = client.post("/api/workers", json={"display_name": "충돌"}, headers=auth(employer_token))
    assert r.status_code == 201 and r.json()["access_code"] == "5678"
    client.delete(f"/api/workers/{r.json()['id']}", headers=auth(employer_token))


def test_legacy_six_digit_code_still_logs_in(client, employer_token):
    r = client.post("/api/workers", json={"display_name": "예전코드", "access_code": "135790"},
                    headers=auth(employer_token))
    assert r.status_code == 201
    try:
        login = client.post("/api/auth/worker-login", json={"workplace_code": "DEMO01", "access_code": "135790"})
        assert login.status_code == 200
    finally:
        client.delete(f"/api/workers/{r.json()['id']}", headers=auth(employer_token))


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


def test_delete_worker_removes_help_requests(client, employer_token):
    w = client.post("/api/workers", json={"display_name": "지울근로자"}, headers=auth(employer_token)).json()
    tok = client.post("/api/auth/worker-login",
                      json={"workplace_code": "DEMO01", "access_code": w["access_code"]}).json()["token"]
    _, aid, (s1, _) = _assigned(client, employer_token, w["id"])
    _help(client, tok, aid, s1)
    assert client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token)).status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(HelpRequest).where(HelpRequest.worker_id == w["id"])).all() == []
        assert db.get(Assignment, aid) is None


def test_delete_task_removes_help_requests(client, employer_token, worker):
    task, aid, (s1, _) = _assigned(client, employer_token, worker["id"])
    _help(client, worker["token"], aid, s1)
    assert client.delete(f"/api/tasks/{task['id']}", headers=auth(employer_token)).status_code == 200
    with SessionLocal() as db:
        assert db.scalars(select(HelpRequest).where(HelpRequest.assignment_id == aid)).all() == []


def test_delete_step_keeps_help_but_unlinks_step(client, employer_token, worker):
    task, aid, (s1, s2) = _assigned(client, employer_token, worker["id"])
    h = _help(client, worker["token"], aid, s2).json()
    r = client.delete(f"/api/tasks/{task['id']}/steps/{s2}", headers=auth(employer_token))
    assert r.status_code == 200
    got = client.get(f"/api/worker/help/{h['id']}", headers=auth(worker["token"])).json()
    assert got["step_id"] is None and got["step_order"] is None and got["state"] == "open"
    row = next(x for x in client.get("/api/employer/help", headers=auth(employer_token)).json()
               if x["id"] == h["id"])
    assert row["step_id"] is None and row["step_sentence"] is None and row["step_symbol_url"] is None


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
