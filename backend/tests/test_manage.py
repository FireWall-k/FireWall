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
