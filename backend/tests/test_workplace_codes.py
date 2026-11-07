"""근로자 접속 코드의 테넌트 격리(Phase 0.1) 회귀 테스트.

예전에는 접속 코드가 전역 unique였고 로그인이 코드만으로 근로자를 찾았다. 그래서
- 사업주 B가 코드를 직접 지정해 근로자를 만들 때 409가 "다른 사업장에 이 코드가 있다"를 알려 줬고
  (스로틀 없음), 이걸로 남의 사업장 근로자 코드를 찾아 그 근로자로 로그인할 수 있었다.
- 목록·대시보드 응답에 평문 코드가 그대로 실렸다.
지금은 사업장 코드 + 접속 코드로 로그인하고, 코드는 사업장별 HMAC 해시로만 저장한다.
"""
import pytest

import ratelimit
from auth import hash_password, make_token
from conftest import auth
from database import SessionLocal
from models import Employer, Worker

DEMO_WP = "DEMO01"


def _login(client, workplace, code):
    return client.post("/api/auth/worker-login",
                       json={"workplace_code": workplace, "access_code": code})


@pytest.fixture()
def other_tenant():
    """두 번째 사업장(B). 끝나면 지워서 다른 테스트의 '근로자 1명' 가정을 깨지 않는다."""
    db = SessionLocal()
    emp = Employer(id="emp-b", name="B 사업주", org_name="B 작업장", login_id="tenant-b",
                   password_hash=hash_password("pw-b-1234"))
    db.add(emp)
    db.commit()
    wp = emp.workplace_code
    db.close()
    yield {"id": "emp-b", "token": make_token("emp-b", "employer"), "workplace_code": wp}
    db = SessionLocal()
    for w in db.query(Worker).filter(Worker.employer_id == "emp-b").all():
        db.delete(w)
    db.delete(db.get(Employer, "emp-b"))
    db.commit()
    db.close()


def _create(client, token, name="테스트", code=None):
    body = {"display_name": name}
    if code is not None:
        body["access_code"] = code
    return client.post("/api/workers", json=body, headers=auth(token))


# --- 사업장 코드 -----------------------------------------------------------------
def test_employer_gets_readable_workplace_code(other_tenant):
    wp = other_tenant["workplace_code"]
    assert 6 <= len(wp) <= 8
    assert wp.isalnum() and wp.upper() == wp
    # 사람이 옮겨 적다 헷갈리는 문자는 쓰지 않는다.
    assert not set(wp) & set("0O1I")


def test_workplace_endpoint_shows_own_code(client, employer_token, other_tenant):
    r = client.get("/api/workplace", headers=auth(employer_token))
    assert r.status_code == 200
    assert r.json()["workplace_code"] == DEMO_WP
    r = client.get("/api/workplace", headers=auth(other_tenant["token"]))
    assert r.json()["workplace_code"] == other_tenant["workplace_code"]


def test_workplace_endpoint_is_employer_only(client, worker_token):
    assert client.get("/api/workplace", headers=auth(worker_token)).status_code == 403


# --- 교차 테넌트 -----------------------------------------------------------------
def test_tenant_a_code_does_not_log_in_at_tenant_b(client, other_tenant):
    # 데모(A) 근로자 코드 1234는 A 사업장 코드로만 들어간다.
    assert _login(client, DEMO_WP, "1234").status_code == 200
    r = _login(client, other_tenant["workplace_code"], "1234")
    assert r.status_code == 401


def test_two_tenants_can_use_the_same_code(client, employer_token, other_tenant):
    a = _create(client, employer_token, "A근로", "246810")
    b = _create(client, other_tenant["token"], "B근로", "246810")
    try:
        assert a.status_code == 201, a.text
        assert b.status_code == 201, b.text
        ra = _login(client, DEMO_WP, "246810")
        rb = _login(client, other_tenant["workplace_code"], "246810")
        assert ra.json()["display_name"] == "A근로"
        assert rb.json()["display_name"] == "B근로"
    finally:
        client.delete(f"/api/workers/{a.json()['id']}", headers=auth(employer_token))


def test_custom_code_does_not_reveal_other_tenant(client, other_tenant):
    # A(데모)에 1234가 있어도 B는 아무 일 없다는 듯 같은 코드를 만들 수 있다 — 409가 나면 오라클이다.
    r = _create(client, other_tenant["token"], "B근로", "1234")
    assert r.status_code == 201, r.text


def test_same_tenant_duplicate_is_409(client, employer_token):
    r = _create(client, employer_token, "중복", "1234")
    assert r.status_code == 409


def test_custom_code_attempts_are_throttled_per_employer(client, employer_token, monkeypatch):
    """같은 사업장 안의 409는 여전히 '이 코드를 쓰는 동료가 있다'는 신호라 시도 횟수를 막는다."""
    monkeypatch.setattr(ratelimit.worker_throttle, "max_failures", 3)
    for _ in range(3):
        assert _create(client, employer_token, "중복", "1234").status_code == 409
    r = _create(client, employer_token, "새사람", "8642097")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0


def test_unknown_workplace_looks_like_wrong_code(client):
    bad_wp = _login(client, "ZZZZZZ", "1234")
    bad_code = _login(client, DEMO_WP, "000000")
    assert bad_wp.status_code == bad_code.status_code == 401
    # 사업장 코드가 틀렸는지 접속 코드가 틀렸는지 구별되지 않아야 사업장 존재를 탐지할 수 없다.
    assert bad_wp.json()["detail"] == bad_code.json()["detail"]


def test_workplace_code_is_case_and_space_insensitive(client):
    assert _login(client, " demo01 ", "1234").status_code == 200


# --- 접속 코드 표시 범위 -------------------------------------------------------------
# 2026-11-07 사용자 요청: 사업주 화면(근로자 목록·대시보드 근로자 목록)에 전체 코드를 보여 준다(근로자에게 다시
# 알려 줄 수 있게). 대신 그 근로자를 소유한 사업주에게만 나가고, 근로자용 응답·다른 사업장·DB 평문에는 없어야 한다.
def test_owner_employer_sees_full_code(client, employer_token):
    created = _create(client, employer_token, "평문검사", "97531864")
    assert created.status_code == 201
    w = created.json()
    try:
        assert w["access_code"] == "97531864"
        assert w["access_code_hint"] == "64"

        task = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                           headers=auth(employer_token)).json()
        client.post(f"/api/tasks/{task['id']}/publish", headers=auth(employer_token))
        assigned = client.post(f"/api/tasks/{task['id']}/assignments",
                               json={"worker_ids": [w["id"]]}, headers=auth(employer_token))
        assert assigned.status_code == 200

        listed = next(x for x in client.get("/api/workers", headers=auth(employer_token)).json()
                      if x["id"] == w["id"])
        assert listed["access_code"] == "97531864"
        dash = next(x for x in client.get(f"/api/dashboard/tasks/{task['id']}/workers",
                                          headers=auth(employer_token)).json() if x["worker_id"] == w["id"])
        assert dash["access_code"] == "97531864"

        # 코드 표시가 필요 없는 응답에는 여전히 싣지 않는다.
        for path in (f"/api/dashboard/tasks/{task['id']}?worker_id={w['id']}",
                     f"/api/workers/{w['id']}/tasks", "/api/workplace"):
            r = client.get(path, headers=auth(employer_token))
            assert r.status_code == 200, (path, r.text)
            assert "97531864" not in r.text, path

        # 근로자 자신의 로그인·오늘 카드 응답에는 코드가 없다(공용 태블릿 화면에 남지 않게).
        tok = _login(client, DEMO_WP, "97531864")
        assert tok.status_code == 200
        assert "97531864" not in tok.text
        today = client.get("/api/worker/me/today", headers=auth(tok.json()["token"]))
        assert "97531864" not in today.text

        reissued = client.post(f"/api/workers/{w['id']}/access-code", headers=auth(employer_token))
        new_code = reissued.json()["access_code"]
        assert len(new_code) == 6 and new_code.isdigit()
        relisted = next(x for x in client.get("/api/workers", headers=auth(employer_token)).json()
                        if x["id"] == w["id"])
        assert relisted["access_code"] == new_code
    finally:
        client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


def test_other_tenant_never_sees_code(client, employer_token, other_tenant):
    w = _create(client, employer_token, "남의근로", "86421357").json()
    try:
        for path in ("/api/workers", f"/api/workers/{w['id']}/tasks"):
            r = client.get(path, headers=auth(other_tenant["token"]))
            assert "86421357" not in r.text, path
    finally:
        client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


def test_db_stores_no_plaintext_code(client, employer_token):
    w = _create(client, employer_token, "해시검사", "86420975").json()
    try:
        db = SessionLocal()
        row = db.get(Worker, w["id"])
        assert "86420975" not in row.access_code_hash
        assert "86420975" not in (row.access_code_cipher or "")
        assert row.access_code_cipher and row.access_code_cipher.startswith("v1:")
        assert row.access_code_hint == "75"
        assert len(row.access_code_hash) == 64
        # 평문 컬럼 자체가 없어야 한다.
        assert "access_code" not in Worker.__table__.columns
        db.close()
    finally:
        client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


def test_cipher_moved_to_other_tenant_row_does_not_decrypt(client, employer_token, other_tenant):
    """암호문은 사업장 id에 묶여 있다(AAD). 다른 사업장 행에 옮겨 붙여도 그 사업주에게 코드가 보이지 않는다."""
    a = _create(client, employer_token, "원래", "75319864").json()
    b = _create(client, other_tenant["token"], "옮김", "11223344").json()
    try:
        db = SessionLocal()
        db.get(Worker, b["id"]).access_code_cipher = db.get(Worker, a["id"]).access_code_cipher
        db.commit()
        db.close()
        listed = next(x for x in client.get("/api/workers", headers=auth(other_tenant["token"])).json()
                      if x["id"] == b["id"])
        assert listed["access_code"] is None
    finally:
        client.delete(f"/api/workers/{a['id']}", headers=auth(employer_token))


def test_legacy_worker_code_filled_on_next_login(client, employer_token):
    """0005 이전 근로자는 암호문이 없다(평문을 몰라서). 로그인에 성공하면 그 순간 채워진다."""
    w = _create(client, employer_token, "옛근로", "24681357").json()
    try:
        db = SessionLocal()
        db.get(Worker, w["id"]).access_code_cipher = None
        db.commit()
        db.close()
        before = next(x for x in client.get("/api/workers", headers=auth(employer_token)).json()
                      if x["id"] == w["id"])
        assert before["access_code"] is None and before["access_code_hint"] == "57"
        assert _login(client, DEMO_WP, "24681357").status_code == 200
        after = next(x for x in client.get("/api/workers", headers=auth(employer_token)).json()
                     if x["id"] == w["id"])
        assert after["access_code"] == "24681357"
    finally:
        client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


def test_reissue_invalidates_old_token_with_workplace_login(client, employer_token):
    w = _create(client, employer_token, "재발급").json()
    try:
        tok = _login(client, DEMO_WP, w["access_code"]).json()["token"]
        assert client.get("/api/worker/me/today", headers=auth(tok)).status_code == 200
        client.post(f"/api/workers/{w['id']}/access-code", headers=auth(employer_token))
        assert client.get("/api/worker/me/today", headers=auth(tok)).status_code == 401
        assert _login(client, DEMO_WP, w["access_code"]).status_code == 401
    finally:
        client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


# --- 동시 요청으로 확인과 저장 사이에 코드가 겹친 경우 ----------------------------------------
# 앞의 "이미 있나" 확인은 commit 전에 한다. 동시 요청이 그 사이에 같은 코드를 저장하면 DB의
# (employer_id, access_code_hash) unique가 막는다. 그 IntegrityError가 500으로 새면 안 된다.
# 확인 함수/코드 생성기를 바꿔 끼워 "확인은 통과했는데 저장에서 겹친" 상황을 재현한다.
def _codes(*seq):
    it = iter(seq)
    return lambda db, employer_id: next(it)


def test_custom_code_race_is_409_not_500(client, employer_token, monkeypatch):
    import main

    monkeypatch.setattr(main, "_access_code_taken", lambda db, employer_id, code: False)
    r = _create(client, employer_token, "경합", "1234")  # 데모 근로자가 이미 1234
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == "이미 사용 중인 접속 코드입니다. 다른 코드를 입력해 주세요."


def test_generated_code_race_retries_with_new_code(client, employer_token, monkeypatch):
    import main

    monkeypatch.setattr(main, "_new_access_code", _codes("1234", "864213"))
    r = _create(client, employer_token, "자동경합")
    assert r.status_code == 201, r.text
    try:
        assert r.json()["access_code"] == "864213"
        assert _login(client, DEMO_WP, "864213").status_code == 200
    finally:
        client.delete(f"/api/workers/{r.json()['id']}", headers=auth(employer_token))


def test_reissue_race_retries_with_new_code(client, employer_token, monkeypatch):
    import main

    w = _create(client, employer_token, "재발급경합").json()
    try:
        monkeypatch.setattr(main, "_new_access_code", _codes("1234", "531864"))
        r = client.post(f"/api/workers/{w['id']}/access-code", headers=auth(employer_token))
        assert r.status_code == 200, r.text
        assert r.json()["access_code"] == "531864"
        assert _login(client, DEMO_WP, "531864").status_code == 200
        # 겹친 코드의 원래 주인(데모 근로자)은 그대로다.
        assert _login(client, DEMO_WP, "1234").status_code == 200
    finally:
        client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


def test_unknown_workplace_does_same_work_as_wrong_code(client, monkeypatch):
    """사업장 코드가 없을 때 해시·조회를 건너뛰면 응답 시간으로 사업장 존재를 알 수 있다.
    두 경우 모두 해시 계산을 한 번씩 하는지 확인한다(조회도 같은 자리에서 한다)."""
    import main

    calls = []
    real = main.hash_access_code
    monkeypatch.setattr(main, "hash_access_code",
                        lambda employer_id, code: calls.append(employer_id) or real(employer_id, code))
    assert _login(client, "ZZZZZZ", "1234").status_code == 401
    assert _login(client, DEMO_WP, "000000").status_code == 401
    assert len(calls) == 2
