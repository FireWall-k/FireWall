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
