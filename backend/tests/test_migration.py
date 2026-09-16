"""컬럼 추가 마이그레이션 테스트.

create_all()은 기존 테이블에 컬럼을 추가하지 않는다. 모델에 컬럼이 늘어나면
이미 만들어진 DB에서 조회가 깨진다. apply_pending_columns()가 그 구멍을 메우는지,
그리고 여러 번 돌려도 안전한지 확인한다.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402


@pytest.fixture()
def legacy_db(monkeypatch):
    """business_type/work_environment가 없던 시절의 tasks 테이블을 만든다."""
    tmp = tempfile.mkdtemp()
    url = f"sqlite:///{tmp}/legacy.db"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE tasks (
                id VARCHAR PRIMARY KEY,
                employer_id VARCHAR,
                title VARCHAR,
                raw_input TEXT,
                status VARCHAR,
                created_at DATETIME
            )
        """))
        conn.execute(text(
            "INSERT INTO tasks (id, employer_id, title, raw_input, status) "
            "VALUES ('t1', 'e1', '예전 직무', '상자를 옮기세요', 'draft')"
        ))
    return engine


def test_adds_missing_columns_to_existing_table(legacy_db, monkeypatch):
    import database

    monkeypatch.setattr(database, "engine", legacy_db)

    before = {c["name"] for c in inspect(legacy_db).get_columns("tasks")}
    assert "business_type" not in before

    applied = database.apply_pending_columns()

    assert "tasks.business_type" in applied
    assert "tasks.work_environment" in applied
    after = {c["name"] for c in inspect(legacy_db).get_columns("tasks")}
    assert {"business_type", "work_environment"} <= after


def test_adds_step_symbol_query_column(legacy_db, monkeypatch):
    """steps 테이블에도 symbol_query 컬럼을 추가해야 한다(구 DB에서 후보 조회가 안 깨지게)."""
    import database

    with legacy_db.begin() as conn:
        conn.execute(text("""
            CREATE TABLE steps (
                id VARCHAR PRIMARY KEY, task_id VARCHAR, order_index INTEGER,
                sentence TEXT, action_type VARCHAR, symbol_url VARCHAR,
                symbol_source VARCHAR, needs_fallback BOOLEAN, tts_audio_url VARCHAR
            )
        """))
        conn.execute(text(
            "INSERT INTO steps (id, task_id, order_index, sentence) "
            "VALUES ('s1', 't1', 1, '상자를 옮기세요')"
        ))
    monkeypatch.setattr(database, "engine", legacy_db)

    applied = database.apply_pending_columns()
    assert "steps.symbol_query" in applied
    with legacy_db.connect() as conn:
        val = conn.execute(text("SELECT symbol_query FROM steps WHERE id='s1'")).scalar()
    assert val == ""


def test_existing_rows_get_a_usable_default(legacy_db, monkeypatch):
    """기존 행이 NULL로 남으면 안 된다 — 검색 맥락으로 그대로 쓰이기 때문."""
    import database

    monkeypatch.setattr(database, "engine", legacy_db)
    database.apply_pending_columns()

    with legacy_db.connect() as conn:
        row = conn.execute(
            text("SELECT business_type, work_environment FROM tasks WHERE id='t1'")
        ).one()
    assert row[0] == ""
    assert row[1] == ""


def test_is_idempotent(legacy_db, monkeypatch):
    """서버는 켤 때마다 이걸 돌린다. 두 번째부터는 아무것도 안 해야 한다."""
    import database

    monkeypatch.setattr(database, "engine", legacy_db)

    assert database.apply_pending_columns()  # 1회차: 추가함
    assert database.apply_pending_columns() == []  # 2회차: 할 일 없음
    assert database.apply_pending_columns() == []


def test_skips_tables_that_do_not_exist_yet(monkeypatch):
    """빈 DB에서는 create_all이 최신 스키마로 만들므로 손댈 게 없다."""
    import database

    tmp = tempfile.mkdtemp()
    empty = create_engine(f"sqlite:///{tmp}/empty.db")
    monkeypatch.setattr(database, "engine", empty)

    assert database.apply_pending_columns() == []
