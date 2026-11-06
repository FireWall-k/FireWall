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
        # 지운 행의 내용을 0으로 덮어쓴다. 기본값(off)이면 근로자를 삭제해도 이름·메모가 DB 파일의 빈
        # 페이지에 그대로 남아, 파일 사본(백업·유출)에서 되살릴 수 있다(개인정보 파기 요건).
        # 연결마다 걸어야 하는 설정이라 여기서 켠다. WAL에 남은 옛 프레임은 삭제 직후 체크포인트로 비운다.
        cur.execute("PRAGMA secure_delete=ON")
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


# 스키마는 Alembic 리비전(migrations/)으로만 바꾼다. 실행 입구는 db_migrate.py.
# 예전의 _ADDED_COLUMNS/apply_pending_columns()는 컬럼 '추가'만 할 수 있었고 서버 기동마다 돌았다.
# 레거시 DB 보정용으로만 db_migrate._LEGACY_COLUMNS에 고정해 남겼다.


def checkpoint_wal(db_session) -> None:
    """WAL에 남은 프레임을 DB 파일로 옮기고 WAL을 비운다(SQLite 전용, 그 밖에는 아무것도 안 한다).

    secure_delete는 지운 페이지를 0으로 덮어쓰지만, WAL 모드에서는 지우기 전 내용을 담은 프레임이
    -wal 파일에 체크포인트 때까지 남는다. 근로자 삭제처럼 "디스크에서도 사라져야 하는" 작업 직후에 부른다.
    다른 연결이 읽는 중이면 일부만 옮겨질 수 있다(그래도 다음 자동 체크포인트 때 덮인다).
    """
    if not DATABASE_URL.startswith("sqlite"):
        return
    from sqlalchemy import text

    db_session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
