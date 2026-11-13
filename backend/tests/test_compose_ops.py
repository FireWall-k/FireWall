"""(3-0 ops-1) docker-compose.yml 운영 설정.

지키는 것:
1. backend가 PUBLIC_FRONTEND_URL을 받는다(없어서 운영에서도 기기 연결 QR이 늘 localhost였다). 기본은 예전 로컬 주소.
2. 웹 푸시 VAPID 설정 셋(공개 키·개인 키 파일·연락처)과 개인 키 secret 자리. 공개 키 기본값은 비어 있다(키를 커밋하지 않음).
3. 모든 서비스가 json-file 로그를 10MB × 5개로 돌려 쓴다(기본은 끝없이 쌓여 디스크를 채운다).
4. purge·scheduler가 백업 보존 기간 BACKUP_RETENTION_DAYS(기본 30)를 받는다(3-0 M8).
"""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))


def test_backend_gets_public_frontend_url_defaulting_to_local():
    env = _compose()["services"]["backend"]["environment"]
    assert env["PUBLIC_FRONTEND_URL"] == "${PUBLIC_FRONTEND_URL:-http://localhost:5173}"


def test_vapid_settings_and_empty_secret_slot():
    c = _compose()
    backend = c["services"]["backend"]
    env = backend["environment"]
    assert env["VAPID_PUBLIC_KEY"] == "${VAPID_PUBLIC_KEY:-}"  # 값 없음
    assert env["VAPID_PRIVATE_KEY_FILE"] == "/run/secrets/vapid_private_key"
    assert env["VAPID_SUBJECT"].startswith("${VAPID_SUBJECT:-mailto:")
    assert "vapid_private_key" in backend["secrets"]
    assert c["secrets"]["vapid_private_key"] == {"file": "./secrets/vapid_private.pem"}
    # 개인 키는 backend만 쓴다(다른 서비스에 연결하지 않음).
    for name, svc in c["services"].items():
        if name != "backend":
            assert "vapid_private_key" not in (svc.get("secrets") or []), name


def test_every_service_rotates_json_file_logs():
    services = _compose()["services"]
    assert set(services) >= {"ai_service", "migrate", "purge", "scheduler", "backend", "frontend"}
    for name, svc in services.items():
        assert svc.get("logging") == {"driver": "json-file", "options": {"max-size": "10m", "max-file": "5"}}, name


def test_purge_and_scheduler_get_backup_retention():
    services = _compose()["services"]
    for name in ("purge", "scheduler"):
        assert services[name]["environment"]["BACKUP_RETENTION_DAYS"] == "${BACKUP_RETENTION_DAYS:-30}", name
