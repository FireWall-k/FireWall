"""2a-0 버전 고정: 보낸 직무의 스냅샷(task_versions·task_version_steps), 배정의 버전·날짜, 로그·도움의 버전 단계 FK.

Revision ID: 0007_task_versions
Revises: 0006_worker_phase1
Create Date: 2026-11-09

왜:
1. 배정이 직무의 '지금' 단계(steps)를 읽어서, 사업주가 보낸 직무를 고치면 하고 있는 근로자의 화면·순서·완료 판정이
   그 자리에서 바뀌었고, 단계를 지우면 수행 로그까지 지워졌다(결정 5: 고친 내용은 다음 배정부터).
   이제 보낼 때 steps를 버전으로 복사하고, 배정은 버전(task_version_id)을, 로그·도움은 버전 단계를 가리킨다.
2. 배정의 '그 날'을 보낸 시각(assigned_date)이 아니라 scheduled_day(현지 날짜)로 둔다 — 내일로 보내기, 어제 못 끝낸
   일을 다시 보내기(예전에는 어제 배정을 재사용해 오늘 화면에 뜨지 않았다)를 위해서다.
3. tasks.updated_at(고친 날)·archived_at(보관, 2a-1), assignments의 send_batch_id·pinned_at·first_seen_at.

백필:
- 배정이 있거나 status='published'인 직무마다 지금 steps로 버전 1을 만든다. 버전 1 단계 id = 원래 step.id
  (근로자 기기의 오프라인 대기열에 남은 옛 단계 id가 그대로 맞는다), source_step_id = step.id.
- 그 직무의 배정은 모두 버전 1에 묶고 pinned_at = first_seen_at = assigned_date(이미 받았다고 본다 — 다시 보내도 옮기지 않음).
- scheduled_day = assigned_date의 현지 날짜(APP_UTC_OFFSET_HOURS, 기본 9). tasks.updated_at = created_at.

FK 대상 바꾸기: performance_logs·help_requests의 step_id FK를 task_version_steps.id로 바꾸려고 두 표를 다시 만든다
(SQLite는 FK를 바꾸는 ALTER가 없다). 다시 만든 뒤 색인을 직접 다시 만든다 — 특히 help_requests의 부분 unique
색인(uq_help_requests_one_active: 배정마다 열린 요청 하나)을 빠뜨리면 동시 요청이 두 건을 만들던 문제가 되살아난다.

downgrade(데이터 손실 있음, 명시): 버전 2 이상 단계를 가리키는 로그·도움은 source_step_id가 지금 steps에 있으면 그
id로 옮긴다. 옮길 수 없는 로그는 지우고 도움은 step_id=NULL로 둔다(지운 수를 로그로 남긴다).

0003·0006처럼 "이미 있으면 건너뜀"으로 써서 중간에 멈춘 뒤 다시 돌려도 head에 도달한다. 앱 모듈을 import하지 않는다.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007_task_versions"
down_revision: Union[str, None] = "0006_worker_phase1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("jobcard.migrate")

_HELP_INDEXES = (
    ("ix_help_requests_employer_id", ["employer_id"]),
    ("ix_help_requests_worker_id", ["worker_id"]),
    ("ix_help_requests_assignment_id", ["assignment_id"]),
    ("ix_help_requests_step_id", ["step_id"]),
    ("ix_help_requests_created_at", ["created_at"]),
    ("ix_help_requests_assignment_state", ["assignment_id", "state"]),
)
_LOG_INDEXES = (
    ("ix_performance_logs_assignment_id", ["assignment_id"]),
    ("ix_performance_logs_step_id", ["step_id"]),
)
_VERSION_STEP_INDEXES = (
    ("ix_task_version_steps_version_id", ["version_id"]),
    ("ix_task_version_steps_source_step_id", ["source_step_id"]),
    ("ix_task_version_steps_symbol_media_id", ["symbol_media_id"]),
    ("ix_task_version_steps_tts_media_id", ["tts_media_id"]),
)
_ASSIGNMENT_INDEXES = (
    ("ix_assignments_task_version_id", ["task_version_id"]),
    ("ix_assignments_send_batch_id", ["send_batch_id"]),
    ("ix_assignments_worker_day", ["worker_id", "scheduled_day"]),
)


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    # 매번 새 Inspector를 만든다(캐시된 Inspector는 DDL 뒤의 모양을 못 본다).
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def _step_fk_target(bind, table: str) -> str | None:
    for fk in sa.inspect(bind).get_foreign_keys(table):
        if fk.get("constrained_columns") == ["step_id"]:
            return fk.get("referred_table")
    return None


def _create_indexes(bind, table: str, specs) -> None:
    have = _indexes(bind, table)
    for name, cols in specs:
        if name not in have:
            op.create_index(name, table, cols)


# --- 다시 만드는 두 표의 정의(0006 모양 + step_id FK 대상만 다름) ---------------------------------

def _log_table(step_target: str) -> list:
    return [
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("assignment_id", sa.String(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("step_id", sa.String(), sa.ForeignKey(f"{step_target}.id"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("duration_sec", sa.Float(), nullable=False),
        sa.Column("replay_count", sa.Integer(), nullable=False),
        sa.Column("stuck", sa.Boolean(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("client_event_id", sa.String(length=64), nullable=True),
        sa.UniqueConstraint("assignment_id", "step_id", name="uq_log_assignment_step"),
    ]


def _help_table(step_target: str) -> list:
    return [
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("employer_id", sa.String(), sa.ForeignKey("employers.id"), nullable=False),
        sa.Column("worker_id", sa.String(), sa.ForeignKey("workers.id"), nullable=False),
        sa.Column("assignment_id", sa.String(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("step_id", sa.String(), sa.ForeignKey(f"{step_target}.id"), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("resolution", sa.String(), nullable=True),
        sa.Column("client_request_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    ]


def _help_indexes_after_rebuild(bind) -> None:
    _create_indexes(bind, "help_requests", _HELP_INDEXES)
    have = _indexes(bind, "help_requests")
    if "uq_help_requests_assignment_client" not in have:
        op.create_index("uq_help_requests_assignment_client", "help_requests",
                        ["assignment_id", "client_request_id"], unique=True)
    if "uq_help_requests_one_active" not in have:
        # models.HelpRequest와 같은 조건(배정마다 열린 요청 하나).
        where = sa.text("state IN ('open', 'acknowledged')")
        op.create_index("uq_help_requests_one_active", "help_requests", ["assignment_id"], unique=True,
                        sqlite_where=where, postgresql_where=where)


def _rebuild(bind, table: str, step_target: str) -> None:
    """table을 step_id FK 대상이 step_target인 같은 모양 표로 다시 만든다(데이터 그대로). 이미 그렇다면 건너뛴다.

    중간에 멈춘 경우: 임시 표만 있으면(원래 표를 지운 뒤 멈춤) 이름만 바꾸고, 둘 다 있으면 임시 표를 지우고 다시 한다.
    """
    tmp = f"_{table}_0007"
    tables = _tables(bind)
    if table not in tables and tmp in tables:
        op.rename_table(tmp, table)
        tables = _tables(bind)
    if table in tables and _step_fk_target(bind, table) == step_target:
        if tmp in tables:
            op.drop_table(tmp)
        return
    if tmp in tables:
        op.drop_table(tmp)
    factory = _log_table if table == "performance_logs" else _help_table
    items = factory(step_target)
    op.create_table(tmp, *items)
    names = ", ".join(c.name for c in items if isinstance(c, sa.Column))
    bind.execute(sa.text(f"INSERT INTO {tmp} ({names}) SELECT {names} FROM {table}"))
    op.drop_table(table)  # 이 표의 색인도 함께 지워진다 — 아래에서 직접 다시 만든다
    op.rename_table(tmp, table)


def _rebuild_logs_and_help(bind, step_target: str) -> None:
    _rebuild(bind, "performance_logs", step_target)
    _create_indexes(bind, "performance_logs", _LOG_INDEXES)
    _rebuild(bind, "help_requests", step_target)
    _help_indexes_after_rebuild(bind)


def upgrade() -> None:
    bind = op.get_bind()
    offset = int(os.getenv("APP_UTC_OFFSET_HOURS", "9"))
    # SQLAlchemy가 SQLite DateTime을 저장하는 글자 모양 그대로 넣는다(sqlite3 기본 datetime 변환기는 3.12부터 사라질 예정).
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

    # --- 1. 버전 표 ---------------------------------------------------------------------
    tables = _tables(bind)
    if "task_versions" not in tables:
        op.create_table(
            "task_versions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False),
            sa.Column("version_no", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=True),
            sa.UniqueConstraint("task_id", "version_no", name="uq_task_versions_task_no"),
        )
    _create_indexes(bind, "task_versions", (("ix_task_versions_task_id", ["task_id"]),))
    if "task_version_steps" not in tables:
        op.create_table(
            "task_version_steps",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("version_id", sa.String(), sa.ForeignKey("task_versions.id"), nullable=False),
            sa.Column("source_step_id", sa.String(), nullable=True),
            sa.Column("order_index", sa.Integer(), nullable=False),
            sa.Column("sentence", sa.Text(), nullable=False),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("symbol_query", sa.Text(), nullable=False),
            sa.Column("symbol_url", sa.String(), nullable=True),
            sa.Column("symbol_source", sa.String(), nullable=False),
            sa.Column("symbol_media_id", sa.String(), sa.ForeignKey("media_files.id"), nullable=True),
            sa.Column("tts_media_id", sa.String(), sa.ForeignKey("media_files.id"), nullable=True),
            sa.UniqueConstraint("version_id", "order_index", name="uq_task_version_steps_order"),
        )
    _create_indexes(bind, "task_version_steps", _VERSION_STEP_INDEXES)

    # --- 2. 직무: 지금 버전·고친 날·보관 -------------------------------------------------
    cols = _columns(bind, "tasks")
    missing = [n for n in ("current_version_id", "updated_at", "archived_at") if n not in cols]
    if missing:
        with op.batch_alter_table("tasks") as batch:
            if "current_version_id" in missing:
                batch.add_column(sa.Column("current_version_id", sa.String(), nullable=True))
            if "updated_at" in missing:
                batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=True))
            if "archived_at" in missing:
                batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
    # 아주 예전 설치본은 created_at이 비어 있을 수 있다(그럴 때만 지금 시각).
    bind.execute(sa.text("UPDATE tasks SET updated_at = COALESCE(created_at, :now) WHERE updated_at IS NULL"),
                 {"now": now})
    if any(c["name"] == "updated_at" and c["nullable"] for c in sa.inspect(bind).get_columns("tasks")):
        with op.batch_alter_table("tasks") as batch:
            batch.alter_column("updated_at", existing_type=sa.DateTime(), nullable=False)

    # --- 3. 배정: 버전·묶음·날짜·고정 시각·처음 받은 시각 ---------------------------------
    cols = _columns(bind, "assignments")
    new_cols = {
        "task_version_id": lambda: sa.Column("task_version_id", sa.String(),
                                             sa.ForeignKey("task_versions.id",
                                                           name="fk_assignments_task_version_id"),
                                             nullable=True),
        "send_batch_id": lambda: sa.Column("send_batch_id", sa.String(), nullable=True),
        "scheduled_day": lambda: sa.Column("scheduled_day", sa.Date(), nullable=True),
        "pinned_at": lambda: sa.Column("pinned_at", sa.DateTime(), nullable=True),
        "first_seen_at": lambda: sa.Column("first_seen_at", sa.DateTime(), nullable=True),
    }
    missing = [n for n in new_cols if n not in cols]
    if missing:
        with op.batch_alter_table("assignments") as batch:
            for n in missing:
                batch.add_column(new_cols[n]())
    bind.execute(sa.text("UPDATE assignments SET scheduled_day = COALESCE(date(assigned_date, :mod), "
                         "date(:now, :mod)) WHERE scheduled_day IS NULL"),
                 {"mod": f"{offset:+d} hours", "now": now})
    if any(c["name"] == "scheduled_day" and c["nullable"] for c in sa.inspect(bind).get_columns("assignments")):
        with op.batch_alter_table("assignments") as batch:
            batch.alter_column("scheduled_day", existing_type=sa.Date(), nullable=False)
    _create_indexes(bind, "assignments", _ASSIGNMENT_INDEXES)

    # --- 4. 백필: 보냈거나 배정한 직무마다 버전 1 = 지금 steps -------------------------------
    rows = bind.execute(sa.text(
        "SELECT t.id, t.title, t.employer_id FROM tasks t "
        "WHERE (t.status = 'published' OR EXISTS (SELECT 1 FROM assignments a WHERE a.task_id = t.id)) "
        "AND NOT EXISTS (SELECT 1 FROM task_versions v WHERE v.task_id = t.id)")).all()
    if rows:
        bind.execute(sa.text(
            "INSERT INTO task_versions (id, task_id, version_no, title, created_at, created_by) "
            "VALUES (:id, :task_id, 1, :title, :now, :by)"),
            [{"id": str(uuid.uuid4()), "task_id": r[0], "title": r[1] or "", "now": now, "by": r[2]}
             for r in rows])
    # 버전 단계 id = 원래 step.id. 순서는 1..N으로 다시 매긴다(혹시 겹친 order_index가 있어도 unique에 걸리지 않게).
    bind.execute(sa.text(
        "INSERT INTO task_version_steps (id, version_id, source_step_id, order_index, sentence, action_type, "
        "symbol_query, symbol_url, symbol_source, symbol_media_id, tts_media_id) "
        "SELECT s.id, v.id, s.id, ROW_NUMBER() OVER (PARTITION BY s.task_id ORDER BY s.order_index, s.id), "
        "s.sentence, s.action_type, COALESCE(s.symbol_query, ''), s.symbol_url, s.symbol_source, "
        "s.symbol_media_id, s.tts_media_id "
        "FROM steps s JOIN task_versions v ON v.task_id = s.task_id AND v.version_no = 1 "
        "WHERE NOT EXISTS (SELECT 1 FROM task_version_steps x WHERE x.version_id = v.id)"))
    bind.execute(sa.text(
        "UPDATE tasks SET current_version_id = (SELECT v.id FROM task_versions v WHERE v.task_id = tasks.id "
        "ORDER BY v.version_no DESC LIMIT 1) WHERE current_version_id IS NULL "
        "AND EXISTS (SELECT 1 FROM task_versions v WHERE v.task_id = tasks.id)"))
    bind.execute(sa.text(
        "UPDATE assignments SET task_version_id = (SELECT v.id FROM task_versions v "
        "WHERE v.task_id = assignments.task_id AND v.version_no = 1), "
        "pinned_at = assigned_date, first_seen_at = assigned_date "
        "WHERE task_version_id IS NULL "
        "AND EXISTS (SELECT 1 FROM task_versions v WHERE v.task_id = assignments.task_id AND v.version_no = 1)"))
    left = bind.execute(sa.text("SELECT COUNT(*) FROM assignments WHERE task_version_id IS NULL")).scalar()
    if left:
        # 직무가 지워진 고아 배정뿐이다(delete_task가 배정을 함께 지우므로 정상 DB에는 없다).
        logger.warning("0007: 버전을 찾지 못한 배정 %d건(직무 없음) — 앱은 task.steps로 대신 읽는다", left)

    # --- 5. 로그·도움의 step_id → 버전 단계 ------------------------------------------------
    _rebuild_logs_and_help(bind, "task_version_steps")


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)

    if "task_version_steps" in tables:
        # 1) 버전 단계를 가리키는 로그·도움을 원래 단계(source_step_id)로 옮긴다. 백필 버전 1은 id가 같아 그대로다.
        remap = ("UPDATE {or_ignore} {t} SET step_id = (SELECT vs.source_step_id FROM task_version_steps vs "
                 "WHERE vs.id = {t}.step_id) "
                 "WHERE step_id IS NOT NULL AND step_id NOT IN (SELECT id FROM steps) "
                 "AND EXISTS (SELECT 1 FROM task_version_steps vs JOIN steps s ON s.id = vs.source_step_id "
                 "WHERE vs.id = {t}.step_id)")
        if "performance_logs" in tables:
            # 같은 배정이 같은 원래 단계를 두 번 가리키면(드묾) 먼저 옮긴 한 건만 남기고 나머지는 아래에서 지운다.
            bind.execute(sa.text(remap.format(or_ignore="OR IGNORE", t="performance_logs")))
            dropped = bind.execute(sa.text(
                "SELECT COUNT(*) FROM performance_logs WHERE step_id NOT IN (SELECT id FROM steps)")).scalar()
            if dropped:
                bind.execute(sa.text("DELETE FROM performance_logs WHERE step_id NOT IN (SELECT id FROM steps)"))
                logger.warning("0007 downgrade: 원래 단계를 찾지 못한 수행 로그 %d건을 지웠다", dropped)
        if "help_requests" in tables:
            bind.execute(sa.text(remap.format(or_ignore="", t="help_requests")))
            cut = bind.execute(sa.text(
                "SELECT COUNT(*) FROM help_requests WHERE step_id IS NOT NULL "
                "AND step_id NOT IN (SELECT id FROM steps)")).scalar()
            if cut:
                bind.execute(sa.text("UPDATE help_requests SET step_id = NULL WHERE step_id IS NOT NULL "
                                     "AND step_id NOT IN (SELECT id FROM steps)"))
                logger.warning("0007 downgrade: 원래 단계를 찾지 못한 도움 요청 %d건의 단계를 비웠다", cut)

    # 2) 두 표를 steps FK로 다시 만든다(색인 직접 재생성).
    _rebuild_logs_and_help(bind, "steps")

    # 3) 배정·직무의 새 칸, 버전 표를 지운다.
    have = _indexes(bind, "assignments")
    for name, _ in _ASSIGNMENT_INDEXES:
        if name in have:
            op.drop_index(name, table_name="assignments")
    cols = _columns(bind, "assignments")
    drop = [n for n in ("first_seen_at", "pinned_at", "scheduled_day", "send_batch_id", "task_version_id")
            if n in cols]
    if drop:
        with op.batch_alter_table("assignments") as batch:
            if "task_version_id" in drop:
                fks = [fk for fk in sa.inspect(bind).get_foreign_keys("assignments")
                       if fk.get("constrained_columns") == ["task_version_id"] and fk.get("name")]
                for fk in fks:
                    batch.drop_constraint(fk["name"], type_="foreignkey")
            for n in drop:
                batch.drop_column(n)
    cols = _columns(bind, "tasks")
    drop = [n for n in ("archived_at", "updated_at", "current_version_id") if n in cols]
    if drop:
        with op.batch_alter_table("tasks") as batch:
            for n in drop:
                batch.drop_column(n)
    tables = _tables(bind)
    if "task_version_steps" in tables:
        op.drop_table("task_version_steps")
    if "task_versions" in tables:
        op.drop_table("task_versions")
