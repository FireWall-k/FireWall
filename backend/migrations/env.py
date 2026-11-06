"""Alembic 실행 환경.

- 비교 대상 메타데이터는 models.py의 Base.metadata다(autogenerate·`alembic check`가 이걸 본다).
- DB 주소는 database.DATABASE_URL(=DATABASE_URL 환경변수)을 쓴다. alembic.ini에 따로 적으면
  앱과 마이그레이션이 서로 다른 DB를 보게 될 수 있다.
- db_migrate.py가 코드에서 부를 때는 이미 열린 연결을 config.attributes["connection"]으로 넘긴다.
  그래야 레거시 보정·stamp·upgrade가 테스트용 엔진이나 같은 트랜잭션 안에서 돈다.
"""
from __future__ import annotations

import os
import sys

from alembic import context
from sqlalchemy import create_engine, pool

# `alembic` CLI를 backend/ 밖에서 실행해도 database/models를 찾게 한다.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import models  # noqa: E402,F401  (Base.metadata에 테이블을 등록한다)
from database import DATABASE_URL, Base  # noqa: E402

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    return config.get_main_option("sqlalchemy.url") or DATABASE_URL


def _configure(**kw) -> None:
    context.configure(
        target_metadata=target_metadata,
        # SQLite는 ALTER TABLE로 컬럼 변경·삭제를 못 한다. batch 모드는 "새 테이블 생성 → 복사 →
        # 교체"로 이를 대신하므로, 이후 리비전이 SQLite에서도 그대로 돈다.
        render_as_batch=True,
        compare_type=True,
        **kw,
    )


def run_migrations_offline() -> None:
    _configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        _configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()
        return

    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as conn:
        _configure(connection=conn)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
