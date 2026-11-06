"""baseline: Alembic 도입 시점(2026-11)의 스키마.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-06

models.py를 autogenerate로 옮긴 뒤 손으로 다듬었다. 테이블 정의를 op.create_table 나열 대신
build_metadata()로 묶은 이유: Alembic 도입 전 설치본(alembic_version 없음)을 받아들일 때
db_migrate.adopt_legacy_db()가 "빠진 테이블만" 이 baseline 정의 그대로 만들어야 한다.
그때 현재 models.py(나중에 계속 바뀐다)를 쓰면 baseline보다 새 모양의 테이블이 생기고,
stamp 뒤 이어지는 리비전이 이미 있는 컬럼을 또 추가하다 실패한다. 그래서 여기 정의는 고정이다.

이 파일은 절대 고치지 않는다. 스키마를 바꾸려면 새 리비전을 만든다:
    alembic revision --autogenerate -m "설명"
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def build_metadata() -> sa.MetaData:
    """baseline 시점의 테이블·인덱스·제약 정의(고정)."""
    md = sa.MetaData()
    sa.Table(
        "employers", md,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("org_name", sa.String(), nullable=False),
        sa.Column("login_id", sa.String(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Index("ix_employers_login_id", "login_id", unique=True),
    )
    sa.Table(
        "tasks", md,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("employer_id", sa.String(), sa.ForeignKey("employers.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("raw_input", sa.Text(), nullable=False),
        sa.Column("business_type", sa.String(), nullable=False),
        sa.Column("work_environment", sa.String(), nullable=False),
        sa.Column("job", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Index("ix_tasks_employer_id", "employer_id"),
    )
    sa.Table(
        "workers", md,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("employer_id", sa.String(), sa.ForeignKey("employers.id"), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("access_code", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Index("ix_workers_access_code", "access_code", unique=True),
        sa.Index("ix_workers_employer_id", "employer_id"),
    )
    sa.Table(
        "assignments", md,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("worker_id", sa.String(), sa.ForeignKey("workers.id"), nullable=False),
        sa.Column("assigned_date", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Index("ix_assignments_assigned_date", "assigned_date"),
        sa.Index("ix_assignments_task_id", "task_id"),
        sa.Index("ix_assignments_worker_id", "worker_id"),
    )
    sa.Table(
        "steps", md,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("task_id", sa.String(), sa.ForeignKey("tasks.id"), nullable=False),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("sentence", sa.Text(), nullable=False),
        sa.Column("action_type", sa.String(), nullable=False),
        sa.Column("symbol_query", sa.Text(), nullable=False),
        sa.Column("symbol_url", sa.String(), nullable=True),
        sa.Column("symbol_source", sa.String(), nullable=False),
        sa.Column("needs_fallback", sa.Boolean(), nullable=False),
        sa.Column("tts_audio_url", sa.String(), nullable=True),
        sa.Index("ix_steps_task_id", "task_id"),
    )
    sa.Table(
        "performance_logs", md,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("assignment_id", sa.String(), sa.ForeignKey("assignments.id"), nullable=False),
        sa.Column("step_id", sa.String(), sa.ForeignKey("steps.id"), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("duration_sec", sa.Float(), nullable=False),
        sa.Column("replay_count", sa.Integer(), nullable=False),
        sa.Column("stuck", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("assignment_id", "step_id", name="uq_log_assignment_step"),
        sa.Index("ix_performance_logs_assignment_id", "assignment_id"),
        sa.Index("ix_performance_logs_step_id", "step_id"),
    )
    return md


def upgrade() -> None:
    build_metadata().create_all(bind=op.get_bind())


def downgrade() -> None:
    build_metadata().drop_all(bind=op.get_bind())
