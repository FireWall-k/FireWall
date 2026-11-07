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


# --- 비밀값은 프로세스 기동 시 한 번만 읽는다(Phase 0.5 보완) ----------------------

def test_auth_secret_is_read_once_per_process(tmp_path, monkeypatch):
    """예전 _secret()은 토큰 검증·접속 코드 해시·서명 URL마다 비밀값 파일을 다시 열었다(요청마다 디스크 I/O,
    파일이 잠깐 비거나 바뀌는 순간 요청마다 다른 키). 이제 처음 한 번 읽어 캐시한다."""
    f = tmp_path / "jobcard_secret.txt"
    f.write_text("a" * 48, encoding="utf-8")
    monkeypatch.setenv("JOBCARD_SECRET_FILE", str(f))
    calls = []
    real = auth.read_secret
    monkeypatch.setattr(auth, "read_secret", lambda *a, **k: calls.append(a) or real(*a, **k))
    auth.reset_secret_cache()
    for _ in range(5):
        assert auth._secret() == "a" * 48
    auth.make_token("e1", "employer")
    assert len(calls) == 1


def test_secret_rotation_needs_restart_or_reset(tmp_path, monkeypatch):
    """키 교체는 재시작으로 반영된다(실행 중에 파일만 바꾸면 이전 키를 계속 쓴다). 테스트는 reset 훅으로 다시 읽는다."""
    f = tmp_path / "jobcard_secret.txt"
    f.write_text("a" * 48, encoding="utf-8")
    monkeypatch.setenv("JOBCARD_SECRET_FILE", str(f))
    auth.reset_secret_cache()
    assert auth._secret() == "a" * 48
    f.write_text("b" * 48, encoding="utf-8")
    assert auth._secret() == "a" * 48
    auth.reset_secret_cache()
    assert auth._secret() == "b" * 48


def test_weak_prod_secret_is_not_cached(tmp_path, monkeypatch):
    """운영 가드에 걸린 값은 캐시하지 않는다 — 다음 호출도 다시 실패해야 한다(약한 키로 한 번이라도 서명하지 않게)."""
    monkeypatch.setenv("JOBCARD_ENV", "prod")
    monkeypatch.setenv("JOBCARD_SECRET", "too-short")
    auth.reset_secret_cache()
    for _ in range(2):
        with pytest.raises(RuntimeError, match="JOBCARD_SECRET"):
            auth._secret()


def test_lifespan_loads_secret_at_startup(monkeypatch):
    """개발 모드에서도 기동 시 한 번 읽어 둔다(첫 요청이 파일 I/O·오류를 떠안지 않게)."""
    calls = []
    real = auth.read_secret
    monkeypatch.setattr(auth, "read_secret", lambda *a, **k: calls.append(a) or real(*a, **k))
    auth.reset_secret_cache()
    auth.check_production_config()
    assert len(calls) == 1
