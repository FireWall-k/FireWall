"""비밀값 로더(secret_env.read_secret) 테스트 — Phase 0.5.

compose는 비밀값을 /run/secrets/<이름> 파일로 넘기고 앱은 <이름>_FILE 환경변수로 그 경로를 받는다.
파일 값이 환경변수 직접 값보다 우선하고, 파일이 비어 있으면(init-secrets가 만든 빈 파일) 예전처럼
환경변수/기본값으로 동작해야 한다.
"""
import logging

import pytest

import auth
import secret_env


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("FOO_SECRET", "FOO_SECRET_FILE"):
        monkeypatch.delenv(name, raising=False)
    secret_env._warned.clear()


def test_file_wins_over_direct_env(tmp_path, monkeypatch):
    f = tmp_path / "foo.txt"
    f.write_text("from-file", encoding="utf-8")
    monkeypatch.setenv("FOO_SECRET", "from-env")
    monkeypatch.setenv("FOO_SECRET_FILE", str(f))
    assert secret_env.read_secret("FOO_SECRET") == "from-file"


@pytest.mark.parametrize("raw", ["abc123\n", "abc123\r\n", "abc123\n\n"])
def test_trailing_newlines_stripped(tmp_path, monkeypatch, raw):
    # echo/메모장으로 만든 파일 끝 개행이 키에 섞이면 HMAC 키·Bearer 헤더가 조용히 달라진다.
    f = tmp_path / "foo.txt"
    f.write_bytes(raw.encode("utf-8"))
    monkeypatch.setenv("FOO_SECRET_FILE", str(f))
    assert secret_env.read_secret("FOO_SECRET") == "abc123"


def test_utf8_bom_stripped(tmp_path, monkeypatch):
    # Windows 메모장/PowerShell 5의 UTF-8 저장은 BOM을 붙인다.
    f = tmp_path / "foo.txt"
    f.write_bytes("﻿abc123\n".encode("utf-8"))
    monkeypatch.setenv("FOO_SECRET_FILE", str(f))
    assert secret_env.read_secret("FOO_SECRET") == "abc123"


def test_inner_content_preserved(tmp_path, monkeypatch):
    f = tmp_path / "foo.txt"
    f.write_text("a b\tc\n", encoding="utf-8")
    monkeypatch.setenv("FOO_SECRET_FILE", str(f))
    assert secret_env.read_secret("FOO_SECRET") == "a b\tc"


def test_unset_keeps_previous_behavior(monkeypatch):
    assert secret_env.read_secret("FOO_SECRET") == ""
    assert secret_env.read_secret("FOO_SECRET", "dflt") == "dflt"
    monkeypatch.setenv("FOO_SECRET", "from-env")
    assert secret_env.read_secret("FOO_SECRET") == "from-env"


def test_empty_file_falls_back_to_env_with_warning(tmp_path, monkeypatch, caplog):
    f = tmp_path / "foo.txt"
    f.write_text("\n", encoding="utf-8")
    monkeypatch.setenv("FOO_SECRET_FILE", str(f))
    assert secret_env.read_secret("FOO_SECRET", "dflt") == "dflt"
    monkeypatch.setenv("FOO_SECRET", "from-env")
    with caplog.at_level(logging.WARNING, logger="jobcard.secrets"):
        assert secret_env.read_secret("FOO_SECRET") == "from-env"
    assert "FOO_SECRET" in caplog.text
    assert "from-env" not in caplog.text  # 경고에 값이 새면 안 된다


def test_missing_file_fails_closed(tmp_path, monkeypatch):
    # 경로를 줬는데 파일이 없으면 오타·마운트 누락이다. 조용히 기본(개발용) 키로 떨어지면 안 된다.
    monkeypatch.setenv("FOO_SECRET_FILE", str(tmp_path / "nope.txt"))
    monkeypatch.setenv("FOO_SECRET", "from-env")
    with pytest.raises(RuntimeError, match="FOO_SECRET_FILE"):
        secret_env.read_secret("FOO_SECRET")


def test_auth_secret_reads_file(tmp_path, monkeypatch):
    f = tmp_path / "jobcard_secret.txt"
    f.write_text("k" * 48 + "\n", encoding="utf-8")
    monkeypatch.setenv("JOBCARD_SECRET_FILE", str(f))
    monkeypatch.setenv("JOBCARD_SECRET", "test-secret")
    assert auth._secret() == "k" * 48


def test_auth_prod_guard_applies_to_file_value(tmp_path, monkeypatch):
    f = tmp_path / "jobcard_secret.txt"
    f.write_text("too-short\n", encoding="utf-8")
    monkeypatch.setenv("JOBCARD_SECRET_FILE", str(f))
    monkeypatch.setenv("JOBCARD_ENV", "prod")
    with pytest.raises(RuntimeError, match="JOBCARD_SECRET"):
        auth._secret()
