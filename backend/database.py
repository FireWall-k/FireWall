"""DB 연결 (SQLAlchemy).

스켈레톤은 zero-setup을 위해 SQLite를 기본값으로 쓴다.
운영/실증에서는 DATABASE_URL 환경변수만 Postgres로 바꾸면 된다.
  예: export DATABASE_URL=postgresql+psycopg://user:pass@host/jobcard
"""
from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./jobcard.db")

# SQLite는 동일 스레드 제약이 있어 옵션을 단다 (Postgres에선 무시됨).
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
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
