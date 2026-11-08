"""근로자 화면 0·1차: 그림 확인, 완료/신호 구분, 오프라인 재전송 키, 화면 설정, 도움 요청.

Revision ID: 0006_worker_phase1
Revises: 0005_access_code_cipher
Create Date: 2026-11-09

왜:
1. [도와주세요]가 stuck=true 수행 로그로 저장돼, 마지막 단계에서 도움만 눌러도 '모든 단계 기록 있음'이 되어
   직무가 '다 함'으로 바뀌었다. 도움 요청은 help_requests로 옮기고, 수행 로그에는 completed(완료인지)를 둔다.
   0006 이전 행은 완료로 본다(server_default 1) — 과거 도움 전용 행과 구분할 수 없는 것은 알려진 한계다.
2. 근로자 기기의 오프라인 대기열이 같은 기록을 다시 보내도 한 번만 세려고 client_event_id를 둔다.
3. steps.picture_confirmed: 사업주가 그림을 확인했는지(그림 4상태). 사진 단계, 그리고 이미 보낸(published)
   직무의 그림 있는 단계는 사업주가 보고 보낸 것으로 보고 1로 채운다.
4. workers.a11y_prefs(화면 설정 JSON, 빈 객체 = 기본값), workers.last_seen_at(오늘 할 일 마지막 조회).

0003·0005처럼 "이미 있으면 건너뜀"으로 써서 SQLite에서 중간에 멈춘 뒤 다시 돌려도 head에 도달한다.
이 리비전은 앱 모듈을 import하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_worker_phase1"
down_revision: Union[str, None] = "0005_access_code_cipher"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_HELP_INDEXES = (
    ("ix_help_requests_employer_id", ["employer_id"]),
    ("ix_help_requests_worker_id", ["worker_id"]),
    ("ix_help_requests_assignment_id", ["assignment_id"]),
    ("ix_help_requests_step_id", ["step_id"]),
    ("ix_help_requests_created_at", ["created_at"]),
    ("ix_help_requests_assignment_state", ["assignment_id", "state"]),
)


def _columns(bind, table: str) -> set[str]:
    # 매번 새 Inspector를 만든다(캐시된 Inspector는 DDL 뒤의 모양을 못 본다).
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. 단계: 그림 확인 ------------------------------------------------------------
    if "picture_confirmed" not in _columns(bind, "steps"):
        with op.batch_alter_table("steps") as batch:
            batch.add_column(sa.Column("picture_confirmed", sa.Boolean(), nullable=False,
                                       server_default=sa.text("0")))
    # 백필은 다시 돌려도 결과가 같다(같은 조건으로 1만 채운다). 이 리비전이 끝나기 전에는 앱이 이 컬럼을 쓰지 않는다.
    bind.execute(sa.text(
        "UPDATE steps SET picture_confirmed = 1 WHERE symbol_source = 'photo' "
        "OR (task_id IN (SELECT id FROM tasks WHERE status = 'published') "
        "AND (symbol_media_id IS NOT NULL OR (symbol_url IS NOT NULL AND symbol_url != '')))"))

    # --- 2. 수행 로그: 완료 여부 + 재전송 키 --------------------------------------------
    cols = _columns(bind, "performance_logs")
    if "completed" not in cols:
        with op.batch_alter_table("performance_logs") as batch:
            batch.add_column(sa.Column("completed", sa.Boolean(), nullable=False,
                                       server_default=sa.text("1")))
    if "client_event_id" not in cols:
        with op.batch_alter_table("performance_logs") as batch:
            batch.add_column(sa.Column("client_event_id", sa.String(length=64), nullable=True))

    # --- 3. 근로자: 화면 설정 + 마지막 조회 ---------------------------------------------
    cols = _columns(bind, "workers")
    if "a11y_prefs" not in cols:
        with op.batch_alter_table("workers") as batch:
            batch.add_column(sa.Column("a11y_prefs", sa.Text(), nullable=False, server_default="{}"))
    if "last_seen_at" not in cols:
        with op.batch_alter_table("workers") as batch:
            batch.add_column(sa.Column("last_seen_at", sa.DateTime(), nullable=True))

    # --- 4. 도움 요청 ------------------------------------------------------------------
    if "help_requests" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "help_requests",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("employer_id", sa.String(), sa.ForeignKey("employers.id"), nullable=False),
            sa.Column("worker_id", sa.String(), sa.ForeignKey("workers.id"), nullable=False),
            sa.Column("assignment_id", sa.String(), sa.ForeignKey("assignments.id"), nullable=False),
            sa.Column("step_id", sa.String(), sa.ForeignKey("steps.id"), nullable=True),
            sa.Column("state", sa.String(), nullable=False),
            sa.Column("resolution", sa.String(), nullable=True),
            sa.Column("client_request_id", sa.String(length=64), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("acknowledged_at", sa.DateTime(), nullable=True),
            sa.Column("cancelled_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("help_requests")}
    for name, columns in _HELP_INDEXES:
        if name not in indexes:
            op.create_index(name, "help_requests", columns)


def downgrade() -> None:
    bind = op.get_bind()
    if "help_requests" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("help_requests")
    cols = _columns(bind, "workers")
    with op.batch_alter_table("workers") as batch:
        for name in ("last_seen_at", "a11y_prefs"):
            if name in cols:
                batch.drop_column(name)
    cols = _columns(bind, "performance_logs")
    if "completed" in cols:
        # 0005 코드는 "기록이 있는 단계 수 >= 단계 수"면 다 함으로 본다. completed=0(어려움 신호만 있고 끝내지
        # 않은 단계) 행을 남긴 채 컬럼만 지우면, 그 행이 완료로 세어져 예전 완료 판정 버그가 되살아난다(1차 검증 지적).
        # 되돌릴 때는 그 행을 지운다(잃는 것은 어려움 신호 기록뿐이다).
        op.execute(sa.text("DELETE FROM performance_logs WHERE completed = 0"))
    with op.batch_alter_table("performance_logs") as batch:
        for name in ("client_event_id", "completed"):
            if name in cols:
                batch.drop_column(name)
    if "picture_confirmed" in _columns(bind, "steps"):
        with op.batch_alter_table("steps") as batch:
            batch.drop_column("picture_confirmed")
