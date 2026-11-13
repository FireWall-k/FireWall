"""보존기간이 지난 데이터 삭제(purge) — `python manage.py purge`로 실행한다.

보존기간(환경변수, 일 단위):
- PERFORMANCE_LOG_RETENTION_DAYS (기본 365): 근로자 단계별 수행 로그(소요시간·다시듣기·막힘)와
  도움 요청(help_requests, 0006)과 화면 측정 이벤트(client_events, 0009). 도움 요청·측정 이벤트도
  "언제 어느 단계에서 막혔는지·다시 들었는지"라는 같은 종류의 행동 기록이다. 측정 이벤트만 남기면 지운
  수행 로그·도움 요청을 시각과 단계로 다시 이어 볼 수 있으므로 같은 기한에 함께 지운다.
  코칭·대시보드는 최근 기록만 쓰고, 1년 넘은 수행 기록은 개선 제안에 거의 쓰이지 않는다. 오래 둘수록
  장애 특성을 추정할 수 있는 행동 기록만 쌓이므로 기본 1년으로 자른다.
- ACCESS_AUDIT_RETENTION_DAYS (기본 730): 접근 감사 로그. 「개인정보의 안전성 확보조치 기준」
  (개인정보보호위원회 고시) 제8조는 접속기록을 1년 이상, 5만 명 이상 처리하거나 고유식별정보·민감정보를
  처리하는 경우 2년 이상 보관하도록 한다. 발달장애 관련 정보는 건강(민감)정보에 해당할 수 있어 2년을 기본으로 한다.
  이보다 짧게 설정하면 기동은 되지만 법적 최소치를 어길 수 있다(법무 검토 필요).
- TTS 캐시: 어느 단계도 참조하지 않는 mp3는 TTS_ORPHAN_GRACE_HOURS(기본 24) 지나면 지운다. 막 합성돼
  아직 단계 행이 커밋되기 전인 파일(직무 생성 중)을 지우지 않으려고 유예를 둔다.
  (Phase 0.3) 사진·TTS 모두 소유 레코드(MediaFile) 기준으로 media.gc가 정리한다. 유예시간 이름은
  MEDIA_ORPHAN_GRACE_HOURS(없으면 TTS_ORPHAN_GRACE_HOURS).
- BACKUP_RETENTION_DAYS (기본 30, 3-0 M8): DB 백업 사본. 마이그레이션 직전 자동 백업(db_migrate.backup_before_upgrade,
  `jobcard-<시각>-<리비전>.db`)과 야간 백업(같은 폴더에 `jobcard-`로 시작하는 이름으로 둔다)은 DB 전체(근로자 이름·메모·
  수행 기록)를 담고, 근로자를 지워도 사본에는 남는다. 그래서 30일 지난 사본은 purge가 지운다. 백업 폴더
  (db_migrate.backup_dir_for: DB 옆 backups/ 또는 JOBCARD_BACKUP_DIR) 바로 아래의 `jobcard-*.db`·`jobcard-*.db.gz`
  보통 파일만 본다 — 하위 폴더·바로 가기(symlink)·다른 이름의 파일·지금 쓰는 DB 파일은 절대 건드리지 않는다.
  나이는 이름의 시각(`jobcard-20261114T010203...Z-...`)으로 재고, 이름에 시각이 없으면 수정 시각으로 잰다
  (shutil.copy2는 원본 DB의 수정 시각을 그대로 복사하므로 이름의 시각이 더 정확하다).

감사 로그를 지우는 코드는 이 파일에만 있어야 한다(tests/test_privacy.py가 확인한다). Core delete는
models.AccessAuditLog의 ORM 수정·삭제 차단 이벤트를 거치지 않는다 — 그래서 purge만 지울 수 있다.
"""
from __future__ import annotations

import fnmatch
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

import media
from database import checkpoint_wal
from models import AccessAuditLog, ClientEvent, HelpRequest, PerformanceLog


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


def backup_retention_days() -> int:
    return _positive_days("BACKUP_RETENTION_DAYS", 30)


# 백업 사본으로 보는 이름. 지금 쓰는 DB(jobcard.db)는 '-'가 없어 걸리지 않는다(그래도 따로 한 번 더 막는다).
_BACKUP_PATTERNS = ("jobcard-*.db", "jobcard-*.db.gz")
_STAMP_RE = re.compile(r"^jobcard-(?:[a-z]+-)?(\d{8}T\d{6})(\d{0,6})Z")


def _backup_time(path: Path) -> datetime:
    """백업을 만든 시각(UTC, tz 없음). 이름에 시각이 있으면 그것, 없으면 수정 시각."""
    m = _STAMP_RE.match(path.name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%dT%H%M%S")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).replace(tzinfo=None)


def purge_backups(db_file: Path | None, *, now: datetime, dry_run: bool = False) -> int:
    """보존기간(BACKUP_RETENTION_DAYS)이 지난 DB 백업 사본을 지운다. 지운(지울) 파일 수를 돌려준다.

    백업 폴더 바로 아래의 보통 파일 중 이름이 _BACKUP_PATTERNS에 맞는 것만 본다. 폴더가 없거나 SQLite 파일 DB가
    아니면 0. 파일 하나를 지우지 못해도(권한 등) 나머지는 계속 지우고, 다음 실행에서 다시 시도한다.
    """
    import db_migrate  # 지연 import: alembic을 /health 경로에서 끌어오지 않게

    if db_file is None:
        return 0
    folder = db_migrate.backup_dir_for(db_file)
    if not folder.is_dir():
        return 0
    folder = folder.resolve()
    live = {db_file.resolve(), *(db_file.resolve().with_name(db_file.name + s) for s in ("-wal", "-shm", "-journal"))}
    cutoff = now - timedelta(days=backup_retention_days())
    count = 0
    for path in folder.iterdir():
        if not any(fnmatch.fnmatchcase(path.name, pat) for pat in _BACKUP_PATTERNS):
            continue
        # 바로 가기는 따라가지 않는다(폴더 밖 파일을 지우게 될 수 있다). 하위 폴더도 보지 않는다.
        if path.is_symlink() or not path.is_file():
            continue
        if path.resolve().parent != folder or path.resolve() in live:
            continue
        try:
            if _backup_time(path) >= cutoff:
                continue
            if not dry_run:
                path.unlink()
        except OSError:
            continue
        count += 1
    return count


def _db_file(db: Session) -> Path | None:
    import db_migrate

    return db_migrate.sqlite_file(db.get_bind())


def tts_orphan_grace_hours() -> float:
    # (Phase 0.3) 사진·TTS 공통 유예시간(media.orphan_grace_hours)으로 옮겼다. 예전 이름도 그대로 받는다.
    return media.orphan_grace_hours()


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def purge(db: Session, *, dry_run: bool = False, now: datetime | None = None) -> dict:
    """보존기간이 지난 수행 로그·도움 요청·측정 이벤트·접근 감사 로그·DB 백업 사본과 고아 사진·TTS(media.gc)를
    지운다. 지운(지울) 개수를 돌려준다."""
    now = now or _utcnow_naive()
    log_cutoff = now - timedelta(days=performance_log_retention_days())
    audit_cutoff = now - timedelta(days=access_audit_retention_days())

    log_filter = PerformanceLog.completed_at < log_cutoff
    help_filter = HelpRequest.created_at < log_cutoff
    event_filter = ClientEvent.created_at < log_cutoff
    audit_filter = AccessAuditLog.at < audit_cutoff
    report = {
        "performance_logs": db.scalar(select(func.count()).select_from(PerformanceLog).where(log_filter)) or 0,
        "access_audit_logs": db.scalar(select(func.count()).select_from(AccessAuditLog).where(audit_filter)) or 0,
        "help_requests": db.scalar(select(func.count()).select_from(HelpRequest).where(help_filter)) or 0,
        "client_events": db.scalar(select(func.count()).select_from(ClientEvent).where(event_filter)) or 0,
    }
    report["dry_run"] = dry_run
    # 백업 사본은 DB 행과 상관없는 파일이라 먼저 정리한다(DB 삭제가 실패해도 지난 사본은 지운다).
    report["backup_files"] = purge_backups(_db_file(db), now=now, dry_run=dry_run)
    if dry_run:
        report.update({k: v for k, v in media.gc(db, dry_run=True).items() if k != "dry_run"})
        return report

    db.execute(delete(PerformanceLog).where(log_filter))
    db.execute(delete(HelpRequest).where(help_filter))
    db.execute(delete(ClientEvent).where(event_filter))
    db.execute(delete(AccessAuditLog).where(audit_filter))
    db.commit()

    def _checkpoint() -> None:
        # 지운 기록이 WAL 파일에 남아 있지 않게 바로 체크포인트한다(database.checkpoint_wal 참고).
        # 지울 것이 없어도 매번 한다 — 근로자 삭제 직후 다른 연결의 읽기 때문에 끝나지 못한 체크포인트를
        # 여기서 다시 해, 삭제된 이름·메모가 -wal 파일에 남아 있는 기간을 하루 안으로 줄인다.
        report["wal_checkpointed"] = checkpoint_wal(db)

    # 고아 사진·TTS 정리(manage.py gc-media와 같은 일). 지울 파일을 고른 뒤·지우기 직전 사이에 체크포인트를 한다.
    # 그 사이 직무 생성·단계 수정이 같은 문장의 캐시를 다시 썼으면(tts.synthesize_tts가 수정 시각을 갱신하고
    # 레코드가 그 파일을 가리키게 된다) media.gc가 지우기 직전에 다시 확인해 남긴다.
    gc_report = media.gc(db, before_unlink=_checkpoint)
    report.update({k: v for k, v in gc_report.items() if k != "dry_run"})
    return report
