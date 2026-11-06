"""보존기간이 지난 데이터 삭제(purge) — `python manage.py purge`로 실행한다.

보존기간(환경변수, 일 단위):
- PERFORMANCE_LOG_RETENTION_DAYS (기본 365): 근로자 단계별 수행 로그(소요시간·다시듣기·막힘).
  코칭·대시보드는 최근 기록만 쓰고, 1년 넘은 수행 기록은 개선 제안에 거의 쓰이지 않는다. 오래 둘수록
  장애 특성을 추정할 수 있는 행동 기록만 쌓이므로 기본 1년으로 자른다.
- ACCESS_AUDIT_RETENTION_DAYS (기본 730): 접근 감사 로그. 「개인정보의 안전성 확보조치 기준」
  (개인정보보호위원회 고시) 제8조는 접속기록을 1년 이상, 5만 명 이상 처리하거나 고유식별정보·민감정보를
  처리하는 경우 2년 이상 보관하도록 한다. 발달장애 관련 정보는 건강(민감)정보에 해당할 수 있어 2년을 기본으로 한다.
  이보다 짧게 설정하면 기동은 되지만 법적 최소치를 어길 수 있다(법무 검토 필요).
- TTS 캐시: 어느 단계도 참조하지 않는 mp3는 TTS_ORPHAN_GRACE_HOURS(기본 24) 지나면 지운다. 막 합성돼
  아직 단계 행이 커밋되기 전인 파일(직무 생성 중)을 지우지 않으려고 유예를 둔다.

감사 로그를 지우는 코드는 이 파일에만 있어야 한다(tests/test_privacy.py가 확인한다). Core delete는
models.AccessAuditLog의 ORM 수정·삭제 차단 이벤트를 거치지 않는다 — 그래서 purge만 지울 수 있다.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from database import checkpoint_wal
from models import AccessAuditLog, PerformanceLog, Step
from tts import get_tts_cache_dir


def _positive_days(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        days = int(raw)
    except ValueError:
        raise ValueError(f"{name}는 일 수(정수)여야 합니다: {raw!r}") from None
    if days <= 0:
        # 0이나 음수면 purge가 방금 쌓인 기록까지 전부 지운다. 설정 실수를 데이터 삭제로 만들지 않는다.
        raise ValueError(f"{name}는 1 이상이어야 합니다: {days}")
    return days


def performance_log_retention_days() -> int:
    return _positive_days("PERFORMANCE_LOG_RETENTION_DAYS", 365)


def access_audit_retention_days() -> int:
    return _positive_days("ACCESS_AUDIT_RETENTION_DAYS", 730)


def tts_orphan_grace_hours() -> float:
    return float(os.getenv("TTS_ORPHAN_GRACE_HOURS", "24"))


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _referenced_tts_files(db: Session) -> set[str]:
    # tts_audio_url은 "<PUBLIC_BACKEND_URL>/api/tts/<hash>.mp3". 서버 주소가 바뀌었어도 파일명으로 비교한다.
    urls = db.scalars(select(Step.tts_audio_url).where(Step.tts_audio_url.is_not(None))).all()
    return {u.rsplit("/", 1)[-1] for u in urls if u}


def orphan_tts_files(db: Session, grace_hours: float | None = None) -> list[Path]:
    grace = tts_orphan_grace_hours() if grace_hours is None else grace_hours
    cutoff = time.time() - grace * 3600
    referenced = _referenced_tts_files(db)
    out = []
    for path in get_tts_cache_dir().glob("*.mp3"):
        if path.name in referenced:
            continue
        try:
            if path.stat().st_mtime > cutoff:
                continue
        except FileNotFoundError:
            continue
        out.append(path)
    return out


def purge(db: Session, *, dry_run: bool = False, now: datetime | None = None) -> dict:
    """보존기간이 지난 수행 로그·접근 감사 로그와 미참조 TTS 파일을 지운다. 지운(지울) 개수를 돌려준다."""
    now = now or _utcnow_naive()
    log_cutoff = now - timedelta(days=performance_log_retention_days())
    audit_cutoff = now - timedelta(days=access_audit_retention_days())

    log_filter = PerformanceLog.completed_at < log_cutoff
    audit_filter = AccessAuditLog.at < audit_cutoff
    report = {
        "performance_logs": db.scalar(select(func.count()).select_from(PerformanceLog).where(log_filter)) or 0,
        "access_audit_logs": db.scalar(select(func.count()).select_from(AccessAuditLog).where(audit_filter)) or 0,
    }
    orphans = orphan_tts_files(db)
    report["tts_files"] = len(orphans)
    report["dry_run"] = dry_run
    if dry_run:
        return report

    db.execute(delete(PerformanceLog).where(log_filter))
    db.execute(delete(AccessAuditLog).where(audit_filter))
    db.commit()
    # 지운 기록이 WAL 파일에 남아 있지 않게 바로 체크포인트한다(database.checkpoint_wal 참고).
    checkpoint_wal(db)
    for path in orphans:
        path.unlink(missing_ok=True)
    return report
