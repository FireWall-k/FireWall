"""2b-1 만들고 보내기: 단계의 조심 표시·나누기 출처·원문 조각·음성 다시 만들기 표시·묶음 경계.

Revision ID: 0008_step_review
Revises: 0007_task_versions
Create Date: 2026-11-10

왜(contract §3.1):
1. steps.safety_flag·safety_source·safety_note: 근로자 화면 '조심해요' 띠. 칼·뜨거운·기계 같은 말이 있으면 서버가
   '✦ 자동 제안'으로 켜고(safety_source='auto'), 사업주가 스위치를 바꾸면 'manual'이다. 근로자에게는 flag만 간다.
2. steps.split_source·split_needs_review·original_span: 입력 화면에서 어떻게 나눴는지와 원래 지시문 조각(편집기의
   원문 인용). 나눈 문장 확인은 입력 화면이 끝내므로 split_needs_review는 늘 0으로 저장한다(옛 데이터 방어용 칸).
3. steps.tts_stale: 600ms 자동 저장(defer_media)은 문장만 저장하고 음성은 칸을 벗어날 때·보낼 때 만든다.
4. steps.group_break·task_version_steps.group_break: 9단계가 넘는 직무의 묶음 경계(데이터만, 근로자 쉼 화면은 3차).
5. task_version_steps.safety_flag: 보낸 버전에 고정된 조심 표시(근로자 응답이 읽는다).

해시를 저장하지 않으므로 다시 계산할 것이 없다. 모든 칸에 server_default가 있어 옛 행은 '조심 없음·나누기 정보 없음'이다.
0006·0007처럼 "이미 있으면 건너뜀"으로 써서 중간에 멈춘 뒤 다시 돌려도 head에 도달한다. 앱 모듈을 import하지 않는다.
downgrade는 이 칸들을 지운다(조심 표시·원문 조각이 사라진다. 다시 올리면 모두 기본값).
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008_step_review"
down_revision: Union[str, None] = "0007_task_versions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _bool(name: str) -> sa.Column:
    return sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("0"))


def _text(name: str, type_=sa.Text) -> sa.Column:
    return sa.Column(name, type_(), nullable=False, server_default="")


# (칸 이름, 칸 만들기) — 순서대로 더한다.
_STEP_COLUMNS = (
    ("safety_flag", lambda: _bool("safety_flag")),
    ("safety_source", lambda: _text("safety_source", sa.String)),
    ("safety_note", lambda: _text("safety_note")),
    ("split_source", lambda: _text("split_source", sa.String)),
    ("split_needs_review", lambda: _bool("split_needs_review")),
    ("original_span", lambda: _text("original_span")),
    ("tts_stale", lambda: _bool("tts_stale")),
    ("group_break", lambda: _bool("group_break")),
)
_VERSION_STEP_COLUMNS = (
    ("safety_flag", lambda: _bool("safety_flag")),
    ("group_break", lambda: _bool("group_break")),
)


def _columns(bind, table: str) -> set[str]:
    # 매번 새 Inspector를 만든다(캐시된 Inspector는 DDL 뒤의 모양을 못 본다).
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _add(bind, table: str, specs) -> None:
    have = _columns(bind, table)
    missing = [make() for name, make in specs if name not in have]
    if missing:
        with op.batch_alter_table(table) as batch:
            for col in missing:
                batch.add_column(col)


def _drop(bind, table: str, specs) -> None:
    have = _columns(bind, table)
    drop = [name for name, _ in specs if name in have]
    if drop:
        with op.batch_alter_table(table) as batch:
            for name in drop:
                batch.drop_column(name)


def upgrade() -> None:
    bind = op.get_bind()
    _add(bind, "steps", _STEP_COLUMNS)
    _add(bind, "task_version_steps", _VERSION_STEP_COLUMNS)


def downgrade() -> None:
    bind = op.get_bind()
    _drop(bind, "task_version_steps", _VERSION_STEP_COLUMNS)
    _drop(bind, "steps", _STEP_COLUMNS)
