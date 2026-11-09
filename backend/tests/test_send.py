"""2a-0 서버 보내기 검사·보내기·받는 사람 시험 (scratchpad/p2/contract.md §1.4).

지키는 것:
- 확인 안 한 자동 그림(auto_high·choose)·그림 없는 단계·단계 없음은 서버가 막는다(send·publish·옛 assignments 같은 검사).
- 점검표는 code와 숫자만 보낸다(label 없음).
- 같은 내용을 다시 보내면 버전을 늘리지 않고, 고쳤으면 새 버전을 만든다.
- 배정 규칙 5가지(created·repinned·unchanged·kept·kept_in_progress·다 함→created), first_seen_at으로 '받음'을 판정.
- 날짜: 내일로 보낸 일은 오늘 화면에 없고 내일 뜬다. 지난 날짜·60일 넘게 뒤면 422. 어제 못 끝낸 일을 다시 보내면 오늘 뜬다.
- 감사 task.assign은 근로자마다 남는다.
"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

import clock  # noqa: E402
from auth import hash_password, make_token  # noqa: E402
from conftest import TEST_AAC_IMAGE, auth, give_pictures, delete_task  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import AccessAuditLog, Assignment, Employer, Step, Task, TaskVersion, Worker  # noqa: E402


@pytest.fixture()
def workers(client, employer_token):
    """데모 사업장의 새 근로자 둘(로그인 토큰 포함). 끝나면 지운다."""
    made = []
    for name in ("보내기가", "보내기나"):
        r = client.post("/api/workers", json={"display_name": name}, headers=auth(employer_token))
        assert r.status_code == 201, r.text
        w = r.json()
        login = client.post("/api/auth/worker-login",
                            json={"workplace_code": "DEMO01", "access_code": w["access_code"]})
        w["token"] = login.json()["token"]
        made.append(w)
    yield made
    for w in made:
        client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


def _task(client, token, pictures=True):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"}, headers=auth(token))
    assert r.status_code == 201, r.text
    if pictures:
        give_pictures(client, token, r.json()["id"])
    return client.get(f"/api/tasks/{r.json()['id']}", headers=auth(token)).json()


def _send(client, token, task_id, worker_ids, day="today"):
    return client.post(f"/api/tasks/{task_id}/send", headers=auth(token),
                       json={"worker_ids": worker_ids, "day": day})


def _outcome(r):
    assert r.status_code == 200, r.text
    return r.json()["results"][0]["outcome"]


def _cards(client, wtoken):
    r = client.get("/api/worker/me/today?include_done=true", headers=auth(wtoken))
    assert r.status_code == 200, r.text
    return r.json()


def _task_cards(client, wtoken, task_id):
    return [c for c in _cards(client, wtoken) if c["task_id"] == task_id]


def _log(client, wtoken, aid, sid):
    return client.post("/api/performance-logs", headers=auth(wtoken), json={
        "assignment_id": aid, "step_id": sid, "duration_sec": 3.0, "replay_count": 0, "stuck": False})


def _edit(client, token, task, text):
    sid = client.get(f"/api/tasks/{task['id']}", headers=auth(token)).json()["steps"][0]["id"]
    r = client.patch(f"/api/tasks/{task['id']}/steps/{sid}", headers=auth(token), json={"sentence": text})
    assert r.status_code == 200, r.text


def _set_step(step_id, **values):
    with SessionLocal() as db:
        step = db.get(Step, step_id)
        for k, v in values.items():
            setattr(step, k, v)
        db.commit()


# --- 버전 만들기 ---------------------------------------------------------------------------

def test_resend_same_content_no_new_version(client, employer_token, workers):
    task = _task(client, employer_token)
    a, b = workers
    first = _send(client, employer_token, task["id"], [a["id"]])
    assert first.status_code == 200 and first.json()["version_no"] == 1 and first.json()["version_created"]
    again = _send(client, employer_token, task["id"], [b["id"]])
    assert again.json()["version_no"] == 1 and again.json()["version_created"] is False
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(TaskVersion)
                         .where(TaskVersion.task_id == task["id"])) == 1
    got = client.get(f"/api/tasks/{task['id']}", headers=auth(employer_token)).json()
    assert got["status"] == "published"
    assert got["version"] == {"current_no": 1, "has_unsent_changes": False}
    assert got["recipients_count"] == 2


def test_resend_changed_creates_version(client, employer_token, workers):
    task = _task(client, employer_token)
    a, b = workers
    assert _send(client, employer_token, task["id"], [a["id"]]).json()["version_no"] == 1
    _edit(client, employer_token, task, "상자를 두 손으로 옮기세요.")
    assert client.get(f"/api/tasks/{task['id']}", headers=auth(employer_token)).json()["version"] == {
        "current_no": 1, "has_unsent_changes": True}
    r = _send(client, employer_token, task["id"], [b["id"]])
    assert r.json()["version_no"] == 2 and r.json()["version_created"] is True
    assert client.get(f"/api/tasks/{task['id']}", headers=auth(employer_token)).json()["version"] == {
        "current_no": 2, "has_unsent_changes": False}
    # 받은 사람마다 자기 버전: a는 버전 1 문장, b는 버전 2 문장.
    card_a = _task_cards(client, a["token"], task["id"])[0]
    card_b = _task_cards(client, b["token"], task["id"])[0]
    assert card_a["task_version_no"] == 1 and card_b["task_version_no"] == 2
    assert card_b["steps"][0]["sentence"] == "상자를 두 손으로 옮기세요."
    assert card_a["steps"][0]["sentence"] != card_b["steps"][0]["sentence"]
    # 제목만 바꿔도 다른 내용이다.
    with SessionLocal() as db:
        db.get(Task, task["id"]).title = "새 제목"
        db.commit()
    assert _send(client, employer_token, task["id"], [b["id"]]).json()["version_no"] == 3


# --- 배정 규칙 5가지 -------------------------------------------------------------------------

def test_assign_outcomes(client, employer_token, workers):
    task = _task(client, employer_token)
    w = workers[0]
    tid = task["id"]
    assert _outcome(_send(client, employer_token, tid, [w["id"]])) == "created"
    assert _outcome(_send(client, employer_token, tid, [w["id"]])) == "unchanged"
    _edit(client, employer_token, task, "고친 문장 하나예요.")
    r = _send(client, employer_token, tid, [w["id"]])
    assert _outcome(r) == "repinned" and r.json()["version_no"] == 2
    with SessionLocal() as db:
        a = db.scalar(select(Assignment).where(Assignment.task_id == tid, Assignment.worker_id == w["id"]))
        assert a.first_seen_at is None and a.pinned_at is not None
    # 근로자가 받았다(today가 first_seen_at을 씀) → 다시 보내도 옛 버전 그대로
    card = _task_cards(client, w["token"], tid)[0]
    assert card["task_version_no"] == 2
    _edit(client, employer_token, task, "또 고친 문장이에요.")
    assert _outcome(_send(client, employer_token, tid, [w["id"]])) == "kept"
    assert _task_cards(client, w["token"], tid)[0]["task_version_no"] == 2
    # 하는 중
    assert _log(client, w["token"], card["assignment_id"], card["steps"][0]["id"]).status_code == 201
    _edit(client, employer_token, task, "세 번째 고친 문장이에요.")
    assert _outcome(_send(client, employer_token, tid, [w["id"]])) == "kept_in_progress"
    # 다 함 → 한 번 더 하라는 새 배정(지금 버전)
    done = _log(client, w["token"], card["assignment_id"], card["steps"][1]["id"])
    assert done.json()["assignment_status"] == "done"
    r = _send(client, employer_token, tid, [w["id"]])
    assert _outcome(r) == "created"
    cards = _task_cards(client, w["token"], tid)
    assert len(cards) == 2
    assert cards[0]["status"] == "done" and cards[1]["status"] == "new"
    # 마지막 고침(버전 4)을 kept_in_progress 때 이미 버전으로 만들었다 — 같은 내용이라 새 버전 없이 4.
    assert cards[1]["task_version_no"] == r.json()["version_no"] == 4 and r.json()["version_created"] is False
    assert cards[1]["steps"][0]["sentence"] == "세 번째 고친 문장이에요."
    assert cards[1]["is_next"] is True


def test_viewing_step1_resend_kept(client, employer_token, workers):
    """1단계를 보는 중(로그 0건, first_seen_at 있음)에 다시 보내기 → kept, today 단계 id 그대로, 옛 단계 완료 기록 성공."""
    task = _task(client, employer_token)
    w = workers[0]
    assert _outcome(_send(client, employer_token, task["id"], [w["id"]])) == "created"
    card = _task_cards(client, w["token"], task["id"])[0]
    ids = [s["id"] for s in card["steps"]]
    _edit(client, employer_token, task, "보는 중에 고친 문장이에요.")
    assert _outcome(_send(client, employer_token, task["id"], [w["id"]])) == "kept"
    again = _task_cards(client, w["token"], task["id"])
    assert len(again) == 1 and [s["id"] for s in again[0]["steps"]] == ids
    r = _log(client, w["token"], card["assignment_id"], ids[0])
    assert r.status_code == 201 and r.json()["applied"] is True


def test_help_only_counts_as_received(client, employer_token, workers):
    """받기 전 판정은 도움 0건도 본다: 도움을 불렀으면 화면에 떴던 것이라 kept."""
    task = _task(client, employer_token)
    w = workers[0]
    _send(client, employer_token, task["id"], [w["id"]])
    with SessionLocal() as db:
        a = db.scalar(select(Assignment).where(Assignment.task_id == task["id"]))
        aid = a.id
    # 기기가 today를 부르기 전에 도움 요청이 먼저 닿은 경우(오프라인 대기열)
    assert client.post("/api/worker/help", headers=auth(w["token"]),
                       json={"assignment_id": aid}).status_code == 201
    with SessionLocal() as db:
        db.get(Assignment, aid).first_seen_at = None
        db.commit()
    _edit(client, employer_token, task, "도움 뒤 고친 문장이에요.")
    assert _outcome(_send(client, employer_token, task["id"], [w["id"]])) == "kept"


def test_yesterday_unfinished_resend_shows_today(client, employer_token, workers):
    """재사용 결함(main.py 1824행): 어제 못 끝낸 일을 다시 보내면 어제 배정을 재사용해 오늘 화면에 안 떴다."""
    task = _task(client, employer_token)
    w = workers[0]
    _send(client, employer_token, task["id"], [w["id"]])
    old = _task_cards(client, w["token"], task["id"])[0]
    _log(client, w["token"], old["assignment_id"], old["steps"][0]["id"])
    with SessionLocal() as db:
        a = db.get(Assignment, old["assignment_id"])
        a.scheduled_day = a.scheduled_day - timedelta(days=1)
        a.assigned_date = a.assigned_date - timedelta(days=1)
        db.commit()
    assert _task_cards(client, w["token"], task["id"]) == []
    assert _outcome(_send(client, employer_token, task["id"], [w["id"]])) == "created"
    cards = _task_cards(client, w["token"], task["id"])
    assert len(cards) == 1 and cards[0]["assignment_id"] != old["assignment_id"] and cards[0]["status"] == "new"
    with SessionLocal() as db:
        assert db.get(Assignment, old["assignment_id"]).status == "assigned"  # 어제 배정은 그대로 둔다


# --- 날짜 ---------------------------------------------------------------------------------

def test_tomorrow_not_in_today(client, employer_token, workers, monkeypatch):
    task = _task(client, employer_token)
    w = workers[0]
    r = _send(client, employer_token, task["id"], [w["id"]], day="tomorrow")
    assert r.status_code == 200 and r.json()["day"] == (clock.local_today() + timedelta(days=1)).isoformat()
    assert _task_cards(client, w["token"], task["id"]) == []
    hist = client.get("/api/worker/me/history", headers=auth(w["token"])).json()
    assert all(h["task_id"] != task["id"] for h in hist)
    real = clock.utcnow
    monkeypatch.setattr(clock, "utcnow", lambda: real() + timedelta(days=1))
    cards = _task_cards(client, w["token"], task["id"])
    assert len(cards) == 1 and cards[0]["status"] == "new"
    # 그 날의 사업주 달력에도 내일 날짜로 보인다.
    tomorrow = (clock.local_today()).isoformat()
    ids = [t["id"] for t in client.get(f"/api/workers/{w['id']}/tasks?date={tomorrow}",
                                       headers=auth(employer_token)).json()]
    assert task["id"] in ids


def test_past_day_422(client, employer_token, workers):
    task = _task(client, employer_token)
    yesterday = (clock.local_today() - timedelta(days=1)).isoformat()
    r = _send(client, employer_token, task["id"], [workers[0]["id"]], day=yesterday)
    assert r.status_code == 422
    assert r.json()["detail"] == "지난 날짜에는 보낼 수 없어요. 오늘이나 그 뒤 날짜를 골라 주세요."
    for bad in ("2026-13-40", "next week", ""):
        r = _send(client, employer_token, task["id"], [workers[0]["id"]], day=bad)
        assert r.status_code == 422 if bad else r.status_code == 200, (bad, r.text)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Assignment).where(
            Assignment.task_id == task["id"], Assignment.scheduled_day < clock.local_today())) == 0


def test_day_over_60_422(client, employer_token, workers):
    task = _task(client, employer_token)
    far = (clock.local_today() + timedelta(days=61)).isoformat()
    r = _send(client, employer_token, task["id"], [workers[0]["id"]], day=far)
    assert r.status_code == 422 and r.json()["detail"] == "60일 안의 날짜를 골라 주세요."
    ok = (clock.local_today() + timedelta(days=60)).isoformat()
    r = _send(client, employer_token, task["id"], [workers[0]["id"]], day=ok)
    assert r.status_code == 200 and r.json()["day"] == ok


# --- 서버 보내기 검사 -------------------------------------------------------------------------

def _check(client, token, tid):
    r = client.get(f"/api/tasks/{tid}/send-check", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _row(check, code):
    return next((b for b in check["blocking"] if b["code"] == code), None)


def test_send_check_codes(client, employer_token, workers):
    task = _task(client, employer_token, pictures=False)
    tid = task["id"]
    s1, s2 = (s["id"] for s in task["steps"])
    w = workers[0]
    emp = auth(employer_token)

    # 1) no_picture
    check = _check(client, employer_token, tid)
    assert check["ok"] is False
    assert _row(check, "no_picture") == {"code": "no_picture", "done": 0, "total": 2, "step_ids": [s1, s2]}
    r = _send(client, employer_token, tid, [w["id"]])
    assert r.status_code == 422
    body = {"detail": "1단계와 2단계에 그림이 없어요. 그림을 고르거나 사진을 올려 주세요.",
            "code": "send_blocked", "step_ids": [s1, s2]}
    assert r.json() == body
    assert client.post(f"/api/tasks/{tid}/publish", headers=emp).json() == body

    # 2) unconfirmed_auto: 1단계 auto_high, 2단계 choose
    _set_step(s1, symbol_url=TEST_AAC_IMAGE, needs_fallback=False, picture_confirmed=False)
    _set_step(s2, symbol_url=TEST_AAC_IMAGE, needs_fallback=True, picture_confirmed=False)
    states = [s["picture_state"] for s in client.get(f"/api/tasks/{tid}", headers=emp).json()["steps"]]
    assert states == ["auto_high", "choose"]
    check = _check(client, employer_token, tid)
    assert check["ok"] is False
    assert _row(check, "no_picture") == {"code": "no_picture", "done": 2, "total": 2, "step_ids": []}
    assert _row(check, "unconfirmed_auto") == {"code": "unconfirmed_auto", "done": 0, "total": 2,
                                               "step_ids": [s1, s2]}
    body = {"detail": "1단계와 2단계의 그림을 아직 확인하지 않았어요. 확인한 뒤 다시 보내 주세요.",
            "code": "send_blocked", "step_ids": [s1, s2]}
    assert _send(client, employer_token, tid, [w["id"]]).json() == body
    assert client.post(f"/api/tasks/{tid}/publish", headers=emp).json() == body
    assert client.get(f"/api/tasks/{tid}", headers=emp).json()["status"] == "draft"

    # 하나만 확인 → 남은 하나만 막힘
    assert client.post(f"/api/tasks/{tid}/steps/{s1}/picture/confirm", headers=emp).status_code == 200
    r = _send(client, employer_token, tid, [w["id"]])
    assert r.status_code == 422 and r.json()["step_ids"] == [s2]
    assert r.json()["detail"].startswith("2단계의 그림을 아직 확인하지 않았어요.")

    # 3) 모두 확인 → 200(publish도)
    assert client.post(f"/api/tasks/{tid}/steps/{s2}/picture/confirm", headers=emp).status_code == 200
    check = _check(client, employer_token, tid)
    assert check["ok"] is True and _row(check, "unconfirmed_auto")["done"] == 2
    assert _row(check, "unreviewed_split") == {"code": "unreviewed_split", "done": 0, "total": 0, "step_ids": []}
    assert client.post(f"/api/tasks/{tid}/publish", headers=emp).status_code == 200
    assert _send(client, employer_token, tid, [w["id"]]).status_code == 200
    # 보낸 뒤 자동 그림 단계를 더하면 옛 assignments도 같은 검사로 막는다.
    _set_step(s2, picture_confirmed=False, needs_fallback=False)
    r = client.post(f"/api/tasks/{tid}/assignments", headers=emp, json={"worker_id": w["id"]})
    assert r.status_code == 422 and r.json()["code"] == "send_blocked" and r.json()["step_ids"] == [s2]

    # 4) no_steps
    with SessionLocal() as db:
        t = Task(employer_id="emp-demo", title="빈 직무", raw_input="", status="draft")
        db.add(t)
        db.commit()
        empty = t.id
    check = _check(client, employer_token, empty)
    assert check["ok"] is False and _row(check, "no_steps") == {"code": "no_steps", "done": 0, "total": 1,
                                                                "step_ids": []}
    r = _send(client, employer_token, empty, [w["id"]])
    assert r.status_code == 422 and r.json() == {"detail": "단계가 하나도 없어요. 단계를 넣어 주세요.",
                                                 "code": "no_steps", "step_ids": []}
    assert client.post(f"/api/tasks/{empty}/publish", headers=emp).json()["code"] == "no_steps"
    delete_task(client, empty, emp)


def test_send_check_has_no_label(client, employer_token):
    task = _task(client, employer_token, pictures=False)
    check = _check(client, employer_token, task["id"])
    assert set(check) == {"ok", "blocking", "warnings"}
    for b in check["blocking"]:
        assert set(b) == {"code", "done", "total", "step_ids"}
        assert isinstance(b["done"], int) and isinstance(b["total"], int)
    assert [w["code"] for w in check["warnings"]] == ["too_long", "command_tone", "auto_caution"]
    for w in check["warnings"]:
        assert set(w) == {"code", "count", "step_ids"}
    text = str(check)
    assert "label" not in text and "message" not in text
    assert not any("가" <= ch <= "힣" for ch in text)  # 한국어 문구 없음(화면 copy.ts가 만든다)


def test_send_check_and_send_reject_other_employer(client, employer_token, workers):
    eid = "emp-send-other"
    with SessionLocal() as db:
        if db.get(Employer, eid) is None:
            db.add(Employer(id=eid, name="다른", org_name="다른", login_id=eid, password_hash=hash_password("pw")))
            db.commit()
    other = make_token(eid, "employer")
    task = _task(client, employer_token)
    assert client.get(f"/api/tasks/{task['id']}/send-check", headers=auth(other)).status_code == 404
    assert _send(client, other, task["id"], [workers[0]["id"]]).status_code == 404
    assert client.get(f"/api/tasks/{task['id']}/recipients", headers=auth(other)).status_code == 404


def test_send_validates_workers(client, employer_token, workers):
    task = _task(client, employer_token)
    r = _send(client, employer_token, task["id"], [])
    assert r.status_code == 422 and r.json()["detail"] == "받는 사람을 한 명 이상 골라 주세요."
    r = _send(client, employer_token, task["id"], [workers[0]["id"], "no-such-worker"])
    assert r.status_code == 404
    assert r.json()["detail"] == "받는 사람을 찾지 못했어요. 목록을 새로 고친 뒤 다시 골라 주세요."
    with SessionLocal() as db:  # 하나라도 틀리면 아무에게도 보내지 않는다
        assert db.scalar(select(func.count()).select_from(Assignment)
                         .where(Assignment.task_id == task["id"])) == 0
    # 같은 근로자를 두 번 적어도 한 번만
    r = _send(client, employer_token, task["id"], [workers[0]["id"], workers[0]["id"]])
    assert [x["outcome"] for x in r.json()["results"]] == ["created"]


def test_send_records_task_assign_audit_per_worker(client, employer_token, workers):
    task = _task(client, employer_token)
    before = clock.utcnow() - timedelta(seconds=1)
    r = _send(client, employer_token, task["id"], [w["id"] for w in workers])
    assert r.status_code == 200
    assert [x["display_name"] for x in r.json()["results"]] == ["보내기가", "보내기나"]
    ids = [w["id"] for w in workers]
    with SessionLocal() as db:
        rows = db.scalars(select(AccessAuditLog.worker_id).where(AccessAuditLog.action == "task.assign",
                                                                 AccessAuditLog.worker_id.in_(ids),
                                                                 AccessAuditLog.at >= before)).all()
    assert sorted(rows) == sorted(ids)
    # 옛 assignments 경로도 같은 함수라 근로자마다 남긴다.
    r = client.post(f"/api/tasks/{task['id']}/assignments", headers=auth(employer_token),
                    json={"worker_ids": [w["id"] for w in workers]})
    assert r.status_code == 200 and len(r.json()) == 2
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AccessAuditLog).where(
            AccessAuditLog.action == "task.assign", AccessAuditLog.worker_id.in_(ids),
            AccessAuditLog.at >= before)) == 4


def test_recipients_last_batch_and_today_status(client, employer_token, workers):
    task = _task(client, employer_token)
    a, b = workers
    _send(client, employer_token, task["id"], [a["id"]])
    _send(client, employer_token, task["id"], [b["id"]])
    r = client.get(f"/api/tasks/{task['id']}/recipients", headers=auth(employer_token))
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["last_batch_worker_ids"] == [b["id"]]
    assert got["all_ever_worker_ids"] == [a["id"], b["id"]]
    assert got["workplace_last_batch_worker_ids"] == [b["id"]]
    assert got["today_status"][a["id"]] == "not_started" and got["today_status"][b["id"]] == "not_started"
    with SessionLocal() as db:
        demo_ids = db.scalars(select(Worker.id).where(Worker.employer_id == "emp-demo")).all()
    assert set(got["today_status"]) == set(demo_ids)
    card = _task_cards(client, a["token"], task["id"])[0]
    _log(client, a["token"], card["assignment_id"], card["steps"][0]["id"])
    got = client.get(f"/api/tasks/{task['id']}/recipients", headers=auth(employer_token)).json()
    assert got["today_status"][a["id"]] == "in_progress"
    _log(client, a["token"], card["assignment_id"], card["steps"][1]["id"])
    got = client.get(f"/api/tasks/{task['id']}/recipients", headers=auth(employer_token)).json()
    assert got["today_status"][a["id"]] == "done"
    # 둘에게 함께 다시 보내면 그 묶음이 마지막
    _send(client, employer_token, task["id"], [a["id"], b["id"]])
    got = client.get(f"/api/tasks/{task['id']}/recipients", headers=auth(employer_token)).json()
    assert sorted(got["last_batch_worker_ids"]) == sorted([a["id"], b["id"]])
    assert client.get(f"/api/tasks/{task['id']}", headers=auth(employer_token)).json()["recipients_count"] == 2


def test_recipients_records_access_per_worker_with_today_status(client, employer_token, workers):
    """받는 사람 시트의 오늘 상태는 근로자별 수행 정보다 — 오늘 배정이 있는 근로자마다 열람 기록을 남기고(1회차 검증),
    시트를 다시 열어도 짧은 창 안에서는 한 줄로 묶는다. 오늘 배정이 없는 근로자(none)는 남기지 않는다."""
    import privacy
    assert "task.recipients" in privacy.DEDUPED_ACTIONS
    task = _task(client, employer_token)
    a, b = workers
    _send(client, employer_token, task["id"], [a["id"]])
    before = clock.utcnow() - timedelta(seconds=1)

    def rows():
        with SessionLocal() as db:
            return db.scalars(select(AccessAuditLog.worker_id).where(
                AccessAuditLog.action == "task.recipients", AccessAuditLog.at >= before,
                AccessAuditLog.worker_id.in_([a["id"], b["id"]]))).all()
    assert client.get(f"/api/tasks/{task['id']}/recipients", headers=auth(employer_token)).status_code == 200
    assert rows() == [a["id"]]
    assert client.get(f"/api/tasks/{task['id']}/recipients", headers=auth(employer_token)).status_code == 200
    assert rows() == [a["id"]]


def test_assign_endpoint_shape_unchanged(client, employer_token, workers):
    """옛 화면의 POST …/assignments: 응답 모양 그대로, 같은 날 다시 부르면 같은 배정을 돌려준다."""
    task = _task(client, employer_token)
    emp = auth(employer_token)
    assert client.post(f"/api/tasks/{task['id']}/publish", headers=emp).status_code == 200
    r = client.post(f"/api/tasks/{task['id']}/assignments", headers=emp, json={"worker_id": workers[0]["id"]})
    assert r.status_code == 200
    first = r.json()
    assert set(first[0]) == {"id", "task_id", "worker_id", "status"}
    again = client.post(f"/api/tasks/{task['id']}/assignments", headers=emp, json={"worker_id": workers[0]["id"]})
    assert again.json() == first


# --- 2회차 검증: 날짜 기준 보기 ---------------------------------------------------------------

def _shift_assignment(aid, days, hours=0):
    with SessionLocal() as db:
        a = db.get(Assignment, aid)
        a.scheduled_day = a.scheduled_day + timedelta(days=days)
        a.assigned_date = a.assigned_date + timedelta(days=days, hours=hours)
        db.commit()


def test_dashboard_date_shows_that_days_assignment(client, employer_token, workers):
    """대시보드·코칭은 달력에서 고른 날(?date=)의 배정을 센다. 어제 1/2 → 오늘 다시 보냄(created)이면
    date=어제는 1/2, date=오늘은 0/2. 날짜가 없으면 지금처럼 오늘까지 중 가장 늦은 배정(0/2)."""
    task = _task(client, employer_token)
    w = workers[0]
    _send(client, employer_token, task["id"], [w["id"]])
    old = _task_cards(client, w["token"], task["id"])[0]
    total = len(old["steps"])
    assert total >= 2
    assert _log(client, w["token"], old["assignment_id"], old["steps"][0]["id"]).status_code == 201
    _shift_assignment(old["assignment_id"], -1)
    assert _outcome(_send(client, employer_token, task["id"], [w["id"]])) == "created"
    today = clock.local_today()
    yesterday = today - timedelta(days=1)
    base = f"/api/dashboard/tasks/{task['id']}"

    def dash(q):
        r = client.get(f"{base}?worker_id={w['id']}{q}", headers=auth(employer_token))
        assert r.status_code == 200, r.text
        return r.json()

    assert dash(f"&date={yesterday.isoformat()}")["completed_steps"] == 1
    assert dash(f"&date={today.isoformat()}")["completed_steps"] == 0
    assert dash("")["completed_steps"] == 0
    # 배정이 없는 날은 기록 없음(0)
    empty = dash(f"&date={(today - timedelta(days=5)).isoformat()}")
    assert empty["completed_steps"] == 0 and empty["total_steps"] == total
    # 코칭도 같은 날의 배정
    seen = {}
    import ai_client

    def fake(title, steps, ctx, allow_llm=True):
        seen["steps"] = steps
        return {"summary": "", "suggestions": []}
    orig = ai_client.coaching
    ai_client.coaching = fake
    try:
        r = client.get(f"{base}/coaching?worker_id={w['id']}&date={yesterday.isoformat()}",
                       headers=auth(employer_token))
        assert r.status_code == 200, r.text
        assert sum(1 for s in seen["steps"] if s["completed"]) == 1
        r = client.get(f"{base}/coaching?worker_id={w['id']}&date={today.isoformat()}",
                       headers=auth(employer_token))
        assert sum(1 for s in seen["steps"] if s["completed"]) == 0
    finally:
        ai_client.coaching = orig
    bad = client.get(f"{base}?worker_id={w['id']}&date=2026-13-40", headers=auth(employer_token))
    assert bad.status_code == 422


def test_history_ordered_by_scheduled_day(client, employer_token, workers):
    """'했던 일' 날짜 칸은 scheduled_day다. 정렬도 그 날짜 내림차순이어야 화면이 같은 날을 한 묶음으로 만든다
    (이틀 전 아침에 '어제'로 미리 보낸 일 + 이틀 전 오후에 그날 보낸 일 + 오늘 보낸 일)."""
    w = workers[0]
    t1, t2, t3 = (_task(client, employer_token)["id"] for _ in range(3))
    _send(client, employer_token, t1, [w["id"]])
    a1 = _task_cards(client, w["token"], t1)[0]["assignment_id"]
    with SessionLocal() as db:
        a = db.get(Assignment, a1)
        a.assigned_date = a.assigned_date - timedelta(days=2, hours=5)
        a.scheduled_day = a.scheduled_day - timedelta(days=1)
        db.commit()
    _send(client, employer_token, t2, [w["id"]])
    a2 = _task_cards(client, w["token"], t2)[0]["assignment_id"]
    _shift_assignment(a2, -2)
    _send(client, employer_token, t3, [w["id"]])
    hist = client.get("/api/worker/me/history", headers=auth(w["token"])).json()
    days = [h["assigned_date"] for h in hist]
    assert days == sorted(days, reverse=True), days
    today = clock.local_today()
    assert [h["task_id"] for h in hist] == [t3, t1, t2]
    assert days == [today.isoformat(), (today - timedelta(days=1)).isoformat(),
                    (today - timedelta(days=2)).isoformat()]
