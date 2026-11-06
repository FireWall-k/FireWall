"""개인정보 보호: 근로자 메모·AI 메모 허용, 동의 기록, 접근 감사 로그 (Phase 0.2).

Revision ID: 0003_privacy
Revises: 0002_workplace_code
Create Date: 2026-11-07

왜: 발달장애 근로자의 이름·수행 데이터·특성 메모가 동의 기록 없이 해외 LLM으로 나갔고, 누가 근로자
데이터를 봤는지 남지 않았다. 이 리비전은
1. workers.note(사업주 메모), workers.ai_note_allowed(메모를 AI에 보내도 되는지, 기본 false)를 추가한다.
   기존 근로자는 모두 "허용 안 함"으로 시작한다 — 동의·허용 없이 메모가 나가던 상태를 끝내는 것이 목적이다.
2. worker_consents(동의 기록)와 access_audit_logs(접근 감사, append-only) 테이블을 만든다.

0002와 같이 각 단계를 "이미 돼 있으면 건너뛰기"로 써서, SQLite에서 중간에 멈춘 뒤 다시 돌려도 head에 도달한다.
이 파일은 배포 후 고치지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003_privacy"
down_revision: Union[str, None] = "0002_workplace_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(bind, table: str) -> set[str]:
    # 매번 새 Inspector를 만든다(캐시된 Inspector는 DDL 뒤의 모양을 못 본다).
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. 근로자 메모 + AI 메모 허용 -------------------------------------------------
    # NOT NULL 컬럼을 기존 행이 있는 테이블에 붙이므로 server_default가 필요하다(SQLite ADD COLUMN 규칙).
    cols = _columns(bind, "workers")
    if "note" not in cols:
        with op.batch_alter_table("workers") as batch:
            batch.add_column(sa.Column("note", sa.Text(), nullable=False, server_default=""))
    if "ai_note_allowed" not in cols:
        with op.batch_alter_table("workers") as batch:
            batch.add_column(sa.Column("ai_note_allowed", sa.Boolean(), nullable=False,
                                       server_default=sa.text("0")))

    # --- 2. 동의 기록 --------------------------------------------------------------
    if "worker_consents" not in _tables(bind):
        op.create_table(
            "worker_consents",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("worker_id", sa.String(), sa.ForeignKey("workers.id"), nullable=False),
            sa.Column("consent_type", sa.String(), nullable=False),
            sa.Column("subject", sa.String(), nullable=False),
            sa.Column("policy_version", sa.String(), nullable=False),
            sa.Column("granted_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("recorded_by", sa.String(), sa.ForeignKey("employers.id"), nullable=False),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("worker_consents")}
    for name, column in (("ix_worker_consents_worker_id", "worker_id"),
                         ("ix_worker_consents_recorded_by", "recorded_by")):
        if name not in indexes:
            op.create_index(name, "worker_consents", [column])

    # --- 3. 접근 감사 로그 -----------------------------------------------------------
    # worker_id에 FK를 걸지 않는다 — 근로자 삭제 뒤에도 보존기간 동안 열람 기록이 남아야 한다.
    if "access_audit_logs" not in _tables(bind):
        op.create_table(
            "access_audit_logs",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("actor_id", sa.String(), nullable=False),
            sa.Column("actor_role", sa.String(), nullable=False),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("worker_id", sa.String(), nullable=True),
            sa.Column("at", sa.DateTime(), nullable=False),
            sa.Column("request_ip", sa.String(), nullable=False),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("access_audit_logs")}
    for name, column in (("ix_access_audit_logs_actor_id", "actor_id"),
                         ("ix_access_audit_logs_worker_id", "worker_id"),
                         ("ix_access_audit_logs_at", "at")):
        if name not in indexes:
            op.create_index(name, "access_audit_logs", [column])


def downgrade() -> None:
    op.drop_table("access_audit_logs")
    op.drop_table("worker_consents")
    with op.batch_alter_table("workers") as batch:
        batch.drop_column("ai_note_allowed")
        batch.drop_column("note")
