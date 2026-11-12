"""2d 관리 화면: 사업장 호칭(teacher_title)과 근로자 화면 기본값(worker_defaults).

Revision ID: 0010_workplace_settings
Revises: 0009_live_push (2b-1·2c·2d 병합 때 0009 뒤로 이음)
Create Date: 2026-11-10

왜:
1. 근로자 화면에서 사업주를 부르는 호칭이 '선생님'으로 고정돼 있었다(창업자 결정 1). 현장마다 '코치'·'반장'처럼
   다르게 부르므로 사업장 설정으로 둔다. 기본은 '선생님'이라 지금 근로자 화면은 그대로다.
2. 새 근로자를 만들 때 쓸 화면 설정 기본값(글자 크기·말 속도 등). 빈 객체 = 지금 기본값. 이미 있는 근로자는
   그대로 둔다(기본값을 바꿔도 소급하지 않는다).

0006·0007처럼 "이미 있으면 건너뜀"으로 써서 중간에 멈춘 뒤 다시 돌려도 head에 도달한다. 앱 모듈을 import하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010_workplace_settings"
down_revision: Union[str, None] = "0009_live_push"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    # 매번 새 Inspector를 만든다(캐시된 Inspector는 DDL 뒤의 모양을 못 본다).
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind, "employers")
    if "teacher_title" not in cols:
        with op.batch_alter_table("employers") as batch:
            batch.add_column(sa.Column("teacher_title", sa.String(), nullable=False, server_default="선생님"))
    if "worker_defaults" not in cols:
        with op.batch_alter_table("employers") as batch:
            batch.add_column(sa.Column("worker_defaults", sa.Text(), nullable=False, server_default="{}"))


def downgrade() -> None:
    bind = op.get_bind()
    cols = _columns(bind, "employers")
    with op.batch_alter_table("employers") as batch:
        for name in ("worker_defaults", "teacher_title"):
            if name in cols:
                batch.drop_column(name)
