"""운영 관리 명령(manage.py) 테스트 — 운영에서 사업주 계정을 만드는 유일한 경로다."""
import io

import pytest

import manage


def _run(monkeypatch, argv, password):
    monkeypatch.setattr("sys.stdin", io.StringIO(password + "\n"))
    manage.main(argv + ["--password-stdin"])


def test_create_employer_then_login(client, monkeypatch):
    _run(monkeypatch, ["create-employer", "--login", "itda-admin", "--org", "잇다"], "correct-horse-1")
    r = client.post("/api/auth/login", json={"login_id": "itda-admin", "password": "correct-horse-1"})
    assert r.status_code == 200, r.text
    assert r.json()["display_name"] == "잇다"


def test_duplicate_login_is_rejected(client, monkeypatch):
    _run(monkeypatch, ["create-employer", "--login", "dup-admin"], "correct-horse-1")
    with pytest.raises(SystemExit):
        _run(monkeypatch, ["create-employer", "--login", "dup-admin"], "correct-horse-2")


def test_short_password_is_rejected(monkeypatch):
    with pytest.raises(SystemExit):
        _run(monkeypatch, ["create-employer", "--login", "short-pw"], "short")


def test_set_password(client, monkeypatch):
    _run(monkeypatch, ["create-employer", "--login", "pw-admin"], "correct-horse-1")
    _run(monkeypatch, ["set-password", "--login", "pw-admin"], "battery-staple-2")
    ok = client.post("/api/auth/login", json={"login_id": "pw-admin", "password": "battery-staple-2"})
    assert ok.status_code == 200


def test_create_employer_prints_workplace_code(client, monkeypatch, capsys):
    """근로자 로그인에 사업장 코드가 필요하므로, 계정을 만들면서 바로 알려 줘야 한다."""
    _run(monkeypatch, ["create-employer", "--login", "wp-admin"], "correct-horse-1")
    out = capsys.readouterr().out
    tok = client.post("/api/auth/login", json={"login_id": "wp-admin", "password": "correct-horse-1"})
    wp = client.get("/api/workplace", headers={"Authorization": f"Bearer {tok.json()['token']}"})
    assert f"사업장 코드: {wp.json()['workplace_code']}" in out


def test_workplace_code_collision_retries(client, monkeypatch, capsys):
    """사업장 코드는 전역 unique다. 무작위 코드가 기존 사업장(데모 DEMO01)과 겹치면 500 대신 다시 뽑는다."""
    codes = iter(["DEMO01", "ZZZZZ9"])
    monkeypatch.setattr(manage, "new_workplace_code", lambda: next(codes))
    _run(monkeypatch, ["create-employer", "--login", "wp-collide"], "correct-horse-1")
    assert "사업장 코드: ZZZZZ9" in capsys.readouterr().out
    tok = client.post("/api/auth/login", json={"login_id": "wp-collide", "password": "correct-horse-1"})
    assert tok.status_code == 200
