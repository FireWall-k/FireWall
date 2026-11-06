"""비밀값 로더(secret_env.read_secret)와 OPENAI_API_KEY_FILE 연결 테스트 — Phase 0.5.

backend/secret_env.py와 같은 파일이다(빌드 컨텍스트가 서비스별이라 복사본을 둔다).
"""
import importlib

import pytest

import secret_env


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("FOO_SECRET", "FOO_SECRET_FILE"):
        monkeypatch.delenv(name, raising=False)
    secret_env._warned.clear()


def test_file_wins_and_newline_stripped(tmp_path, monkeypatch):
    f = tmp_path / "foo.txt"
    f.write_bytes(b"from-file\r\n")
    monkeypatch.setenv("FOO_SECRET", "from-env")
    monkeypatch.setenv("FOO_SECRET_FILE", str(f))
    assert secret_env.read_secret("FOO_SECRET") == "from-file"


def test_unset_keeps_previous_behavior(monkeypatch):
    assert secret_env.read_secret("FOO_SECRET", "dflt") == "dflt"
    monkeypatch.setenv("FOO_SECRET", "from-env")
    assert secret_env.read_secret("FOO_SECRET") == "from-env"


def test_empty_file_falls_back(tmp_path, monkeypatch):
    f = tmp_path / "foo.txt"
    f.write_text("", encoding="utf-8")
    monkeypatch.setenv("FOO_SECRET_FILE", str(f))
    monkeypatch.setenv("FOO_SECRET", "from-env")
    assert secret_env.read_secret("FOO_SECRET") == "from-env"


def test_missing_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("FOO_SECRET_FILE", str(tmp_path / "nope.txt"))
    with pytest.raises(RuntimeError, match="FOO_SECRET_FILE"):
        secret_env.read_secret("FOO_SECRET")


def test_llm_reads_openai_key_file(tmp_path, monkeypatch):
    import llm

    f = tmp_path / "openai_api_key.txt"
    f.write_text("sk-from-file\n", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY_FILE", str(f))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-env")
    try:
        importlib.reload(llm)
        assert llm.OPENAI_API_KEY == "sk-from-file"
        assert llm.llm_available()
    finally:
        monkeypatch.undo()
        importlib.reload(llm)
