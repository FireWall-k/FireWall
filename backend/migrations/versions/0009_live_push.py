"""오늘 현황과 도움(2c): 근로자 지금 단계, [이전] 누름 수, 웹 푸시 구독, 측정 이벤트.

Revision ID: 0009_live_push
Revises: 0007_task_versions (병합 때 0008_step_review 뒤로 다시 잇는다 — contract §5.1)
Create Date: 2026-11-10

왜:
1. worker_presence: 사업주 홈(GET /api/employer/live)이 근로자마다 '지금 단계'·머문 시간·다시 듣기를 보고 막힘 의심과
   연결 끊김을 서버에서 판정한다(예전에는 근로자 화면 StepPlayer가 120초를 혼자 셌다). 근로자마다 한 줄을 덮어쓴다.
2. performance_logs.prev_count: 단계마다 [이전]을 누른 수(타임라인·코칭 신호). 옛 행은 0.
3. push_subscriptions: 도움 요청을 사업주 기기에 웹 푸시로 알린다(내용에 근로자 이름 없음).
4. client_events: 명세 8.4 측정 이벤트. 이름·문장 같은 개인정보 칸이 없다.

0006·0007처럼 "이미 있으면 건너뜀"으로 써서 중간에 멈춘 뒤 다시 돌려도 head에 닿는다. 앱 모듈을 import하지 않는다.
downgrade는 새 표 셋과 prev_count를 지운다(측정 이벤트·구독·지금 단계는 사라진다. 수행 로그 행은 남는다).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009_live_push"
# 2b-1의 0008_step_review가 이 가지에 없어서 지금 head(0007)에 잇는다. 병합 때 "0008_step_review"로 바꾼다.
down_revision: Union[str, None] = "0007_task_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)

    if "worker_presence" not in tables:
        op.create_table(
            "worker_presence",
            sa.Column("worker_id", sa.String(), sa.ForeignKey("workers.id"), primary_key=True),
            sa.Column("assignment_id", sa.String(), nullable=True),
            sa.Column("step_id", sa.String(), nullable=True),
            sa.Column("step_started_at", sa.DateTime(), nullable=True),
            sa.Column("replay_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("prev_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )

    if "prev_count" not in _columns(bind, "performance_logs"):
        # SQLite ADD COLUMN은 표를 다시 만들지 않는다(색인·부분 unique가 그대로 남는다).
        op.execute(sa.text("ALTER TABLE performance_logs ADD COLUMN prev_count INTEGER NOT NULL DEFAULT 0"))

    if "push_subscriptions" not in tables:
        op.create_table(
            "push_subscriptions",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("employer_id", sa.String(), sa.ForeignKey("employers.id"), nullable=False),
            sa.Column("endpoint", sa.String(), nullable=False),
            sa.Column("p256dh", sa.String(), nullable=False),
            sa.Column("auth", sa.String(), nullable=False),
            sa.Column("user_agent", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("last_ok_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("endpoint"),
        )
    if "ix_push_subscriptions_employer_id" not in _indexes(bind, "push_subscriptions"):
        op.create_index("ix_push_subscriptions_employer_id", "push_subscriptions", ["employer_id"])

    if "client_events" not in tables:
        op.create_table(
            "client_events",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("employer_id", sa.String(), nullable=False),
            sa.Column("actor", sa.String(), nullable=False),
            sa.Column("name", sa.String(), nullable=False),
            sa.Column("task_id", sa.String(), nullable=True),
            sa.Column("step_id", sa.String(), nullable=True),
            sa.Column("value_num", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    if "ix_client_events_employer_id" not in _indexes(bind, "client_events"):
        op.create_index("ix_client_events_employer_id", "client_events", ["employer_id"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = _tables(bind)
    for name in ("client_events", "push_subscriptions", "worker_presence"):
        if name in tables:
            op.drop_table(name)
    if "prev_count" in _columns(bind, "performance_logs"):
        # SQLite 3.35+ DROP COLUMN도 표를 다시 만들지 않는다(0007이 직접 만든 색인이 그대로 남는다).
        op.execute(sa.text("ALTER TABLE performance_logs DROP COLUMN prev_count"))
