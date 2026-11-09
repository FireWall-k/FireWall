"""스키마 마이그레이션 실행기(Alembic 래퍼).

스키마 변경은 migrations/versions/ 의 Alembic 리비전으로만 한다. 이 모듈은 그 리비전을
코드에서 돌리는 입구이고, 세 곳에서 쓴다.
- `python manage.py migrate` : 배포 시 compose의 일회성 migrate 서비스가 실행한다(운영의 정식 경로).
- main.py lifespan          : ensure_schema_ready()로 "DB가 head인가"만 확인한다.
                              운영이면 아니면 기동 거부, 개발이면 그 자리에서 자동 upgrade.
- 테스트                    : conftest와 test_migration.py.

Alembic 도입 전 설치본(jobcard-data 볼륨의 SQLite)에는 alembic_version 테이블이 없고, 예전
apply_pending_columns()가 아직 못 채운 컬럼이 빠져 있을 수 있다. 그런 DB에 바로 `upgrade head`를
하면 baseline이 이미 있는 테이블을 또 만들려다 실패한다. 그래서 migrate()는 이런 DB를 감지하면
먼저 baseline 모양으로 보정(adopt_legacy_db)하고 baseline으로 stamp한 뒤 upgrade head 한다.
"""
from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Engine

logger = logging.getLogger("jobcard.migrate")

_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
_ALEMBIC_INI = os.path.join(_BACKEND_DIR, "alembic.ini")

# Alembic 도입 직전 스키마(= 0001_baseline)를 가리킨다. 레거시 DB는 이 리비전으로 stamp한다.
BASELINE_REVISION = "0001_baseline"

# Alembic 도입 전, create_all() 이후에 모델에 추가돼 예전 apply_pending_columns()가 ALTER TABLE로
# 메우던 컬럼들(예전 database._ADDED_COLUMNS). 레거시 DB를 baseline 모양으로 맞추는 데만 쓰므로
# 고정이다 — 앞으로의 컬럼 추가는 여기가 아니라 새 Alembic 리비전으로 한다.
# 기존 행이 NULL로 남으면 검색 맥락으로 그대로 쓰일 때 깨지므로 빈 문자열 기본값을 채운다.
_LEGACY_COLUMNS: dict[str, dict[str, sa.types.TypeEngine]] = {
    "tasks": {
        "business_type": sa.String(),
        "work_environment": sa.String(),
        "job": sa.String(),
    },
    "steps": {
        "symbol_query": sa.Text(),
    },
}


def alembic_config() -> Config:
    """backend/alembic.ini를 읽은 설정. 실행 위치(cwd)와 상관없이 같은 리비전 폴더를 본다."""
    return Config(_ALEMBIC_INI)


def default_engine() -> Engine:
    # 지연 import: 테스트가 이 함수를 바꿔 끼워 임시 DB로 돌릴 수 있게 한다.
    from database import engine

    return engine


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config())


def head_revision() -> str:
    # 리비전이 갈라져 head가 둘 이상이면 여기서 예외가 난다(배포 전에 merge 리비전이 필요하다는 뜻).
    return _script().get_current_head()


def current_revision(engine: Engine | None = None) -> str | None:
    engine = engine or default_engine()
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def is_at_head(engine: Engine | None = None) -> bool:
    return current_revision(engine) == head_revision()


def _run_command(engine: Engine, fn: Callable[[Config], None]) -> None:
    """Alembic 명령을 주어진 엔진의 연결 위에서 돌린다(env.py가 config.attributes에서 꺼내 쓴다)."""
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        fn(cfg)


def upgrade_to_head(engine: Engine | None = None) -> None:
    _run_command(engine or default_engine(), lambda cfg: command.upgrade(cfg, "head"))


def downgrade(engine: Engine | None, target: str) -> None:
    _run_command(engine or default_engine(), lambda cfg: command.downgrade(cfg, target))


def _stamp(engine: Engine, revision: str) -> None:
    _run_command(engine, lambda cfg: command.stamp(cfg, revision))


def _baseline_metadata() -> sa.MetaData:
    """0001_baseline 리비전에 고정된 테이블 정의. 현재 models.py가 아니라 이것을 써야
    stamp 직후 DB가 정확히 baseline 모양이 된다(리비전 파일 docstring 참고)."""
    return _script().get_revision(BASELINE_REVISION).module.build_metadata()


def repair_legacy_columns(engine: Engine) -> list[str]:
    """레거시 DB의 기존 테이블에 빠진 컬럼을 추가한다. 추가한 항목("table.column")을 돌려준다.

    예전 apply_pending_columns()와 같은 일을 한다. 단, NOT NULL DEFAULT ''로 추가해
    baseline(NOT NULL)과 모양이 같아지게 한다(SQLite는 기본값이 있으면 NOT NULL 컬럼 추가를 허용한다).
    없는 테이블은 건드리지 않는다 — adopt_legacy_db()가 baseline 정의로 통째로 만든다.
    """
    applied: list[str] = []
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in _LEGACY_COLUMNS.items():
            if table not in existing_tables:
                continue
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, type_ in columns.items():
                if name in present:
                    continue
                ddl = type_.compile(dialect=engine.dialect)
                conn.execute(sa.text(
                    f"ALTER TABLE {table} ADD COLUMN {name} {ddl} NOT NULL DEFAULT ''"
                ))
                applied.append(f"{table}.{name}")
    return applied


def _tighten_legacy_nullability(engine: Engine) -> list[str]:
    """예전 apply_pending_columns()는 컬럼을 NULL 허용으로 추가했다. baseline은 NOT NULL이므로
    그대로 stamp하면 이후 autogenerate·`alembic check`가 매번 차이를 보고한다.
    NULL을 ''로 채운 뒤 batch 모드(테이블 재생성 + 데이터 복사)로 NOT NULL로 바꾼다."""
    fixed: list[str] = []
    inspector = sa.inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        ops = Operations(MigrationContext.configure(conn, opts={"render_as_batch": True}))
        for table, columns in _LEGACY_COLUMNS.items():
            if table not in existing_tables:
                continue
            info = {c["name"]: c for c in inspector.get_columns(table)}
            loose = [n for n in columns if n in info and info[n]["nullable"]]
            if not loose:
                continue
            for name in loose:
                conn.execute(sa.text(f"UPDATE {table} SET {name} = '' WHERE {name} IS NULL"))
            with ops.batch_alter_table(table) as batch:
                for name in loose:
                    batch.alter_column(name, existing_type=columns[name], nullable=False)
            fixed.extend(f"{table}.{n}" for n in loose)
    return fixed


def _has_app_tables(engine: Engine) -> bool:
    present = set(sa.inspect(engine).get_table_names())
    return bool(present & set(_baseline_metadata().tables))


def adopt_legacy_db(engine: Engine) -> tuple[list[str], list[str]]:
    """Alembic 도입 전 DB를 baseline 모양으로 맞추고 baseline으로 stamp한다.

    순서: 빠진 컬럼 추가 → NULL 허용 컬럼 조이기 → 빠진 테이블 생성(baseline 정의) → stamp.
    데이터는 지우지 않는다. (추가한 컬럼, NOT NULL로 조인 컬럼) 목록을 돌려준다 — 둘 다 운영자가
    migrate 출력에서 봐야 한다(조이기는 테이블 재생성이라 무엇이 바뀌었는지 알아야 백업과 대조할 수 있다).
    """
    repaired = repair_legacy_columns(engine)
    tightened = _tighten_legacy_nullability(engine)
    with engine.begin() as conn:
        _baseline_metadata().create_all(bind=conn, checkfirst=True)
    _stamp(engine, BASELINE_REVISION)
    if repaired or tightened:
        logger.info("레거시 DB 보정: 추가 %s / NOT NULL %s", repaired, tightened)
    return repaired, tightened


def migrate(engine: Engine | None = None) -> dict:
    """DB를 head로 올린다. 빈 DB·레거시 DB·이미 관리 중인 DB 모두 이 하나로 처리한다(멱등)."""
    engine = engine or default_engine()
    before = current_revision(engine)
    adopted = False
    repaired: list[str] = []
    tightened: list[str] = []
    if before is None and _has_app_tables(engine):
        repaired, tightened = adopt_legacy_db(engine)
        adopted = True
    upgrade_to_head(engine)
    return {
        "from_revision": before,
        "to_revision": current_revision(engine),
        "adopted_legacy": adopted,
        "repaired_columns": repaired,
        "tightened_columns": tightened,
    }


def sqlite_file(engine: Engine) -> Path | None:
    """엔진이 가리키는 SQLite 파일 경로(메모리 DB·다른 DB면 None)."""
    url = engine.url
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return None
    return Path(url.database).resolve()


def backup_dir_for(db_file: Path) -> Path:
    """백업 폴더. 기본은 DB 파일 옆 backups/(같은 볼륨), JOBCARD_BACKUP_DIR로 바꿀 수 있다."""
    configured = (os.getenv("JOBCARD_BACKUP_DIR") or "").strip()
    return Path(configured) if configured else db_file.parent / "backups"


def backup_before_upgrade(engine: Engine | None = None) -> Path | None:
    """(2a-0) upgrade 전에 DB 파일을 backups/jobcard-<시각>-<리비전>.db로 복사한다. 만든 파일 경로를 돌려준다.

    - 먼저 PRAGMA wal_checkpoint(TRUNCATE)로 WAL의 내용을 본 파일에 옮긴다. WAL에 남은 최근 쓰기를 빼고 본 파일만
      복사하면 백업이 조용히 옛 상태가 된다. 다른 연결이 읽는 중이라 체크포인트를 끝내지 못하면 예외를 낸다.
    - 이미 head이거나(바꿀 것이 없음), 파일·앱 테이블이 없는 새 DB면 복사하지 않고 None.
    - 복사에 실패하면 예외가 그대로 올라간다 — 부르는 쪽(manage.py migrate)은 upgrade를 하지 않는다.
    """
    engine = engine or default_engine()
    db_file = sqlite_file(engine)
    if db_file is None or not db_file.is_file():
        return None
    if not sa.inspect(engine).get_table_names() or is_at_head(engine):
        return None
    rev = current_revision(engine) or "none"
    with engine.connect() as conn:
        busy = conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)").first()
    if busy is not None and busy[0]:
        raise RuntimeError("다른 연결이 DB를 쓰는 중이라 WAL 체크포인트를 끝내지 못했습니다")
    folder = backup_dir_for(db_file)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = folder / f"jobcard-{stamp}-{rev}.db"
    shutil.copy2(db_file, target)
    if target.stat().st_size != db_file.stat().st_size:
        raise RuntimeError(f"백업 파일 크기가 원본과 다릅니다: {target}")
    return target


def ensure_schema_ready(engine: Engine | None = None, production: bool | None = None) -> None:
    """서버 기동 시 스키마가 head인지 확인한다.

    운영: 요청을 받는 프로세스가 스키마를 바꾸지 않는다. 여러 인스턴스가 동시에 뜨면 마이그레이션이
          겹치고, 실패하면 반쯤 바뀐 DB로 요청을 받게 된다. 그래서 migrate 서비스가 먼저 끝났어야
          하며, 아니면 무엇을 하라는지 적어서 기동을 멈춘다.
    개발: docker compose 없이 `uvicorn main:app`만 띄우는 일이 흔하다. 매번 migrate를 따로 돌리라고
          하면 번거롭고, 잊으면 알 수 없는 OperationalError로 깨지므로 그 자리에서 upgrade 한다.
    """
    engine = engine or default_engine()
    if production is None:
        from auth import is_production

        production = is_production()

    if is_at_head(engine):
        return
    if production:
        raise RuntimeError(
            "DB 스키마가 최신이 아닙니다 "
            f"(현재 {current_revision(engine) or '없음'}, 필요 {head_revision()}). "
            "먼저 `python manage.py migrate`를 실행하세요 "
            "(docker compose에서는 migrate 서비스가 backend보다 먼저 돕니다)."
        )
    report = migrate(engine)
    logger.info("개발 모드 자동 마이그레이션: %s", report)
