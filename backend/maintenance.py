"""보존기간 삭제 스케줄(`manage.py schedule`)과 마지막 성공 기록.

왜: 예전에는 `manage.py purge`를 운영자가 호스트 crontab에 직접 등록해야 했다. 등록을 잊거나 서버를 옮기며
빠뜨리면 보존기간이 지난 수행 로그·접근 감사 로그와 고아 사진·TTS가 무기한 남는데, 그 사실이 어디에도
드러나지 않았다(docs/privacy/data-map.md "삭제 스케줄"). 그래서
- compose 기본 프로필의 `scheduler` 서비스(backend와 같은 이미지)가 이 루프를 돌린다. 한 개만 띄운다 —
  요청을 받는 backend 프로세스 안에 두지 않는 이유는 backend를 여러 개 띄우면 같은 삭제가 겹치기 때문이다.
- 성공할 때마다 마지막 성공 시각을 상태 파일(PURGE_STATUS_FILE, 공유 볼륨)에 남기고, backend `/health`가
  경과 시간과 `stale`(주기의 1.5배 초과)을 보여 준다. 모니터링은 이 값을 보면 된다.

상태 파일은 인증 없는 /health로 요약이 나가므로 개수·시각·오류 종류만 남긴다(오류 메시지·경로는 남기지 않는다 —
메시지에 DB 경로나 SQL 조각이 섞일 수 있다. 자세한 내용은 scheduler 컨테이너 로그에 남는다).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger("jobcard.maintenance")

_REPORT_KEYS = ("performance_logs", "access_audit_logs", "media_records", "photo_files", "tts_files",
                "backup_files", "wal_checkpointed")


def status_path() -> Path:
    return Path(os.getenv("PURGE_STATUS_FILE", "./data/maintenance/purge_status.json"))


def default_interval_hours() -> float:
    """실행 주기(시간). 기본 24 = 하루 한 번. 마지막 '성공' 시각부터 잰다(재시작해도 다시 지우지 않게)."""
    return float(os.getenv("PURGE_INTERVAL_HOURS", "24"))


def default_retry_minutes() -> float:
    """실패 뒤 다시 해 보기까지(분). 주기 전체를 기다리면 하루씩 밀린다."""
    return float(os.getenv("PURGE_RETRY_MINUTES", "60"))


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def read_status() -> dict:
    """상태 파일 내용. 없거나 깨졌으면 빈 dict — /health가 이 때문에 실패하면 안 된다."""
    try:
        data = json.loads(status_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_status(status: dict) -> None:
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # 임시 파일에 쓰고 이름을 바꾼다 — backend가 반쯤 쓴 JSON을 읽지 않게.
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _parse(ts) -> datetime | None:
    try:
        dt = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run_purge_once(now: datetime | None = None) -> dict | None:
    """purge(보존기간 삭제 + 고아 사진·TTS 정리)를 한 번 돌리고 상태를 남긴다. 실패하면 None.

    예외를 밖으로 던지지 않는다 — 루프가 죽으면(restart: unless-stopped가 다시 띄우더라도) 실패 기록이 남지 않는다.
    """
    # 지연 import: /health가 이 모듈의 health_info()만 쓸 때 DB·미디어 모듈을 끌어오지 않게.
    import db_migrate
    import retention
    from database import SessionLocal

    try:
        db_migrate.ensure_schema_ready()
        with SessionLocal() as db:
            report = retention.purge(db)
    except Exception as exc:  # noqa: BLE001 - 어떤 실패든 기록하고 다음 시도로 넘어간다
        logger.exception("보존기간 삭제(purge) 실패")
        record_failure(exc, now)
        return None
    record_success(report, now)
    return report


def record_success(report: dict, now: datetime | None = None) -> None:
    """purge 성공을 남긴다. 수동 `manage.py purge`(dry-run 아님)도 부른다 — 손으로 돌린 것도 '최근에 지웠다'다."""
    status = read_status()
    status.update({
        "last_success_at": (now or _now_utc()).isoformat(),
        "last_error": None,
        "last_report": {k: report[k] for k in _REPORT_KEYS if k in report},
    })
    _write_status(status)


def record_failure(exc: BaseException, now: datetime | None = None) -> None:
    """실패를 남긴다. 마지막 성공 시각은 덮지 않는다(그래야 /health가 '언제부터 밀렸는지'를 보여 준다)."""
    status = read_status()
    status.update({"last_failure_at": (now or _now_utc()).isoformat(), "last_error": type(exc).__name__})
    _write_status(status)


def seconds_until_due(status: dict, now: datetime, interval_h: float) -> float:
    last = _parse(status.get("last_success_at"))
    if last is None:
        return 0.0
    return max(0.0, interval_h * 3600 - (now - last).total_seconds())


def loop(stop, *, now_fn: Callable[[], datetime] = _now_utc, interval_hours: float | None = None,
         retry_minutes: float | None = None, on_report: Callable[[dict], None] | None = None) -> None:
    """stop(threading.Event 같은 것)이 설정될 때까지 주기마다 purge를 돌린다.

    time.sleep 대신 stop.wait(timeout)을 쓴다 — SIGTERM(docker stop)을 받으면 대기 중에도 바로 끝난다.
    """
    interval_h = default_interval_hours() if interval_hours is None else interval_hours
    retry_m = default_retry_minutes() if retry_minutes is None else retry_minutes
    while not stop.is_set():
        wait = seconds_until_due(read_status(), now_fn(), interval_h)
        if wait > 0:
            stop.wait(wait)
            continue
        report = run_purge_once(now=now_fn())
        if report is None:
            stop.wait(retry_m * 60)
            continue
        if on_report is not None:
            on_report(report)
        stop.wait(interval_h * 3600)


def health_info(now: datetime | None = None) -> dict:
    """/health에 싣는 요약. 한 번도 성공하지 않았으면 last_success_at=None, stale=True."""
    status = read_status()
    last = _parse(status.get("last_success_at"))
    out = {
        "last_success_at": last.isoformat() if last else None,
        "age_hours": None,
        "stale": True,
        "last_error": status.get("last_error"),
    }
    if last is not None:
        age = ((now or _now_utc()) - last).total_seconds() / 3600
        out["age_hours"] = round(age, 2)
        try:
            out["stale"] = age > default_interval_hours() * 1.5
        except ValueError:
            out["stale"] = age > 36
    return out
