"""사용 측정(가명): 측정 이벤트에 배정 id를 단다(client_events.assignment_id, 3b-1).

Revision ID: 0012_event_assignment_id
Revises: 0011_step_symbol_candidates
Create Date: 2026-11-14

왜: 명세 8.4 '혼자 끝낸 비율'·'잘못 누름(직무당)'은 직무 한 번(배정) 단위로 세야 한다. 지금 이벤트에는 직무·단계 id만
있어 같은 직무를 여러 근로자가 하면 섞인다. 배정 id는 근로자와 이어지는 가명 정보라 빈 값을 허용하고(예전 행·사업주
이벤트는 비움), 보고서가 배정별로 묶을 때 쓰는 색인을 둔다.

0006~0011처럼 "이미 있으면 건너뜀"으로 써서 중간에 멈춘 뒤 다시 돌려도 head에 도달한다. 앱 모듈을 import하지 않는다.
downgrade는 색인과 칸을 지운다(이벤트 행은 남고 배정 id만 사라진다).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012_event_assignment_id"
down_revision: Union[str, None] = "0011_step_symbol_candidates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEX = "ix_client_events_assignment_id"


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "assignment_id" not in _columns(bind, "client_events"):
        with op.batch_alter_table("client_events") as batch:
            batch.add_column(sa.Column("assignment_id", sa.String(), nullable=True))
    if _INDEX not in _indexes(bind, "client_events"):
        op.create_index(_INDEX, "client_events", ["assignment_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _INDEX in _indexes(bind, "client_events"):
        op.drop_index(_INDEX, table_name="client_events")
    if "assignment_id" in _columns(bind, "client_events"):
        with op.batch_alter_table("client_events") as batch:
            batch.drop_column("assignment_id")
