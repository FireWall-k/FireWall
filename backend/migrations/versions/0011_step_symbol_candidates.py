"""그림 정확도 ②: 생성 때 그림 후보 순서를 단계에 남긴다(steps.symbol_candidates).

Revision ID: 0011_step_symbol_candidates
Revises: 0010_workplace_settings
Create Date: 2026-11-13

왜: 직무를 만들 때 GPT 재순위가 맞는 그림을 후보 맨 앞으로 올려도, 편집기는 후보를 규칙만으로 다시 찾아(유료 모델 없음)
그 순서가 사라졌다. 그래서 '그림 없음' 단계 후보 1순위가 틀린 그림으로 보였다. 생성 때 순서(그림 주소 최대 3개, JSON)를
남겨 편집기 후보 앞에 둔다. 이미 있는 단계는 빈 값 = 예전처럼 규칙 순서다.

0006~0010처럼 "이미 있으면 건너뜀"으로 써서 중간에 멈춘 뒤 다시 돌려도 head에 도달한다. 앱 모듈을 import하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_step_symbol_candidates"
down_revision: Union[str, None] = "0010_workplace_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    if "symbol_candidates" not in _columns(bind, "steps"):
        with op.batch_alter_table("steps") as batch:
            batch.add_column(sa.Column("symbol_candidates", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    bind = op.get_bind()
    if "symbol_candidates" in _columns(bind, "steps"):
        with op.batch_alter_table("steps") as batch:
            batch.drop_column("symbol_candidates")
