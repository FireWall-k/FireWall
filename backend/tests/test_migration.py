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
    assert second["tightened_columns"] == []
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


def _worker_login_status(engine, workplace_code: str, access_code: str) -> int:
    """마이그레이션한 엔진을 앱에 물려 근로자 로그인 응답 코드를 돌려준다."""
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    import main
    from database import get_db

    Session = sessionmaker(bind=engine)

    def _db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[get_db] = _db
    try:
        main.worker_throttle.clear()  # 다른 테스트의 실패 횟수가 남아 429가 나지 않게
        res = TestClient(main.app).post(
            "/api/auth/worker-login",
            json={"workplace_code": workplace_code, "access_code": access_code})
        return res.status_code
    finally:
        main.app.dependency_overrides.pop(get_db, None)


def test_0002_weak_prod_secret_stops_before_ddl_and_retry_succeeds(monkeypatch):
    """운영자가 JOBCARD_ENV=prod로 migrate를 돌렸는데 시크릿을 안 넘긴 경우.
    첫 실행은 멈춰야 하지만 DB를 반쯤 바꾼 채로 멈추면 안 된다(SQLite ALTER는 롤백되지 않는다).
    시크릿을 고치고 다시 돌리면 head에 도달하고 기존 코드로 로그인돼야 한다."""
    engine = _new_engine("weak_prod_secret")
    _make_full_legacy_db(engine)
    monkeypatch.setenv("JOBCARD_ENV", "production")
    monkeypatch.setenv("JOBCARD_SECRET", "too-short")

    with pytest.raises(RuntimeError, match="JOBCARD_SECRET"):
        db_migrate.migrate(engine)

    assert _current_revision(engine) == db_migrate.BASELINE_REVISION
    # 시크릿 확인이 DDL보다 먼저다 → 0002가 아무 컬럼도 남기지 않았다.
    assert "workplace_code" not in {c["name"] for c in inspect(engine).get_columns("employers")}
    assert "access_code" in {c["name"] for c in inspect(engine).get_columns("workers")}

    monkeypatch.setenv("JOBCARD_SECRET", "s" * 64)
    db_migrate.migrate(engine)

    assert db_migrate.is_at_head(engine)
    assert _diff_against_models(engine) == []
    with engine.connect() as conn:
        wp = conn.execute(text("SELECT workplace_code FROM employers WHERE id='e1'")).scalar()
    assert _worker_login_status(engine, wp, "5678") == 200


def test_0002_resumes_from_half_applied_state():
    """시크릿 확인 뒤에도 프로세스가 죽는 등으로 중간에 멈출 수 있다. 예전 버전의 0002가 남긴
    상태(사업장 코드 컬럼은 추가·일부 채움, 해시 컬럼은 다른 키로 일부 채움, 평문 컬럼 남음)에서
    다시 돌려도 duplicate column 없이 head에 도달하고, 해시는 지금 시크릿으로 다시 계산돼야 한다."""
    engine = _new_engine("half_applied")
    _make_full_legacy_db(engine)
    db_migrate.migrate(engine)
    db_migrate.downgrade(engine, db_migrate.BASELINE_REVISION)
    with engine.begin() as conn:
        conn.execute(text("UPDATE workers SET access_code = '5678' WHERE id='w1'"))
        conn.execute(text(
            "INSERT INTO employers (id, name, org_name, login_id, password_hash, created_at) "
            "VALUES ('e2', '다른', '다른 작업장', 'other', 'x', '2026-01-01 00:00:00')"))
        conn.execute(text("ALTER TABLE employers ADD COLUMN workplace_code VARCHAR"))
        conn.execute(text("UPDATE employers SET workplace_code = 'KEEP22' WHERE id='e1'"))
        conn.execute(text("ALTER TABLE workers ADD COLUMN access_code_hash VARCHAR"))
        conn.execute(text("UPDATE workers SET access_code_hash = 'stale-hash-from-other-key'"))
    assert _current_revision(engine) == db_migrate.BASELINE_REVISION

    db_migrate.upgrade_to_head(engine)

    assert db_migrate.is_at_head(engine)
    assert _diff_against_models(engine) == []
    with engine.connect() as conn:
        codes = dict(conn.execute(text("SELECT id, workplace_code FROM employers")).all())
        stored = conn.execute(text("SELECT access_code_hash FROM workers WHERE id='w1'")).scalar()
    assert codes["e1"] == "KEEP22"  # 이미 발급된 사업장 코드는 바꾸지 않는다
    assert codes["e2"] and codes["e2"] != "KEEP22"
    assert stored == hash_access_code("e1", "5678")
    assert _worker_login_status(engine, "KEEP22", "5678") == 200


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
    # NOT NULL로 조인 컬럼도 보고에 남아야 운영자가 migrate 출력에서 확인할 수 있다.
    assert set(report["tightened_columns"]) == {
        "tasks.business_type", "tasks.work_environment", "tasks.job", "steps.symbol_query"}
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


def test_manage_migrate_prints_tightened_columns(monkeypatch, capsys):
    """레거시 보정 내용은 logger.info만으로는 운영자 화면(docker compose run 출력)에 안 보인다.
    추가한 컬럼과 NOT NULL로 조인 컬럼을 표준출력에 적어야 한다."""
    import manage

    engine = _new_engine("manage_tighten")
    _make_full_legacy_db(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE tasks ADD COLUMN job VARCHAR DEFAULT ''"))
    monkeypatch.setattr(db_migrate, "default_engine", lambda: engine)
    manage.main(["migrate"])
    out = capsys.readouterr().out
    assert "tasks.business_type" in out  # 추가한 컬럼
    assert "NOT NULL" in out and "tasks.job" in out  # 조인 컬럼


def test_alembic_ini_points_at_migrations():
    """CI의 `alembic upgrade head`/`alembic check`가 쓰는 설정 파일이 리비전을 찾을 수 있어야 한다."""
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(db_migrate.alembic_config())
    assert script.get_current_head() == db_migrate.head_revision()


# --- 0003 개인정보(동의·감사·메모) ----------------------------------------------

def test_0003_existing_workers_start_with_ai_note_disallowed():
    """기존 근로자는 메모가 비어 있고 "AI에 메모 사용"이 꺼진 상태로 올라와야 한다(동의 없이 나가던 상태를 끝낸다)."""
    engine = _new_engine("privacy_0003")
    _make_full_legacy_db(engine)
    db_migrate.migrate(engine)
    db_migrate.downgrade(engine, "0002_workplace_code")
    assert "ai_note_allowed" not in {c["name"] for c in inspect(engine).get_columns("workers")}
    db_migrate.upgrade_to_head(engine)
    assert db_migrate.is_at_head(engine)
    assert _diff_against_models(engine) == []
    with engine.connect() as conn:
        row = conn.execute(text("SELECT note, ai_note_allowed FROM workers WHERE id='w1'")).one()
    assert row == ("", 0)
    assert {"worker_consents", "access_audit_logs"} <= set(inspect(engine).get_table_names())


def test_0003_resumes_when_column_already_added():
    """SQLite ALTER TABLE은 롤백되지 않는다. 컬럼 하나만 붙은 채 멈춘 상태에서 다시 돌려도 head에 도달한다."""
    engine = _new_engine("privacy_0003_half")
    db_migrate.upgrade_to_head(engine)
    db_migrate.downgrade(engine, "0002_workplace_code")
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE workers ADD COLUMN note TEXT NOT NULL DEFAULT ''"))
    db_migrate.upgrade_to_head(engine)
    assert db_migrate.is_at_head(engine)
    assert _diff_against_models(engine) == []


# --- 0004 사진·TTS 소유 레코드 -------------------------------------------------

def test_0004_moves_legacy_urls_to_owned_records(monkeypatch, tmp_path):
    """옛 절대 URL(/api/photos, /api/tts)은 소유 레코드로 옮겨지고(소유자 = 직무의 사업주), 사진은 EXIF가 지워진다.
    파일이 없는 URL(이미 깨진 링크)은 비운다."""
    from io import BytesIO

    from PIL import Image

    photo_dir, tts_dir = tmp_path / "photos", tmp_path / "tts"
    photo_dir.mkdir()
    tts_dir.mkdir()
    monkeypatch.setenv("PHOTO_DIR", str(photo_dir))
    monkeypatch.setenv("TTS_CACHE_DIR", str(tts_dir))

    exif = Image.Exif()
    exif.get_ifd(0x8825)[1] = "N"
    exif.get_ifd(0x8825)[2] = (37.0, 33.0, 59.0)
    buf = BytesIO()
    Image.new("RGB", (2000, 1000), (1, 2, 3)).save(buf, "JPEG", exif=exif)
    photo_name, tts_name = "a" * 32 + ".jpg", "b" * 32 + ".mp3"
    (photo_dir / photo_name).write_bytes(buf.getvalue())
    (tts_dir / tts_name).write_bytes(b"ID3legacy")

    engine = _new_engine("media_0004")
    _make_full_legacy_db(engine)
    db_migrate.migrate(engine)
    db_migrate.downgrade(engine, "0003_privacy")
    base = "http://localhost:8000"
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE steps SET symbol_url = :p, symbol_source = 'photo', tts_audio_url = :t WHERE id = 's1'"),
            {"p": f"{base}/api/photos/{photo_name}", "t": f"{base}/api/tts/{tts_name}"})
        conn.execute(text(
            "INSERT INTO steps (id, task_id, order_index, sentence, action_type, symbol_query, symbol_url, "
            "symbol_source, needs_fallback, tts_audio_url) VALUES ('s2', 't1', 2, '깨진 링크', 'move', '', "
            ":p, 'photo', 0, :t)"),
            {"p": f"{base}/api/photos/{'c' * 32}.png", "t": f"{base}/api/tts/{'d' * 32}.mp3"})

    db_migrate.upgrade_to_head(engine)
    assert db_migrate.is_at_head(engine)
    assert _diff_against_models(engine) == []
    assert "tts_audio_url" not in {c["name"] for c in inspect(engine).get_columns("steps")}
    with engine.connect() as conn:
        s1 = conn.execute(text("SELECT symbol_url, symbol_media_id, tts_media_id, symbol_source "
                               "FROM steps WHERE id='s1'")).one()
        s2 = conn.execute(text("SELECT symbol_url, symbol_media_id, tts_media_id, symbol_source, needs_fallback "
                               "FROM steps WHERE id='s2'")).one()
        records = {r.id: r for r in conn.execute(text(
            "SELECT id, employer_id, kind, storage_key, bytes FROM media_files")).all()}
    assert s1.symbol_url is None and s1.symbol_source == "photo"
    photo, audio = records[s1.symbol_media_id], records[s1.tts_media_id]
    assert (photo.employer_id, photo.kind, audio.employer_id, audio.kind) == ("e1", "photo", "e1", "tts")
    assert audio.storage_key == tts_name
    # 옛 사진은 메타데이터를 지운 WebP로 다시 저장되고, EXIF(GPS)가 든 원본은 그 자리에서 지워진다
    # (gc-media 유예시간 동안 촬영 위치가 디스크에 남지 않게).
    assert photo.storage_key.endswith(".webp")
    clean = Image.open(photo_dir / photo.storage_key)
    assert not dict(clean.getexif()) and max(clean.size) <= 1600
    assert not (photo_dir / photo_name).exists()
    assert sorted(p.name for p in photo_dir.iterdir()) == [photo.storage_key]  # 임시 파일도 남지 않는다
    # 파일이 없던 URL은 비우고 사진은 폴백 상태로 되돌린다.
    assert tuple(s2) == (None, None, None, "fallback", 1)


def test_0004_resumes_after_original_was_deleted(monkeypatch, tmp_path):
    """원본을 지운 뒤 DB 변경이 롤백되거나 멈춘 상태(단계는 여전히 원본 URL)에서 다시 돌려도 사진을 잃지 않는다:
    원본 이름에서 정해지는 WebP 이름으로 앞선 실행의 결과를 찾아 이어 간다."""
    from io import BytesIO

    from PIL import Image

    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    monkeypatch.setenv("PHOTO_DIR", str(photo_dir))
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path / "tts"))
    revision = db_migrate._script().get_revision("0004_media_files").module
    photo_name = "f" * 32 + ".jpg"
    done_key = revision._converted_key(photo_name)
    assert done_key == revision._converted_key(photo_name) and done_key.endswith(".webp")
    buf = BytesIO()
    Image.new("RGB", (40, 30), (9, 9, 9)).save(buf, "WEBP")
    (photo_dir / done_key).write_bytes(buf.getvalue())  # 앞선 실행이 남긴 WebP, 원본은 이미 없음

    engine = _new_engine("media_0004_resume")
    _make_full_legacy_db(engine)
    db_migrate.migrate(engine)
    db_migrate.downgrade(engine, "0003_privacy")
    with engine.begin() as conn:
        conn.execute(text("UPDATE steps SET symbol_url = :p, symbol_source = 'photo' WHERE id = 's1'"),
                     {"p": f"http://localhost:8000/api/photos/{photo_name}"})
    db_migrate.upgrade_to_head(engine)
    with engine.connect() as conn:
        key = conn.execute(text(
            "SELECT m.storage_key FROM steps s JOIN media_files m ON m.id = s.symbol_media_id "
            "WHERE s.id = 's1'")).scalar()
    assert key == done_key


def test_0004_downgrade_restores_static_urls(monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    (tmp_path / ("e" * 32 + ".mp3")).write_bytes(b"ID3")
    engine = _new_engine("media_0004_down")
    _make_full_legacy_db(engine)
    db_migrate.migrate(engine)
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO media_files (id, employer_id, kind, storage_key, sha256, bytes, created_at) "
            "VALUES ('m1', 'e1', 'tts', :k, '', 3, '2026-01-01 00:00:00')"), {"k": "e" * 32 + ".mp3"})
        conn.execute(text("UPDATE steps SET tts_media_id = 'm1' WHERE id = 's1'"))
    db_migrate.downgrade(engine, "0003_privacy")
    assert "media_files" not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        url = conn.execute(text("SELECT tts_audio_url FROM steps WHERE id='s1'")).scalar()
    assert url.endswith(f"/api/tts/{'e' * 32}.mp3")
    db_migrate.upgrade_to_head(engine)
    assert db_migrate.is_at_head(engine)
