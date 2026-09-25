"""배포 전 보안 회귀 테스트 — 접속 코드·로그인 대입 제한·운영 설정·단계 그림 URL."""
import pytest

import auth as auth_mod
import main
import ratelimit
from conftest import auth


def _create_worker(client, token, **body):
    return client.post("/api/workers", json={"display_name": "테스트", **body}, headers=auth(token))


def _cleanup(client, token, worker_id):
    client.delete(f"/api/workers/{worker_id}", headers=auth(token))


# --- 접속 코드 ---------------------------------------------------------------
def test_worker_gets_random_six_digit_code_when_blank(client, employer_token):
    r = _create_worker(client, employer_token)
    assert r.status_code == 201, r.text
    w = r.json()
    try:
        assert len(w["access_code"]) == 6 and w["access_code"].isdigit()
        login = client.post("/api/auth/worker-login", json={"access_code": w["access_code"]})
        assert login.status_code == 200
    finally:
        _cleanup(client, employer_token, w["id"])


def test_blank_string_code_is_treated_as_auto(client, employer_token):
    r = _create_worker(client, employer_token, access_code="  ")
    assert r.status_code == 201, r.text
    _cleanup(client, employer_token, r.json()["id"])


@pytest.mark.parametrize("code", ["1234", "12345", "abcdef", "12 3456"])
def test_short_or_non_numeric_codes_are_rejected(client, employer_token, code):
    assert _create_worker(client, employer_token, access_code=code).status_code == 422


def test_legacy_short_code_still_logs_in(client):
    # 시드 근로자는 예전 4자리 코드(1234)를 쓴다. 규칙이 바뀌어도 기존 근로자는 계속 로그인돼야 한다.
    assert client.post("/api/auth/worker-login", json={"access_code": "1234"}).status_code == 200


def test_reissue_replaces_code(client, employer_token):
    w = _create_worker(client, employer_token).json()
    try:
        old = w["access_code"]
        r = client.post(f"/api/workers/{w['id']}/access-code", headers=auth(employer_token))
        assert r.status_code == 200, r.text
        new = r.json()["access_code"]
        assert new != old and len(new) == 6
        assert client.post("/api/auth/worker-login", json={"access_code": old}).status_code == 401
        assert client.post("/api/auth/worker-login", json={"access_code": new}).status_code == 200
    finally:
        _cleanup(client, employer_token, w["id"])


def test_reissue_requires_owner(client, employer_token, worker_token):
    assert client.post("/api/workers/wrk-demo/access-code",
                       headers=auth(worker_token)).status_code == 403
    assert client.post("/api/workers/no-such/access-code",
                       headers=auth(employer_token)).status_code == 404


# --- 로그인 대입 제한 --------------------------------------------------------------
def test_worker_code_guessing_is_throttled(client, monkeypatch):
    monkeypatch.setattr(ratelimit.worker_throttle, "max_failures", 5)
    for i in range(5):
        r = client.post("/api/auth/worker-login", json={"access_code": f"99990{i}"})
        assert r.status_code == 401
    blocked = client.post("/api/auth/worker-login", json={"access_code": "999999"})
    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    # 막힌 동안에는 맞는 코드도 받지 않는다(맞았는지 여부가 새어 나가지 않게).
    assert client.post("/api/auth/worker-login", json={"access_code": "1234"}).status_code == 429


def test_worker_success_does_not_reset_ip_counter(client, monkeypatch):
    monkeypatch.setattr(ratelimit.worker_throttle, "max_failures", 3)
    for i in range(2):
        client.post("/api/auth/worker-login", json={"access_code": f"88880{i}"})
    assert client.post("/api/auth/worker-login", json={"access_code": "1234"}).status_code == 200
    client.post("/api/auth/worker-login", json={"access_code": "888809"})
    assert client.post("/api/auth/worker-login", json={"access_code": "1234"}).status_code == 429


def test_employer_password_guessing_is_throttled(client, monkeypatch):
    monkeypatch.setattr(ratelimit.employer_throttle, "max_failures", 3)
    for _ in range(3):
        r = client.post("/api/auth/login", json={"login_id": "demo", "password": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"login_id": "demo", "password": "demo1234"})
    assert r.status_code == 429


def test_throttle_window_expires(monkeypatch):
    t = ratelimit.LoginThrottle(max_failures=2, window_sec=60)
    now = [1000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])
    t.fail("k"); t.fail("k")
    assert t.retry_after("k") > 0
    now[0] += 61
    assert t.retry_after("k") == 0


def test_forwarded_for_is_ignored_unless_trusted(client, monkeypatch):
    monkeypatch.setattr(ratelimit.worker_throttle, "max_failures", 2)
    for i in range(2):
        client.post("/api/auth/worker-login", json={"access_code": f"77770{i}"},
                    headers={"X-Forwarded-For": f"10.0.0.{i}"})
    # 헤더만 바꿔서는 제한을 우회할 수 없다.
    r = client.post("/api/auth/worker-login", json={"access_code": "1234"},
                    headers={"X-Forwarded-For": "10.0.0.99"})
    assert r.status_code == 429


# --- 운영 설정 ---------------------------------------------------------------
@pytest.mark.parametrize("secret", ["", "   ", "dev-insecure-secret-change-me", "short-secret"])
def test_production_rejects_weak_secret(monkeypatch, secret):
    monkeypatch.setenv("JOBCARD_ENV", "prod")
    monkeypatch.setenv("JOBCARD_SECRET", secret)
    with pytest.raises(RuntimeError):
        auth_mod.check_production_config()


def test_production_accepts_strong_secret(monkeypatch):
    monkeypatch.setenv("JOBCARD_ENV", "prod")
    monkeypatch.setenv("JOBCARD_SECRET", "x" * 48)
    auth_mod.check_production_config()


def test_empty_secret_is_not_used_as_hmac_key(monkeypatch):
    monkeypatch.setenv("JOBCARD_SECRET", "")
    assert auth_mod._secret() == auth_mod._DEV_SECRET


def test_demo_seed_is_off_in_production(monkeypatch):
    monkeypatch.setenv("JOBCARD_ENV", "prod")
    monkeypatch.delenv("DEMO_SEED", raising=False)
    assert main._demo_seed_enabled() is False
    monkeypatch.setenv("DEMO_SEED", "1")
    assert main._demo_seed_enabled() is True


# --- 단계 그림 URL --------------------------------------------------------------
@pytest.mark.parametrize("url,ok", [
    ("http://localhost:8000/api/aac/images/cafe/CAFE_013.webp", True),
    ("http://localhost:8000/api/photos/abc.png", True),
    ("/api/aac/images/cafe/CAFE_013.webp", True),
    ("http://evil.example/api/aac/images/cafe/CAFE_013.webp", False),
    ("https://evil.example/pixel.gif", False),
    ("http://localhost:8000/api/photos/../../secrets/google-tts.json", False),
    ("javascript:alert(1)", False),
])
def test_step_symbol_url_must_be_own_image(client, employer_token, url, ok):
    task = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                       headers=auth(employer_token)).json()
    step_id = task["steps"][0]["id"]
    r = client.patch(f"/api/tasks/{task['id']}/steps/{step_id}",
                     json={"symbol_url": url}, headers=auth(employer_token))
    assert (r.status_code == 200) is ok, r.text


# --- 근로자 토큰 무효화 --------------------------------------------------------
def test_reissued_code_invalidates_existing_worker_token(client, employer_token):
    w = _create_worker(client, employer_token).json()
    try:
        tok = client.post("/api/auth/worker-login", json={"access_code": w["access_code"]}).json()["token"]
        assert client.get("/api/worker/me/today", headers=auth(tok)).status_code == 200
        client.post(f"/api/workers/{w['id']}/access-code", headers=auth(employer_token))
        r = client.get("/api/worker/me/today", headers=auth(tok))
        assert r.status_code == 401
        assert "접속 코드가 바뀌었습니다" in r.json()["detail"]
    finally:
        _cleanup(client, employer_token, w["id"])


def test_deleted_worker_token_is_rejected(client, employer_token):
    w = _create_worker(client, employer_token).json()
    tok = client.post("/api/auth/worker-login", json={"access_code": w["access_code"]}).json()["token"]
    _cleanup(client, employer_token, w["id"])
    assert client.get("/api/worker/me/history", headers=auth(tok)).status_code == 401


def test_legacy_worker_token_without_fingerprint_still_works(client):
    # 이 기능 이전에 발급된 토큰(cf 없음)은 만료까지 받아 준다 — 배포 순간 전원 로그아웃되지 않게.
    legacy = auth_mod.make_token("wrk-demo", "worker")
    assert client.get("/api/worker/me/today", headers=auth(legacy)).status_code == 200


def test_worker_token_does_not_expose_code_hash():
    import base64, hashlib, json as _json
    tok = auth_mod.make_token("w", "worker", extra={"cf": auth_mod.code_fingerprint("123456")})
    body = _json.loads(base64.urlsafe_b64decode(tok.split(".")[0] + "=="))
    plain = hashlib.sha256(b"123456").hexdigest()
    assert body["cf"] not in plain and plain[:16] not in body["cf"]
