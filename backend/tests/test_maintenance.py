"""보존기간 삭제 스케줄(maintenance.py, manage.py schedule) 테스트 (Phase 0.2·0.3 후속).

예전에는 purge를 운영자가 호스트 crontab에 직접 등록해야 했다. 등록을 잊으면 보존기간이 지난 수행 로그·
접근 감사 로그·고아 사진이 무기한 남는데, 아무 데서도 드러나지 않았다. 지키는 것:
1. compose 기본 프로필에 하루 한 번 purge(+고아 사진·TTS 정리)를 도는 scheduler 서비스가 있다.
2. 성공하면 마지막 성공 시각을 상태 파일에 남기고, backend /health가 경과 시간을 보여 준다.
3. 실패는 마지막 성공 시각을 덮지 않는다. 오류 내용(경로·SQL 등)은 남기지 않고 종류만 남긴다.
4. 루프는 마지막 성공 후 주기가 지났을 때만 돈다(재시작마다 다시 지우지 않는다), 실패하면 짧게 쉬고 다시 한다.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import maintenance
import retention

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def status_file(tmp_path, monkeypatch) -> Path:
    path = tmp_path / "maintenance" / "purge_status.json"
    monkeypatch.setenv("PURGE_STATUS_FILE", str(path))
    return path


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def test_successful_run_records_last_success(status_file, client):
    now = _utc(2026, 11, 7, 3, 15)
    report = maintenance.run_purge_once(now=now)
    assert report is not None and "performance_logs" in report
    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["last_success_at"] == "2026-11-07T03:15:00+00:00"
    assert status["last_error"] is None
    assert set(status["last_report"]) >= {"performance_logs", "access_audit_logs", "media_records"}


def test_failure_keeps_last_success_and_hides_details(status_file, client, monkeypatch):
    maintenance.run_purge_once(now=_utc(2026, 11, 6, 3, 0))

    def boom(*_a, **_k):
        raise RuntimeError("/app/data/jobcard.db: secret-path detail")

    monkeypatch.setattr(retention, "purge", boom)
    assert maintenance.run_purge_once(now=_utc(2026, 11, 7, 3, 0)) is None
    raw = status_file.read_text(encoding="utf-8")
    status = json.loads(raw)
    assert status["last_success_at"] == "2026-11-06T03:00:00+00:00"
    assert status["last_failure_at"] == "2026-11-07T03:00:00+00:00"
    assert status["last_error"] == "RuntimeError"
    assert "secret-path" not in raw  # 오류 메시지는 /health로 공개되는 파일에 남기지 않는다


def test_health_reports_elapsed_time(status_file, client, monkeypatch):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # 스케줄러가 한 번도 안 돌았으면 null — "몰래 안 돌고 있음"을 숨기지 않는다.
    assert body["purge"]["last_success_at"] is None and body["purge"]["stale"] is True

    maintenance.run_purge_once(now=datetime.now(timezone.utc) - timedelta(hours=5))
    body = client.get("/health").json()
    assert 4.9 < body["purge"]["age_hours"] < 5.2
    assert body["purge"]["stale"] is False

    maintenance.run_purge_once(now=datetime.now(timezone.utc) - timedelta(hours=60))
    body = client.get("/health").json()
    assert body["purge"]["stale"] is True  # 주기(24h)의 1.5배를 넘겼다


def test_corrupt_status_file_does_not_break_health(status_file, client):
    status_file.parent.mkdir(parents=True, exist_ok=True)
    status_file.write_text("{not json", encoding="utf-8")
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["purge"]["last_success_at"] is None


class _FakeStop:
    """stop.wait(timeout)을 기록하고 n번째 대기에서 멈춘다(실제로 자지 않는다)."""

    def __init__(self, stop_after: int):
        self.waits: list[float] = []
        self._stop_after = stop_after
        self._set = False

    def is_set(self) -> bool:
        return self._set

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        if len(self.waits) >= self._stop_after:
            self._set = True
        return self._set


def test_loop_runs_when_due_then_waits_interval(status_file, monkeypatch):
    clock = {"now": _utc(2026, 11, 7, 3, 0)}
    runs = []

    def fake_run(now=None):
        runs.append(clock["now"])
        maintenance._write_status({"last_success_at": clock["now"].isoformat(), "last_error": None})
        return {}

    monkeypatch.setattr(maintenance, "run_purge_once", fake_run)
    stop = _FakeStop(stop_after=1)
    maintenance.loop(stop, now_fn=lambda: clock["now"], interval_hours=24, retry_minutes=60)
    assert runs == [_utc(2026, 11, 7, 3, 0)]  # 상태 파일이 없으니 바로 한 번
    assert stop.waits == [pytest.approx(24 * 3600)]

    # 재시작: 마지막 성공이 10시간 전이면 바로 지우지 않고 남은 14시간을 기다린다.
    clock["now"] = _utc(2026, 11, 7, 13, 0)
    stop = _FakeStop(stop_after=1)
    maintenance.loop(stop, now_fn=lambda: clock["now"], interval_hours=24, retry_minutes=60)
    assert len(runs) == 1
    assert stop.waits == [pytest.approx(14 * 3600)]


def test_loop_retries_sooner_after_failure(status_file, monkeypatch):
    monkeypatch.setattr(maintenance, "run_purge_once", lambda now=None: None)
    stop = _FakeStop(stop_after=1)
    maintenance.loop(stop, now_fn=lambda: _utc(2026, 11, 7, 3, 0), interval_hours=24, retry_minutes=60)
    assert stop.waits == [pytest.approx(3600)]


def test_manage_schedule_runs_loop_with_stop_event(status_file, client, monkeypatch):
    import manage

    calls = []
    monkeypatch.setattr(maintenance, "loop", lambda ev, **kw: calls.append(ev) or None)
    manage.main(["schedule"])
    assert len(calls) == 1 and isinstance(calls[0], threading.Event)


def test_manual_purge_records_success_but_dry_run_does_not(status_file, client):
    import manage

    manage.main(["purge", "--dry-run"])
    assert not status_file.exists()
    manage.main(["purge"])
    assert json.loads(status_file.read_text(encoding="utf-8"))["last_success_at"]


def test_compose_runs_scheduler_by_default():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    svc = compose["services"]["scheduler"]
    assert "profiles" not in svc  # 기본 프로필: docker compose up이면 같이 뜬다
    assert svc["command"] == ["python", "manage.py", "schedule"]
    assert svc["image"] == compose["services"]["backend"]["image"] and "build" not in svc
    assert svc["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
    # backend가 같은 상태 파일을 같은 볼륨에서 읽어야 /health에 보인다.
    status = svc["environment"]["PURGE_STATUS_FILE"]
    assert compose["services"]["backend"]["environment"]["PURGE_STATUS_FILE"] == status
    assert status.startswith("/app/data/")
