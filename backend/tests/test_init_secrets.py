"""scripts/init-secrets.sh(.ps1)의 .env → secrets/ 옮기기 (Phase 0.5 보완).

compose가 OPENAI_API_KEY를 환경변수로 넘기지 않게 바꿨으므로, .env에 키를 두던 설치본은 이 스크립트로
secrets/openai_api_key.txt를 만들어야 한다. 지키는 것:
1. .env 값이 있고 파일이 없거나 비었으면(공백·개행만 포함) 값을 그대로 옮긴다(따옴표·export·CR 제거).
2. 값은 표준출력·표준오류에 절대 나오지 않는다.
3. 이미 값이 있는 파일은 덮어쓰지 않는다(운영 키를 옛 .env 값으로 되돌리지 않게).
4. JOBCARD_SECRET도 새로 만들지 않고 기존 값을 옮긴다.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FAKE_OPENAI = "sk-test-0000000000000000000000000000fake"
FAKE_SECRET = "test-jobcard-secret-value-not-real-0123456789"


def _env_file(tmp_path: Path) -> Path:
    env = tmp_path / ".env"
    # CRLF·따옴표·export 접두어·중복 키(마지막 값이 이김)를 섞어 실제 .env 모양을 흉내 낸다.
    env.write_bytes((
        "# 주석\r\n"
        "OPENAI_API_KEY=old-value\r\n"
        f'export OPENAI_API_KEY="{FAKE_OPENAI}"\r\n'
        f"JOBCARD_SECRET='{FAKE_SECRET}'\r\n"
        "OPENAI_MODEL=gpt-4o-mini\r\n"
    ).encode("utf-8"))
    return env


def _run_sh(tmp_path: Path, secrets_dir: Path, env_file: Path) -> subprocess.CompletedProcess:
    sh = shutil.which("sh")
    if sh is None:
        pytest.skip("sh 없음(이 스크립트는 리눅스 서버·Git Bash용)")
    env = {**os.environ, "SECRETS_DIR": str(secrets_dir), "ENV_FILE": str(env_file)}
    return subprocess.run([sh, str(ROOT / "scripts" / "init-secrets.sh")], env=env,
                          capture_output=True, text=True, encoding="utf-8", check=True)


def _assert_no_values(out: str) -> None:
    assert FAKE_OPENAI not in out and FAKE_SECRET not in out and "old-value" not in out


def test_sh_moves_env_values_without_printing(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "openai_api_key.txt").write_text(" \n\n", encoding="utf-8")  # 공백·개행만 = 빈 파일
    proc = _run_sh(tmp_path, secrets_dir, _env_file(tmp_path))
    _assert_no_values(proc.stdout + proc.stderr)
    assert (secrets_dir / "openai_api_key.txt").read_text(encoding="utf-8") == FAKE_OPENAI
    assert (secrets_dir / "jobcard_secret.txt").read_text(encoding="utf-8") == FAKE_SECRET
    assert (secrets_dir / "google-tts.json").read_bytes() == b""
    assert (secrets_dir / "vapid_private.pem").read_bytes() == b""  # (3-0) 웹 푸시 개인 키 자리
    assert "옮김" in proc.stdout


def test_sh_never_overwrites_existing_value(tmp_path):
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    (secrets_dir / "openai_api_key.txt").write_text("sk-rotated-new-key", encoding="utf-8")
    proc = _run_sh(tmp_path, secrets_dir, _env_file(tmp_path))
    _assert_no_values(proc.stdout + proc.stderr)
    assert (secrets_dir / "openai_api_key.txt").read_text(encoding="utf-8") == "sk-rotated-new-key"


def test_sh_without_env_file_creates_empty_files(tmp_path):
    secrets_dir = tmp_path / "secrets"
    _run_sh(tmp_path, secrets_dir, tmp_path / "missing.env")
    for name in ("openai_api_key.txt", "jobcard_secret.txt", "google-tts.json", "vapid_private.pem"):
        assert (secrets_dir / name).read_bytes() == b""


def test_ps1_moves_env_values_without_printing(tmp_path):
    ps = shutil.which("pwsh") or shutil.which("powershell")
    if ps is None:
        pytest.skip("PowerShell 없음(Windows용 스크립트)")
    secrets_dir = tmp_path / "secrets"
    proc = subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "init-secrets.ps1"),
         "-SecretsDir", str(secrets_dir), "-EnvFile", str(_env_file(tmp_path))],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    _assert_no_values(proc.stdout + proc.stderr)
    assert (secrets_dir / "openai_api_key.txt").read_bytes() == FAKE_OPENAI.encode()
    assert (secrets_dir / "jobcard_secret.txt").read_bytes() == FAKE_SECRET.encode()
    assert (secrets_dir / "google-tts.json").read_bytes() == b""
    assert (secrets_dir / "vapid_private.pem").read_bytes() == b""


def test_sh_strips_inline_comment_like_compose(tmp_path):
    """compose의 dotenv는 따옴표 없는 값에서 ' #' 뒤를 주석으로 버린다. 스크립트가 주석까지 파일에 옮기면
    파일 값(우선)이 지금까지 backend가 쓰던 키와 달라져 토큰·접속 코드 해시·서명 URL이 전부 무효가 된다."""
    secrets_dir = tmp_path / "secrets"
    secrets_dir.mkdir()
    env_file = tmp_path / ".env"
    env_file.write_bytes((
        "JOBCARD_SECRET=abc def # 운영 키\r\n"
        'OPENAI_API_KEY="sk-test#notcomment" # 따옴표 안의 #은 값\r\n'
    ).encode("utf-8"))
    _run_sh(tmp_path, secrets_dir, env_file)
    assert (secrets_dir / "jobcard_secret.txt").read_text(encoding="utf-8") == "abc def"
    assert (secrets_dir / "openai_api_key.txt").read_text(encoding="utf-8") == "sk-test#notcomment"


def test_ps1_strips_inline_comment_like_compose(tmp_path):
    """init-secrets.sh와 같은 규칙(test_sh_strips_inline_comment_like_compose 참고)을 Windows 스크립트도 따른다."""
    ps = shutil.which("pwsh") or shutil.which("powershell")
    if ps is None:
        pytest.skip("PowerShell 없음(Windows용 스크립트)")
    secrets_dir = tmp_path / "secrets"
    env_file = tmp_path / ".env"
    env_file.write_bytes((
        "JOBCARD_SECRET=abc def # 운영 키\r\n"
        'OPENAI_API_KEY="sk-test#notcomment" # 따옴표 안의 #은 값\r\n'
    ).encode("utf-8"))
    subprocess.run(
        [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts" / "init-secrets.ps1"),
         "-SecretsDir", str(secrets_dir), "-EnvFile", str(env_file)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", check=True)
    assert (secrets_dir / "jobcard_secret.txt").read_text(encoding="utf-8") == "abc def"
    assert (secrets_dir / "openai_api_key.txt").read_text(encoding="utf-8") == "sk-test#notcomment"
