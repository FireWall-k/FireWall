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
        # 체크포인트가 WAL을 처음부터 다시 쓰기 시작할 때 파일을 이 크기(바이트)로 자른다. 기본값(-1)이면
        # WAL 파일 길이가 그대로 남아, 새로 쓴 지점보다 뒤에 있는 옛 프레임(지운 이름·메모 포함)이
        # 다음 체크포인트가 돌아도 물리적으로 남는다. 0이면 매번 끝까지 잘라 낸다.
        cur.execute("PRAGMA journal_size_limit=0")
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


# 체크포인트를 다른 연결의 읽기 트랜잭션이 막을 때 다시 해 보는 횟수와 간격(초).
# 대시보드는 3초마다 폴링하고 한 번의 읽기는 수 밀리초면 끝나므로, 짧게 몇 번 다시 하면 대개 성공한다.
_CHECKPOINT_ATTEMPTS = 5
_CHECKPOINT_RETRY_SLEEP = 0.2
# 시도마다 잠금을 기다리는 시간(밀리초). 연결 기본값(busy_timeout=5000)을 그대로 쓰면 시도 한 번에
# 5초씩 걸려 삭제 요청 응답이 수십 초 늦어진다.
_CHECKPOINT_BUSY_MS = 200


def checkpoint_wal(db_session, *, attempts: int | None = None) -> bool:
    """WAL에 남은 프레임을 DB 파일로 옮기고 WAL 파일을 0바이트로 자른다(SQLite 전용, 그 밖에는 True).

    secure_delete는 지운 페이지를 0으로 덮어쓰지만, WAL 모드에서는 지우기 전 내용을 담은 프레임이
    -wal 파일에 남는다. 근로자 삭제처럼 "디스크에서도 사라져야 하는" 작업 직후에 부른다.

    다른 연결이 읽기 트랜잭션을 잡고 있으면 TRUNCATE 체크포인트는 끝까지 못 가고(busy=1이거나
    옮긴 프레임 수 < WAL 프레임 수) 옛 프레임이 -wal 파일에 그대로 남는다. 저절로 덮인다고 가정하지
    않는다 — WAL을 재시작해도 파일을 자르지 않으면 새로 쓴 지점 뒤의 옛 프레임은 물리적으로 남기
    때문이다(journal_size_limit=0으로 줄이지만, 그것도 재시작이 일어나야 적용된다).
    그래서 결과를 확인해 짧게 다시 하고, 그래도 안 되면 경고를 남기고 False를 돌려준다.
    호출한 쪽은 False를 알릴 수 있고, 매일 도는 purge(retention.py)가 다시 TRUNCATE 체크포인트를 한다.
    """
    if not DATABASE_URL.startswith("sqlite"):
        return True
    import logging
    import time

    from sqlalchemy import text

    tries = attempts or _CHECKPOINT_ATTEMPTS
    db_session.execute(text(f"PRAGMA busy_timeout={_CHECKPOINT_BUSY_MS}"))
    try:
        result = None
        for i in range(tries):
            # 결과: (busy, WAL 프레임 수, 옮긴 프레임 수). busy=0이고 둘이 같아야(TRUNCATE면 보통 0, 0)
            # WAL이 비고 파일이 잘린 것이다.
            row = db_session.execute(text("PRAGMA wal_checkpoint(TRUNCATE)")).fetchone()
            result = tuple(row) if row is not None else (0, 0, 0)
            busy, log_frames, checkpointed = result
            if busy == 0 and log_frames == checkpointed:
                return True
            if i + 1 < tries:
                time.sleep(_CHECKPOINT_RETRY_SLEEP)
        logging.getLogger("jobcard.database").warning(
            "WAL 체크포인트를 끝내지 못했습니다(busy, log, checkpointed)=%s. 지운 데이터가 -wal 파일에 "
            "남아 있을 수 있습니다 — 다음 purge가 다시 시도합니다.", result)
        return False
    finally:
        db_session.execute(text("PRAGMA busy_timeout=5000"))
