"""데모 로그인 미리 채우기(GET /api/auth/demo).

로그인 화면이 데모 계정을 미리 채워 '로그인'만 누르면 들어가게 한다. 지켜야 할 것:
- 운영(JOBCARD_ENV=prod)이나 DEMO_SEED=0이면 아무것도 알려 주지 않는다(404).
- 비밀번호·접속 코드는 '저장소에 공개된 기본값이 아직 맞을 때만' 돌려준다. 사업주가 데모 계정
  비밀번호를 바꿨다면 그 값은 이미 비밀이므로, 이 API가 실제 비밀번호를 흘리는 일이 없어야 한다.
- 사업장 코드는 DB의 실제 값을 준다. Alembic 도입 전 설치본은 데모 계정이 DEMO01이 아닌
  무작위 사업장 코드를 받았으므로, 환경변수 기본값을 그대로 주면 근로자 로그인이 틀린다.
"""
import main
from auth import hash_password
from database import SessionLocal
from models import Employer, Worker


def test_demo_credentials_log_in(client):
    r = client.get("/api/auth/demo")
    assert r.status_code == 200
    d = r.json()
    emp = d["employer"]
    assert emp == {"login_id": "demo", "password": "demo1234"}
    assert client.post("/api/auth/login", json=emp).status_code == 200
    wk = d["worker"]
    assert wk["access_code"] == "1234" and wk["workplace_code"]
    r = client.post("/api/auth/worker-login", json=wk)
    assert r.status_code == 200, r.text


def test_demo_workplace_code_comes_from_db(client):
    db = SessionLocal()
    try:
        emp = db.query(Employer).filter(Employer.login_id == "demo").one()
        original = emp.workplace_code
        emp.workplace_code = "HGP2ET"
        db.commit()
        try:
            assert client.get("/api/auth/demo").json()["worker"]["workplace_code"] == "HGP2ET"
        finally:
            emp.workplace_code = original
            db.commit()
    finally:
        db.close()


def test_changed_password_is_never_returned(client):
    db = SessionLocal()
    try:
        emp = db.query(Employer).filter(Employer.login_id == "demo").one()
        original = emp.password_hash
        emp.password_hash = hash_password("real-secret-pw")
        db.commit()
        try:
            d = client.get("/api/auth/demo").json()
            assert d["employer"] is None
            assert "real-secret-pw" not in client.get("/api/auth/demo").text
        finally:
            emp.password_hash = original
            db.commit()
    finally:
        db.close()


def test_changed_worker_code_is_never_returned(client):
    db = SessionLocal()
    try:
        w = db.get(Worker, "wrk-demo")
        original = (w.access_code_hash, w.access_code_hint, w.access_code_length)
        w.set_access_code("987654")
        db.commit()
        try:
            d = client.get("/api/auth/demo").json()
            assert d["worker"] is None
            assert "987654" not in client.get("/api/auth/demo").text
        finally:
            w.access_code_hash, w.access_code_hint, w.access_code_length = original
            db.commit()
    finally:
        db.close()


def test_hidden_in_production(client, monkeypatch):
    monkeypatch.setenv("JOBCARD_ENV", "prod")
    monkeypatch.setenv("DEMO_SEED", "1")  # prod에서는 DEMO_SEED를 켜도 알려 주지 않는다
    assert client.get("/api/auth/demo").status_code == 404


def test_hidden_when_demo_seed_off(client, monkeypatch):
    monkeypatch.setenv("DEMO_SEED", "0")
    assert client.get("/api/auth/demo").status_code == 404


def test_empty_demo_seed_means_default(client, monkeypatch):
    """compose의 "${DEMO_SEED:-}"는 .env에 값이 없으면 빈 문자열을 넘긴다. 빈 값을 끔으로 읽으면
    compose로 새로 설치한 개발 서버에 데모 계정이 생기지 않는다(실제로 그랬다)."""
    monkeypatch.setenv("DEMO_SEED", "")
    assert main._demo_seed_enabled() is True
    assert client.get("/api/auth/demo").status_code == 200
    monkeypatch.setenv("JOBCARD_ENV", "prod")
    assert main._demo_seed_enabled() is False
