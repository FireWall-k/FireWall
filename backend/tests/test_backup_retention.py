"""(3-0 M8) purge가 보존기간(BACKUP_RETENTION_DAYS, 기본 30일)이 지난 DB 백업 사본을 지운다.

마이그레이션 직전 자동 백업(backups/jobcard-<시각>-<리비전>.db)과 야간 백업(같은 폴더, jobcard-로 시작)에는
근로자 이름·메모·수행 기록이 그대로 들어 있고 근로자를 지워도 사본에는 남는다. 지키는 것:
1. 31일 된 사본은 지우고 29일 된 사본은 남긴다(이름의 시각, 이름에 시각이 없으면 수정 시각).
2. 백업 폴더 밖·하위 폴더·다른 이름의 파일·지금 쓰는 DB 파일·바로 가기는 절대 지우지 않는다.
3. dry-run은 세기만 한다. manage.py purge가 실제로 지우고 몇 개 지웠는지 알린다.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import manage
import retention

NOW = datetime(2026, 11, 14, 3, 0, 0)


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S%fZ")


def _touch(path: Path, age_days: float | None = None, now: datetime = NOW) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"SQLite format 3")
    if age_days is not None:
        t = (now - timedelta(days=age_days)).replace(tzinfo=timezone.utc).timestamp()
        os.utime(path, (t, t))
    return path


@pytest.fixture()
def db_dir(tmp_path, monkeypatch) -> Path:
    monkeypatch.delenv("JOBCARD_BACKUP_DIR", raising=False)
    monkeypatch.delenv("BACKUP_RETENTION_DAYS", raising=False)
    d = tmp_path / "data"
    _touch(d / "jobcard.db")
    return d


def test_31_day_old_backup_is_deleted_and_29_day_old_is_kept(db_dir):
    bk = db_dir / "backups"
    # 마이그레이션 백업: 이름의 시각으로 잰다. 수정 시각은 원본 DB 것을 복사해 오므로(copy2) 일부러 반대로 둔다.
    old = _touch(bk / f"jobcard-{_stamp(NOW - timedelta(days=31))}-0009_live_push.db", age_days=0)
    new = _touch(bk / f"jobcard-{_stamp(NOW - timedelta(days=29))}-0010_workplace_settings.db", age_days=400)
    # 야간 백업(이름에 시각 형식이 없으면 수정 시각으로 잰다).
    nightly_old = _touch(bk / "jobcard-nightly-old.db", age_days=31)
    nightly_new = _touch(bk / "jobcard-nightly-new.db.gz", age_days=29)
    nightly_stamped = _touch(bk / f"jobcard-nightly-{_stamp(NOW - timedelta(days=31))}.db.gz", age_days=0)

    assert retention.purge_backups(db_dir / "jobcard.db", now=NOW) == 3

    assert not old.exists()
    assert not nightly_old.exists()
    assert not nightly_stamped.exists()
    assert new.exists()
    assert nightly_new.exists()


def test_retention_days_follow_setting(db_dir, monkeypatch):
    bk = db_dir / "backups"
    f = _touch(bk / f"jobcard-{_stamp(NOW - timedelta(days=10))}-0009.db")
    monkeypatch.setenv("BACKUP_RETENTION_DAYS", "11")
    assert retention.purge_backups(db_dir / "jobcard.db", now=NOW) == 0
    monkeypatch.setenv("BACKUP_RETENTION_DAYS", "9")
    assert retention.purge_backups(db_dir / "jobcard.db", now=NOW) == 1
    assert not f.exists()
    monkeypatch.setenv("BACKUP_RETENTION_DAYS", "0")
    with pytest.raises(ValueError):
        retention.backup_retention_days()


def test_never_deletes_outside_backups_folder(db_dir, tmp_path):
    bk = db_dir / "backups"
    old = _stamp(NOW - timedelta(days=400))
    keep = [
        _touch(db_dir / f"jobcard-{old}-0001.db", age_days=400),          # DB 폴더(백업 폴더 밖)
        _touch(tmp_path / f"jobcard-{old}-0001.db", age_days=400),        # 더 바깥
        _touch(bk / "sub" / f"jobcard-{old}-0001.db", age_days=400),      # 하위 폴더
        _touch(bk / "notes.txt", age_days=400),                           # 다른 이름
        _touch(bk / "jobcard.db", age_days=400),                          # '-' 없는 이름
        _touch(bk / f"other-{old}.db", age_days=400),
        _touch(bk / f"jobcard-{old}-0001.db-wal", age_days=400),
    ]
    assert retention.purge_backups(db_dir / "jobcard.db", now=NOW) == 0
    for p in keep:
        assert p.exists(), p


def test_symlink_in_backups_is_not_followed(db_dir, tmp_path):
    outside = _touch(tmp_path / "elsewhere" / "precious.db", age_days=400)
    link = db_dir / "backups" / f"jobcard-{_stamp(NOW - timedelta(days=400))}-x.db"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("이 환경에서는 바로 가기를 만들 수 없음(Windows 권한)")
    assert retention.purge_backups(db_dir / "jobcard.db", now=NOW) == 0
    assert outside.exists()
    assert link.is_symlink()


def test_backup_dir_setting_pointing_at_db_folder_never_touches_live_db(db_dir, monkeypatch):
    monkeypatch.setenv("JOBCARD_BACKUP_DIR", str(db_dir))
    live = db_dir / "jobcard.db"
    os.utime(live, (0, 0))  # 아주 오래된 수정 시각이어도
    old = _touch(db_dir / f"jobcard-{_stamp(NOW - timedelta(days=31))}-0009.db")
    assert retention.purge_backups(live, now=NOW) == 1
    assert live.exists()
    assert not old.exists()


def test_dry_run_only_counts(db_dir):
    old = _touch(db_dir / "backups" / f"jobcard-{_stamp(NOW - timedelta(days=31))}-0009.db")
    assert retention.purge_backups(db_dir / "jobcard.db", now=NOW, dry_run=True) == 1
    assert old.exists()


def test_missing_folder_or_memory_db_is_zero(db_dir):
    assert retention.purge_backups(db_dir / "jobcard.db", now=NOW) == 0  # backups/ 없음
    assert retention.purge_backups(None, now=NOW) == 0


def test_manage_purge_deletes_old_backups(client, monkeypatch, tmp_path, capsys):
    """manage.py purge(= scheduler가 매일 도는 것)가 실제 DB의 백업 폴더에서 지난 사본을 지우고 알린다."""
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "tts"))
    monkeypatch.delenv("BACKUP_RETENTION_DAYS", raising=False)
    bk = tmp_path / "bk"
    monkeypatch.setenv("JOBCARD_BACKUP_DIR", str(bk))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    old = _touch(bk / f"jobcard-{_stamp(now - timedelta(days=31))}-0009.db", now=now)
    new = _touch(bk / f"jobcard-{_stamp(now - timedelta(days=29))}-0010.db", now=now)

    manage.main(["purge", "--dry-run"])
    assert "DB 백업 사본 1개 지울 대상 (보존 30일)" in capsys.readouterr().out
    assert old.exists()

    manage.main(["purge"])
    assert "DB 백업 사본 1개 지움 (보존 30일)" in capsys.readouterr().out
    assert not old.exists()
    assert new.exists()
