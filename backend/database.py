"""DB 연결 (SQLAlchemy).

현재 지원하는 DB는 SQLite 하나다(단일 서버 + 단일 프로세스 운영 전제).
- 날짜 집계가 SQLite 전용 문법(date(col, '+9 hours'))을 쓰므로 DATABASE_URL만 Postgres로
  바꿔서는 동작하지 않는다. 옮기려면 main.py의 _SQL_LOCAL_DATE_MODIFIER 사용처를 먼저 고친다.
- 동시 요청에 대비해 WAL 모드와 잠금 대기(busy_timeout)를 켠다. 켜지 않으면 쓰기가 겹칠 때
  바로 'database is locked' 오류가 난다.
- 백업은 DB 파일(jobcard.db)과 함께 -wal/-shm 파일도 복사하거나, sqlite3 .backup을 쓴다.
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jobcard.db")

# SQLite는 동일 스레드 제약이 있어 옵션을 단다 (Postgres에선 무시됨).
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _record) -> None:
        cur = dbapi_conn.cursor()
        if ":memory:" not in DATABASE_URL:
            cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 모델에 새로 생긴 컬럼을 기존 DB에 채워 넣는다.
# create_all()은 없는 '테이블'만 만들고 기존 테이블에 '컬럼'은 추가하지 않는다.
# 즉 컬럼을 추가하면 이미 만들어진 DB에서 조회가 OperationalError로 깨진다.
# 정식 마이그레이션 도구(Alembic)를 붙이기 전까지 이 최소 장치로 메운다.
#
# 지켜야 할 조건: 새 컬럼은 NULL 허용이거나 기본값이 있어야 한다(기존 행을 채워야 하므로).
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "tasks": {
        "business_type": "VARCHAR DEFAULT ''",
        "work_environment": "VARCHAR DEFAULT ''",
        "job": "VARCHAR DEFAULT ''",
    },
    "steps": {
        "symbol_query": "TEXT DEFAULT ''",
    },
}


def apply_pending_columns() -> list[str]:
    """모델에 있으나 DB에 없는 컬럼을 ALTER TABLE로 추가한다. 추가한 항목을 돌려준다."""
    from sqlalchemy import inspect, text

    applied: list[str] = []
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if table not in existing_tables:
                continue  # create_all이 새로 만들 테이블 — 이미 최신 스키마다.
            present = {c["name"] for c in inspector.get_columns(table)}
            for name, ddl in columns.items():
                if name in present:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                applied.append(f"{table}.{name}")
    return applied
