"""2d 관리 화면 서버 시험 (scratchpad/p2/contract.md §6, tasks.md §7).

지키는 것:
- 근로자 목록에는 전체 접속 코드가 없다(문자열 검사). 코드는 reveal로만 받고, 볼 때마다 감사가 남고, 분당 10번까지다.
- 근로자 지우기는 이름을 그대로 다시 적어야 한다(다르면 422 고정 문구). 옛 DELETE는 없다.
- 호칭은 한글 1~6자(422 고정 문구), /api/worker/me에 반영된다.
- 근로자 화면 기본값은 새 근로자에게만 쓴다.
- device_link 모양: PUBLIC_FRONTEND_URL + /w?site=CODE.
- 목록 열(오늘 배지·7일 완료·7일 도움·동의 상태)과 근로자 현황(stats).
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

import manage  # noqa: E402
import workers_admin  # noqa: E402
from conftest import auth, give_pictures  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import AccessAuditLog, Worker  # noqa: E402

MSG_TITLE = "호칭은 한글 1~6자로 적어 주세요."
MSG_NAME = "이름이 맞지 않아요. 지울 근로자 이름을 그대로 적어 주세요."


# --- 도우미 ------------------------------------------------------------------

def _employer(client) -> dict:
    """시험마다 따로 쓰는 사업장(데모 사업장의 호칭·기본값을 바꾸지 않게)."""
    login = f"mng-{uuid.uuid4().hex[:8]}"
    manage.create_employer(login, "", "관리 시험", "correct-horse-1")
    r = client.post("/api/auth/login", json={"login_id": login, "password": "correct-horse-1"})
    assert r.status_code == 200, r.text
    return auth(r.json()["token"])


def _worker(client, emp, name="김민지", code=None) -> dict:
    body = {"display_name": name}
    if code:
        body["access_code"] = code
    r = client.post("/api/workers", json=body, headers=emp)
    assert r.status_code == 201, r.text
    return r.json()


def _login(client, emp, code) -> dict:
    wp = client.get("/api/workplace", headers=emp).json()["workplace_code"]
    r = client.post("/api/auth/worker-login", json={"workplace_code": wp, "access_code": code})
    assert r.status_code == 200, r.text
    return auth(r.json()["token"])


def _reveal(client, emp, wid):
    return client.post(f"/api/workers/{wid}/access-code/reveal", headers=emp)


def _row(client, emp, wid) -> dict:
    return next(w for w in client.get("/api/workers", headers=emp).json() if w["id"] == wid)


def _sent_task(client, emp, worker_id) -> dict:
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"}, headers=emp)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    give_pictures(client, emp["Authorization"].split()[1], tid)
    s = client.post(f"/api/tasks/{tid}/send", json={"worker_ids": [worker_id], "day": "today"}, headers=emp)
    assert s.status_code == 200, s.text
    return client.get(f"/api/tasks/{tid}", headers=emp).json()


def _card(client, wh, task_id) -> dict:
    cards = client.get("/api/worker/me/today?include_done=true", headers=wh).json()
    return next(c for c in cards if c["task_id"] == task_id)


def _audits(action: str, worker_id: str) -> int:
    db = SessionLocal()
    try:
        return db.scalar(select(func.count()).select_from(AccessAuditLog).where(
            AccessAuditLog.action == action, AccessAuditLog.worker_id == worker_id))
    finally:
        db.close()


# --- 목록에서 코드 빼기 · reveal ---------------------------------------------------

def test_worker_list_has_no_full_code(client):
    emp = _employer(client)
    a = _worker(client, emp, "김민지", "97531864")
    b = _worker(client, emp, "이서준")  # 서버가 만든 4자리
    r = client.get("/api/workers", headers=emp)
    assert r.status_code == 200
    assert "97531864" not in r.text and b["access_code"] not in r.text
    for row in r.json():
        assert "access_code" not in row
    rows = {w["id"]: w for w in r.json()}
    assert rows[a["id"]]["code_length"] == 8 and rows[b["id"]]["code_length"] == 4
    for key in ("today_badge", "done_7d", "help_7d", "consent_state"):
        assert key in rows[a["id"]]
    assert rows[a["id"]]["done_7d"] == [0] * 7
    # 수정 응답에도 전체 코드가 없다.
    p = client.patch(f"/api/workers/{a['id']}", json={"note": "천천히"}, headers=emp)
    assert p.status_code == 200 and "97531864" not in p.text
    # 만들기·재발급 응답에는 방금 만든 코드가 있다(인쇄 카드에 크게 보여 준다).
    re = client.post(f"/api/workers/{b['id']}/access-code", headers=emp)
    assert re.status_code == 200 and len(re.json()["access_code"]) == 4


def test_reveal_returns_code_and_audits_every_time(client):
    emp = _employer(client)
    w = _worker(client, emp, "김민지", "86421357")
    for _ in range(3):
        r = _reveal(client, emp, w["id"])
        assert r.status_code == 200, r.text
        assert r.json() == {"code": "86421357"}
    # 폴링 묶기 없이 볼 때마다 한 줄씩.
    assert _audits("worker.code.reveal", w["id"]) == 3


def test_reveal_limited_to_10_per_minute(client):
    emp = _employer(client)
    w = _worker(client, emp)
    for i in range(10):
        assert _reveal(client, emp, w["id"]).status_code == 200, i
    r = _reveal(client, emp, w["id"])
    assert r.status_code == 429
    assert r.json()["detail"] == "번호를 너무 자주 열었어요. 1분 뒤에 다시 눌러 주세요."
    assert int(r.headers["Retry-After"]) >= 1
    assert _audits("worker.code.reveal", w["id"]) == 10
    # 다른 사업주는 따로 센다.
    emp2 = _employer(client)
    w2 = _worker(client, emp2)
    assert _reveal(client, emp2, w2["id"]).status_code == 200


def test_no_employer_read_route_carries_full_code(client):
    """전체 코드는 reveal로만 나간다. 다른 읽기 경로(옛 대시보드 근로자 목록 포함)가 한도·감사를 건너뛰는 길이 되면 안 된다."""
    emp = _employer(client)
    code = "86421357"
    w = _worker(client, emp, "김민지", code)
    task = _sent_task(client, emp, w["id"])
    tid, wid = task["id"], w["id"]
    paths = ("/api/workers", f"/api/dashboard/tasks/{tid}/workers", f"/api/dashboard/tasks/{tid}?worker_id={wid}",
             f"/api/tasks/{tid}/recipients", "/api/employer/tasks", f"/api/tasks/{tid}",
             f"/api/workers/{wid}/export", f"/api/workers/{wid}/tasks", "/api/workplace")

    def check():
        for path in paths:
            r = client.get(path, headers=emp)
            assert r.status_code == 200, (path, r.text)
            assert code not in r.text, path

    check()
    dash = client.get(f"/api/dashboard/tasks/{tid}/workers", headers=emp).json()
    assert dash and all("access_code" not in x for x in dash)
    assert dash[0]["access_code_hint"] == code[-2:]
    # reveal 한도를 다 쓴 뒤에도 다른 길로 코드가 나오지 않는다.
    for _ in range(10):
        assert _reveal(client, emp, wid).status_code == 200
    assert _reveal(client, emp, wid).status_code == 429
    check()
    assert _audits("worker.code.reveal", wid) == 10


def test_reveal_other_tenant_is_404_without_audit(client):
    emp, other = _employer(client), _employer(client)
    w = _worker(client, emp, "김민지", "75319864")
    r = _reveal(client, other, w["id"])
    assert r.status_code == 404 and "75319864" not in r.text
    assert _audits("worker.code.reveal", w["id"]) == 0


# --- 근로자 지우기 -----------------------------------------------------------------

def test_delete_needs_exact_name(client):
    emp = _employer(client)
    w = _worker(client, emp, "김민지")
    for wrong in ("", "김민", "김민지 님", "kim"):
        r = client.post(f"/api/workers/{w['id']}/delete", json={"confirm_name": wrong}, headers=emp)
        assert r.status_code == 422, wrong
        assert r.json()["detail"] == MSG_NAME
    db = SessionLocal()
    assert db.get(Worker, w["id"]) is not None
    db.close()
    # 앞뒤 공백은 같은 이름으로 본다.
    r = client.post(f"/api/workers/{w['id']}/delete", json={"confirm_name": "  김민지 "}, headers=emp)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and "name_mentions" in r.json()
    assert all(x["id"] != w["id"] for x in client.get("/api/workers", headers=emp).json())
    assert _audits("worker.delete", w["id"]) == 1


def test_delete_other_tenant_404_and_old_delete_gone(client):
    emp, other = _employer(client), _employer(client)
    w = _worker(client, emp, "김민지")
    r = client.post(f"/api/workers/{w['id']}/delete", json={"confirm_name": "김민지"}, headers=other)
    assert r.status_code == 404
    # 옛 DELETE /api/workers/{id}는 옛 화면과 함께 지웠다.
    assert client.delete(f"/api/workers/{w['id']}", headers=emp).status_code == 405
    db = SessionLocal()
    assert db.get(Worker, w["id"]) is not None
    db.close()


# --- 사업장 설정: 호칭 · 기본값 · device_link --------------------------------------

def test_workplace_shape_and_device_link(client, monkeypatch):
    emp = _employer(client)
    monkeypatch.delenv("PUBLIC_FRONTEND_URL", raising=False)
    wp = client.get("/api/workplace", headers=emp).json()
    code = wp["workplace_code"]
    assert wp["device_link"] == f"http://localhost:5173/w?site={code}"
    assert wp["teacher_title"] == "선생님"
    assert wp["worker_defaults"]["tts_rate"] == 0.9 and len(wp["worker_defaults"]) == 8
    monkeypatch.setenv("PUBLIC_FRONTEND_URL", "https://jobcard.example.kr/")
    assert client.get("/api/workplace", headers=emp).json()["device_link"] == \
        f"https://jobcard.example.kr/w?site={code}"


@pytest.mark.parametrize("title", ["코치", "반장님", "선생님", "가나다라마바", " 팀장 "])
def test_teacher_title_accepts_hangul_1_to_6(client, title):
    emp = _employer(client)
    r = client.patch("/api/workplace", json={"teacher_title": title}, headers=emp)
    assert r.status_code == 200, r.text
    assert r.json()["teacher_title"] == title.strip()


@pytest.mark.parametrize("title", ["", "   ", "가나다라마바사", "Teacher", "선생님1", "선 생", "ㅅㅅ", "코치!",
                                   "선생님​"])
def test_teacher_title_rejects_others(client, title):
    emp = _employer(client)
    r = client.patch("/api/workplace", json={"teacher_title": title, "org_name": "바뀌면 안 됨"}, headers=emp)
    assert r.status_code == 422
    assert r.json()["detail"] == MSG_TITLE
    wp = client.get("/api/workplace", headers=emp).json()
    assert wp["teacher_title"] == "선생님" and wp["org_name"] == "관리 시험"


def test_org_name_patch(client):
    emp = _employer(client)
    r = client.patch("/api/workplace", json={"org_name": "  행복   카페 "}, headers=emp)
    assert r.status_code == 200 and r.json()["org_name"] == "행복 카페"
    for bad in ("", "  ", "가" * 41):
        r = client.patch("/api/workplace", json={"org_name": bad}, headers=emp)
        assert r.status_code == 422 and r.json()["detail"] == "사업장 이름을 1~40자로 적어 주세요."
    assert client.patch("/api/workplace", json={"pin": "1234"}, headers=emp).status_code == 422


def test_me_reflects_teacher_title(client):
    emp = _employer(client)
    w = _worker(client, emp)
    wh = _login(client, emp, w["access_code"])
    assert client.get("/api/worker/me", headers=wh).json()["teacher_title"] == "선생님"
    assert client.patch("/api/workplace", json={"teacher_title": "코치"}, headers=emp).status_code == 200
    assert client.get("/api/worker/me", headers=wh).json()["teacher_title"] == "코치"
    # 다른 사업장 근로자는 그대로.
    emp2 = _employer(client)
    w2 = _worker(client, emp2)
    assert client.get("/api/worker/me", headers=_login(client, emp2, w2["access_code"])).json()[
        "teacher_title"] == "선생님"


def test_bad_stored_title_reads_as_default(client):
    emp = _employer(client)
    w = _worker(client, emp)
    db = SessionLocal()
    db.get(Worker, w["id"]).employer.teacher_title = "Bad!"
    db.commit()
    db.close()
    assert client.get("/api/workplace", headers=emp).json()["teacher_title"] == "선생님"


def test_worker_defaults_apply_only_to_new_workers(client):
    emp = _employer(client)
    old = _worker(client, emp, "옛근로자")
    r = client.patch("/api/workplace", json={"worker_defaults": {"tts_rate": 0.8, "font_size": "large"}},
                     headers=emp)
    assert r.status_code == 200, r.text
    d = r.json()["worker_defaults"]
    assert d["tts_rate"] == 0.8 and d["font_size"] == "large" and d["autoplay_sound"] is True
    # 보낸 키만 병합한다.
    r = client.patch("/api/workplace", json={"worker_defaults": {"hand": "left"}}, headers=emp)
    assert r.json()["worker_defaults"]["tts_rate"] == 0.8 and r.json()["worker_defaults"]["hand"] == "left"

    new = _worker(client, emp, "새근로자")
    assert new["a11y_prefs"]["tts_rate"] == 0.8 and new["a11y_prefs"]["hand"] == "left"
    assert _row(client, emp, old["id"])["a11y_prefs"]["tts_rate"] == 0.9
    # 근로자 기기도 로그인하면 받는다.
    me = client.get("/api/worker/me", headers=_login(client, emp, new["access_code"])).json()
    assert me["a11y_prefs"]["tts_rate"] == 0.8 and me["a11y_prefs"]["font_size"] == "large"
    # 그 근로자를 따로 바꾸면 기본값과 상관없이 그 값.
    p = client.patch(f"/api/workers/{new['id']}", json={"a11y_prefs": {"tts_rate": 1.0}}, headers=emp)
    assert p.json()["a11y_prefs"]["tts_rate"] == 1.0 and p.json()["a11y_prefs"]["hand"] == "left"


@pytest.mark.parametrize("bad", [{"tts_rate": 0.7}, {"sound": True}, {"autoplay_sound": "off"}])
def test_worker_defaults_reject_bad_values(client, bad):
    emp = _employer(client)
    r = client.patch("/api/workplace", json={"worker_defaults": bad}, headers=emp)
    assert r.status_code == 422
    assert client.get("/api/workplace", headers=emp).json()["worker_defaults"]["tts_rate"] == 0.9


def test_workplace_needs_employer(client, worker_token):
    assert client.patch("/api/workplace", json={"teacher_title": "코치"}).status_code == 401
    assert client.patch("/api/workplace", json={"teacher_title": "코치"},
                        headers=auth(worker_token)).status_code == 403


# --- 목록 열 ---------------------------------------------------------------------

def test_list_columns_today_badge_and_week(client):
    emp = _employer(client)
    w = _worker(client, emp)
    wh = _login(client, emp, w["access_code"])
    assert _row(client, emp, w["id"])["today_badge"] == "none"

    task = _sent_task(client, emp, w["id"])
    assert _row(client, emp, w["id"])["today_badge"] == "not_started"

    card = _card(client, wh, task["id"])
    steps = card["steps"]
    r = client.post("/api/performance-logs", headers=wh,
                    json={"assignment_id": card["assignment_id"], "step_id": steps[0]["id"], "duration_sec": 12})
    assert r.status_code == 201, r.text
    assert _row(client, emp, w["id"])["today_badge"] == "in_progress"

    h = client.post("/api/worker/help", headers=wh,
                    json={"assignment_id": card["assignment_id"], "step_id": steps[1]["id"]})
    assert h.status_code == 201, h.text
    row = _row(client, emp, w["id"])
    assert row["today_badge"] == "help" and row["help_7d"] == 1
    client.post(f"/api/employer/help/{h.json()['id']}/acknowledge", headers=emp)
    assert _row(client, emp, w["id"])["today_badge"] == "help_coming"
    client.post(f"/api/employer/help/{h.json()['id']}/resolve", headers=emp)

    for st in steps[1:]:
        r = client.post("/api/performance-logs", headers=wh,
                        json={"assignment_id": card["assignment_id"], "step_id": st["id"], "duration_sec": 30})
        assert r.status_code == 201, r.text
    row = _row(client, emp, w["id"])
    assert row["today_badge"] == "done"
    assert row["done_7d"] == [0, 0, 0, 0, 0, 0, 1]
    assert row["help_7d"] == 1


def test_list_columns_consent_state(client):
    emp = _employer(client)
    w = _worker(client, emp)
    assert _row(client, emp, w["id"])["consent_state"] == "missing"
    c = client.post(f"/api/workers/{w['id']}/consents", json={"consent_type": "personal_info"}, headers=emp)
    assert c.status_code == 201, c.text
    assert _row(client, emp, w["id"])["consent_state"] == "ai_missing"
    a = client.post(f"/api/workers/{w['id']}/consents", json={"consent_type": "ai_processing"}, headers=emp)
    assert _row(client, emp, w["id"])["consent_state"] == "complete"
    client.post(f"/api/workers/{w['id']}/consents/{a.json()['id']}/revoke", headers=emp)
    assert _row(client, emp, w["id"])["consent_state"] == "ai_missing"


# --- 근로자 현황 ------------------------------------------------------------------

def test_worker_stats(client):
    emp = _employer(client)
    w = _worker(client, emp)
    wh = _login(client, emp, w["access_code"])
    empty = client.get(f"/api/employer/workers/{w['id']}/stats", headers=emp)
    assert empty.status_code == 200, empty.text
    body = empty.json()
    assert body["days"] == 7 and len(body["daily"]) == 7 and body["steps"] == [] and body["avg_step_sec"] == 0

    task = _sent_task(client, emp, w["id"])
    card = _card(client, wh, task["id"])
    durations = [148, 30] + [10] * (len(card["steps"]) - 2)
    for st, sec in zip(card["steps"], durations):
        r = client.post("/api/performance-logs", headers=wh, json={
            "assignment_id": card["assignment_id"], "step_id": st["id"], "duration_sec": sec, "replay_count": 1})
        assert r.status_code == 201, r.text
    body = client.get(f"/api/employer/workers/{w['id']}/stats?days=7", headers=emp).json()
    today = body["daily"][-1]
    assert today["assigned"] == 1 and today["done"] == 1
    assert today["steps_done"] == len(card["steps"]) and today["work_sec"] == sum(durations)
    first = next(s for s in body["steps"] if s["order"] == card["steps"][0]["order"])
    assert first["avg_duration_sec"] == 148 and first["samples"] == 1 and first["replay_count"] == 1
    assert first["task_title"] == task["title"]
    assert body["avg_step_sec"] == round(sum(durations) / len(durations), 1)
    assert _audits("worker.stats", w["id"]) >= 1

    assert len(client.get(f"/api/employer/workers/{w['id']}/stats?days=1", headers=emp).json()["daily"]) == 1
    for bad in (0, 32):
        assert client.get(f"/api/employer/workers/{w['id']}/stats?days={bad}", headers=emp).status_code == 422
    assert client.get(f"/api/employer/workers/{w['id']}/stats", headers=_employer(client)).status_code == 404


def test_new_worker_prefs_helper():
    class E:
        worker_defaults = "{}"
    assert workers_admin.new_worker_prefs(E()) == "{}"
    E.worker_defaults = '{"tts_rate": 0.8, "bogus": 1}'
    out = workers_admin.new_worker_prefs(E())
    assert '"tts_rate": 0.8' in out and "bogus" not in out
