"""스키마 마이그레이션(Alembic) 테스트.

세 가지를 지킨다.
1. 빈 DB에서 `upgrade head`만으로 모델(models.py)과 똑같은 스키마가 나온다
   (리비전을 빠뜨리고 모델만 고치면 여기서 깨진다 — CI의 `alembic check`와 같은 검사).
2. Alembic 도입 전 설치본(jobcard-data 볼륨의 SQLite: alembic_version 없음, 일부 컬럼 없음)이
   `manage.py migrate` 한 번으로 데이터를 잃지 않고 head에 도달한다.
3. 레거시 보정(repair_legacy_columns)은 예전 apply_pending_columns()가 하던 일을 그대로 한다:
   없는 컬럼만 추가하고, 기존 행에 쓸 수 있는 기본값을 채우고, 여러 번 돌려도 안전하다.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from alembic.autogenerate import compare_metadata  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from sqlalchemy import create_engine, inspect, text  # noqa: E402

import db_migrate  # noqa: E402
from auth import hash_access_code  # noqa: E402
import models  # noqa: E402,F401  (Base.metadata에 테이블을 등록한다)
from database import Base  # noqa: E402


def _new_engine(name: str):
    tmp = tempfile.mkdtemp()
    return create_engine(f"sqlite:///{tmp}/{name}.db")


def _current_revision(engine):
    with engine.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def _diff_against_models(engine) -> list:
    with engine.connect() as conn:
        return compare_metadata(
            MigrationContext.configure(conn, opts={"render_as_batch": True}),
            Base.metadata,
        )


# --- 1. 빈 DB → head ---------------------------------------------------------

def test_upgrade_head_on_empty_db_matches_models():
    engine = _new_engine("empty")
    db_migrate.upgrade_to_head(engine)

    assert _current_revision(engine) == db_migrate.head_revision()
    diff = _diff_against_models(engine)
    assert diff == [], f"모델과 마이그레이션이 어긋남: {diff}"


def test_migrate_on_empty_db_reaches_head():
    engine = _new_engine("empty2")
    report = db_migrate.migrate(engine)
    assert report["adopted_legacy"] is False
    assert db_migrate.is_at_head(engine)


def test_downgrade_base_then_upgrade_again():
    """baseline의 downgrade가 깨져 있으면 리비전을 되돌릴 수 없다."""
    engine = _new_engine("roundtrip")
    db_migrate.upgrade_to_head(engine)
    db_migrate.downgrade(engine, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    db_migrate.upgrade_to_head(engine)
    assert db_migrate.is_at_head(engine)


# --- 2. 레거시 설치본 → 보정 → stamp → head ----------------------------------

def _make_full_legacy_db(engine) -> None:
    """Alembic 도입 전 create_all()로 만들어졌고, 컬럼 추가분(business_type 등)이 아직 없는 DB."""
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE employers (
                id VARCHAR NOT NULL PRIMARY KEY, name VARCHAR NOT NULL, org_name VARCHAR NOT NULL,
                login_id VARCHAR NOT NULL, password_hash VARCHAR NOT NULL,
                created_at DATETIME NOT NULL
            )"""))
        conn.execute(text("CREATE UNIQUE INDEX ix_employers_login_id ON employers (login_id)"))
        conn.execute(text("""
            CREATE TABLE workers (
                id VARCHAR NOT NULL PRIMARY KEY,
                employer_id VARCHAR NOT NULL REFERENCES employers(id),
                display_name VARCHAR NOT NULL, access_code VARCHAR NOT NULL,
                created_at DATETIME NOT NULL
            )"""))
        conn.execute(text("CREATE INDEX ix_workers_employer_id ON workers (employer_id)"))
        conn.execute(text("CREATE UNIQUE INDEX ix_workers_access_code ON workers (access_code)"))
        conn.execute(text("""
            CREATE TABLE tasks (
                id VARCHAR NOT NULL PRIMARY KEY,
                employer_id VARCHAR NOT NULL REFERENCES employers(id),
                title VARCHAR NOT NULL, raw_input TEXT NOT NULL, status VARCHAR NOT NULL,
                created_at DATETIME NOT NULL
            )"""))
        conn.execute(text("CREATE INDEX ix_tasks_employer_id ON tasks (employer_id)"))
        conn.execute(text("""
            CREATE TABLE steps (
                id VARCHAR NOT NULL PRIMARY KEY, task_id VARCHAR NOT NULL REFERENCES tasks(id),
                order_index INTEGER NOT NULL, sentence TEXT NOT NULL, action_type VARCHAR NOT NULL,
                symbol_url VARCHAR, symbol_source VARCHAR NOT NULL,
                needs_fallback BOOLEAN NOT NULL, tts_audio_url VARCHAR
            )"""))
        conn.execute(text("CREATE INDEX ix_steps_task_id ON steps (task_id)"))
        conn.execute(text("""
            CREATE TABLE assignments (
                id VARCHAR NOT NULL PRIMARY KEY, task_id VARCHAR NOT NULL REFERENCES tasks(id),
                worker_id VARCHAR NOT NULL REFERENCES workers(id),
                assigned_date DATETIME NOT NULL, status VARCHAR NOT NULL
            )"""))
        conn.execute(text("CREATE INDEX ix_assignments_task_id ON assignments (task_id)"))
        conn.execute(text("CREATE INDEX ix_assignments_worker_id ON assignments (worker_id)"))
        conn.execute(text(
            "CREATE INDEX ix_assignments_assigned_date ON assignments (assigned_date)"))
        conn.execute(text("""
            CREATE TABLE performance_logs (
                id VARCHAR NOT NULL PRIMARY KEY,
                assignment_id VARCHAR NOT NULL REFERENCES assignments(id),
                step_id VARCHAR NOT NULL REFERENCES steps(id), completed_at DATETIME NOT NULL,
                duration_sec FLOAT NOT NULL, replay_count INTEGER NOT NULL, stuck BOOLEAN NOT NULL,
                CONSTRAINT uq_log_assignment_step UNIQUE (assignment_id, step_id)
            )"""))
        conn.execute(text(
            "CREATE INDEX ix_performance_logs_assignment_id ON performance_logs (assignment_id)"))
        conn.execute(text(
            "CREATE INDEX ix_performance_logs_step_id ON performance_logs (step_id)"))

        conn.execute(text(
            "INSERT INTO employers (id, name, org_name, login_id, password_hash, created_at) "
            "VALUES ('e1', '사장님', '잇다', 'itda', 'x', '2026-01-01 00:00:00')"))
        conn.execute(text(
            "INSERT INTO workers (id, employer_id, display_name, access_code, created_at) "
            "VALUES ('w1', 'e1', '김근로', '5678', '2026-01-01 00:00:00')"))
        conn.execute(text(
            "INSERT INTO tasks (id, employer_id, title, raw_input, status, created_at) "
            "VALUES ('t1', 'e1', '예전 직무', '상자를 옮기세요', 'published', "
            "'2026-01-01 00:00:00')"))
        conn.execute(text(
            "INSERT INTO steps (id, task_id, order_index, sentence, action_type, "
            "symbol_source, needs_fallback) "
            "VALUES ('s1', 't1', 1, '상자를 옮기세요', 'move', 'fallback', 0)"))


def test_migrate_adopts_legacy_db_and_keeps_data():
    engine = _new_engine("legacy_full")
    _make_full_legacy_db(engine)
    assert _current_revision(engine) is None

    report = db_migrate.migrate(engine)

    assert report["adopted_legacy"] is True
    assert "tasks.business_type" in report["repaired_columns"]
    assert "steps.symbol_query" in report["repaired_columns"]
    assert db_migrate.is_at_head(engine)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title FROM tasks WHERE id='t1'")).scalar() == "예전 직무"
        assert conn.execute(text("SELECT business_type FROM tasks WHERE id='t1'")).scalar() == ""
        assert conn.execute(text("SELECT symbol_query FROM steps WHERE id='s1'")).scalar() == ""
        # 0002부터 평문 코드는 해시로 바뀐다. 데이터를 잃지 않았다 = 같은 코드로 계산한 해시가 남아 있다.
        row = conn.execute(text("SELECT access_code_hash, access_code_hint, access_code_length "
                                "FROM workers WHERE id='w1'")).one()
        assert tuple(row) == (hash_access_code("e1", "5678"), "78", 4)
    diff = _diff_against_models(engine)
    assert diff == [], f"레거시 보정 후에도 모델과 어긋남: {diff}"


def test_migrate_is_idempotent_on_legacy_db():
    engine = _new_engine("legacy_twice")
    _make_full_legacy_db(engine)
    db_migrate.migrate(engine)
    second = db_migrate.migrate(engine)
    assert second["adopted_legacy"] is False
    assert second["repaired_columns"] == []
    assert db_migrate.is_at_head(engine)


def test_legacy_plaintext_codes_still_log_in_after_migration():
    """Phase 0.1 완료 기준: 평문 코드를 쓰던 설치본을 migrate한 뒤에도 근로자는 원래 코드로 들어간다
    (사업장 코드는 마이그레이션이 새로 발급한 것). 평문 컬럼은 남지 않는다."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    import main
    from database import get_db

    engine = _new_engine("legacy_login")
    _make_full_legacy_db(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO employers (id, name, org_name, login_id, password_hash, created_at) "
            "VALUES ('e2', '다른', '다른 작업장', 'other', 'x', '2026-01-01 00:00:00')"))
        conn.execute(text(
            "INSERT INTO workers (id, employer_id, display_name, access_code, created_at) "
            "VALUES ('w2', 'e2', '박근로', '246802', '2026-01-01 00:00:00')"))

    db_migrate.migrate(engine)

    assert "access_code" not in {c["name"] for c in inspect(engine).get_columns("workers")}
    with engine.connect() as conn:
        codes = dict(conn.execute(text("SELECT id, workplace_code FROM employers")).all())
    assert set(codes) == {"e1", "e2"} and codes["e1"] != codes["e2"]
    for wp in codes.values():
        assert len(wp) == 6 and wp.isalnum() and not set(wp) & set("0O1I")

    Session = sessionmaker(bind=engine)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = _db
    try:
        # lifespan(시드·스키마 확인)은 테스트 공용 DB를 보므로 여기서는 띄우지 않는다.
        c = TestClient(main.app)
        ok = c.post("/api/auth/worker-login", json={"workplace_code": codes["e1"], "access_code": "5678"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["display_name"] == "김근로"
        # 다른 사업장 코드로는 같은 근로자 코드가 통하지 않는다.
        cross = c.post("/api/auth/worker-login",
                       json={"workplace_code": codes["e2"], "access_code": "5678"})
        assert cross.status_code == 401
        assert c.post("/api/auth/worker-login",
                      json={"workplace_code": codes["e2"], "access_code": "246802"}).status_code == 200
    finally:
        main.app.dependency_overrides.pop(get_db, None)


def test_downgrade_0002_restores_baseline_shape_without_plaintext():
    """0002 downgrade는 평문을 되살릴 수 없으므로 추측 불가능한 값(근로자 id)으로 채운다."""
    engine = _new_engine("down_0002")
    _make_full_legacy_db(engine)
    db_migrate.migrate(engine)
    db_migrate.downgrade(engine, db_migrate.BASELINE_REVISION)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT access_code FROM workers WHERE id='w1'")).scalar() == "w1"
    assert "workplace_code" not in {c["name"] for c in inspect(engine).get_columns("employers")}
    db_migrate.upgrade_to_head(engine)
    assert db_migrate.is_at_head(engine)
    assert _diff_against_models(engine) == []


def test_columns_added_nullable_by_old_code_become_not_null():
    """예전 apply_pending_columns()는 NULL 허용으로 컬럼을 붙였다. 그런 설치본도 stamp 뒤
    모델과 차이가 없어야 한다(안 그러면 이후 autogenerate·alembic check가 매번 차이를 보고한다)."""
    engine = _new_engine("legacy_nullable")
    _make_full_legacy_db(engine)
    with engine.begin() as conn:
        # 예전 database._ADDED_COLUMNS의 DDL 그대로.
        for table, col, ddl in [("tasks", "business_type", "VARCHAR DEFAULT ''"),
                                ("tasks", "work_environment", "VARCHAR DEFAULT ''"),
                                ("tasks", "job", "VARCHAR DEFAULT ''"),
                                ("steps", "symbol_query", "TEXT DEFAULT ''")]:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}"))
        conn.execute(text("UPDATE tasks SET job = NULL WHERE id='t1'"))

    report = db_migrate.migrate(engine)

    assert report["adopted_legacy"] is True
    assert report["repaired_columns"] == []
    assert db_migrate.is_at_head(engine)
    assert _diff_against_models(engine) == []
    with engine.connect() as conn:
        assert conn.execute(text("SELECT job FROM tasks WHERE id='t1'")).scalar() == ""
        assert conn.execute(text("SELECT title FROM tasks WHERE id='t1'")).scalar() == "예전 직무"
    idx = {i["name"] for i in inspect(engine).get_indexes("tasks")}
    assert "ix_tasks_employer_id" in idx  # 테이블 재생성 후에도 인덱스가 남아 있다


def test_legacy_db_missing_a_whole_table_gets_it():
    """아주 예전 설치본은 테이블 자체가 없을 수 있다(예: performance_logs). 빠진 테이블도 만들어야 한다."""
    engine = _new_engine("legacy_partial")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE tasks (
                id VARCHAR PRIMARY KEY, employer_id VARCHAR, title VARCHAR,
                raw_input TEXT, status VARCHAR, created_at DATETIME
            )"""))
        conn.execute(text(
            "INSERT INTO tasks (id, employer_id, title, raw_input, status) "
            "VALUES ('t1', 'e1', '예전 직무', '상자를 옮기세요', 'draft')"))

    report = db_migrate.migrate(engine)

    assert report["adopted_legacy"] is True
    assert db_migrate.is_at_head(engine)
    tables = set(inspect(engine).get_table_names())
    assert {"employers", "workers", "steps", "assignments", "performance_logs"} <= tables
    with engine.connect() as conn:
        assert conn.execute(text("SELECT title FROM tasks WHERE id='t1'")).scalar() == "예전 직무"


# --- 3. 레거시 컬럼 보정 (예전 apply_pending_columns 테스트를 그대로 옮김) -----

@pytest.fixture()
def legacy_db():
    """business_type/work_environment가 없던 시절의 tasks 테이블을 만든다."""
    engine = _new_engine("legacy")
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


def test_adds_missing_columns_to_existing_table(legacy_db):
    before = {c["name"] for c in inspect(legacy_db).get_columns("tasks")}
    assert "business_type" not in before

    applied = db_migrate.repair_legacy_columns(legacy_db)

    assert "tasks.business_type" in applied
    assert "tasks.work_environment" in applied
    after = {c["name"] for c in inspect(legacy_db).get_columns("tasks")}
    assert {"business_type", "work_environment"} <= after


def test_adds_step_symbol_query_column(legacy_db):
    """steps 테이블에도 symbol_query 컬럼을 추가해야 한다(구 DB에서 후보 조회가 안 깨지게)."""
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

    applied = db_migrate.repair_legacy_columns(legacy_db)
    assert "steps.symbol_query" in applied
    with legacy_db.connect() as conn:
        val = conn.execute(text("SELECT symbol_query FROM steps WHERE id='s1'")).scalar()
    assert val == ""


def test_existing_rows_get_a_usable_default(legacy_db):
    """기존 행이 NULL로 남으면 안 된다 — 검색 맥락으로 그대로 쓰이기 때문."""
    db_migrate.repair_legacy_columns(legacy_db)

    with legacy_db.connect() as conn:
        row = conn.execute(
            text("SELECT business_type, work_environment FROM tasks WHERE id='t1'")
        ).one()
    assert row[0] == ""
    assert row[1] == ""


def test_is_idempotent(legacy_db):
    """두 번째부터는 아무것도 안 해야 한다."""
    assert db_migrate.repair_legacy_columns(legacy_db)  # 1회차: 추가함
    assert db_migrate.repair_legacy_columns(legacy_db) == []  # 2회차: 할 일 없음
    assert db_migrate.repair_legacy_columns(legacy_db) == []


def test_skips_tables_that_do_not_exist_yet():
    """빈 DB에서는 baseline 리비전이 최신 스키마로 만들므로 손댈 게 없다."""
    assert db_migrate.repair_legacy_columns(_new_engine("empty3")) == []


# --- 4. 기동 시 스키마 확인 (lifespan) ----------------------------------------

def test_prod_refuses_to_start_on_unmigrated_db():
    """운영에서는 요청 프로세스가 스키마를 바꾸지 않는다. head가 아니면 이유를 말하고 멈춘다."""
    engine = _new_engine("prod_unmigrated")
    with pytest.raises(RuntimeError, match="manage.py migrate"):
        db_migrate.ensure_schema_ready(engine, production=True)
    assert inspect(engine).get_table_names() == []  # 아무것도 건드리지 않았다


def test_prod_starts_on_migrated_db():
    engine = _new_engine("prod_migrated")
    db_migrate.migrate(engine)
    db_migrate.ensure_schema_ready(engine, production=True)  # 예외 없음


def test_dev_auto_upgrades_on_start():
    engine = _new_engine("dev_auto")
    db_migrate.ensure_schema_ready(engine, production=False)
    assert db_migrate.is_at_head(engine)


def test_manage_migrate_command(monkeypatch, capsys):
    import manage

    engine = _new_engine("manage_cmd")
    monkeypatch.setattr(db_migrate, "default_engine", lambda: engine)
    manage.main(["migrate"])
    assert db_migrate.is_at_head(engine)
    assert db_migrate.head_revision() in capsys.readouterr().out


def test_alembic_ini_points_at_migrations():
    """CI의 `alembic upgrade head`/`alembic check`가 쓰는 설정 파일이 리비전을 찾을 수 있어야 한다."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(db_migrate.alembic_config())
    assert script.get_current_head() == db_migrate.head_revision()
