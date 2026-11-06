"""사업장 코드 도입 + 근로자 접속 코드 해시 저장 (Phase 0.1).

Revision ID: 0002_workplace_code
Revises: 0001_baseline
Create Date: 2026-11-07

왜: 접속 코드가 전역 unique(ix_workers_access_code)였고 로그인이 코드만으로 근로자를 찾았다.
그래서 사업주가 코드를 직접 정할 때의 409가 "다른 사업장에 이 코드가 있다"를 알려 주는 오라클이
됐고, 목록·대시보드 응답에 평문 코드가 실렸다. 이 리비전은
1. employers.workplace_code(서버 생성, 전역 unique)를 추가하고 기존 사업주 모두에게 발급한다.
2. workers.access_code(평문)를 access_code_hash = HMAC-SHA256(JOBCARD_SECRET, "employer_id:code")
   + access_code_hint(뒤 2자리) + access_code_length로 바꾸고, unique를 (employer_id, hash)로 좁힌다.

주의(운영):
- 해시는 **마이그레이션을 돌리는 프로세스의 JOBCARD_SECRET**으로 만든다. migrate 서비스와 backend가
  같은 시크릿을 받아야 한다(docker-compose.yml). 다르면 기존 근로자 전원이 로그인하지 못한다.
- 나중에 JOBCARD_SECRET를 바꾸면 저장된 해시가 모두 맞지 않게 된다 → 근로자 접속 코드를 전부
  재발급해야 한다(README "근로자 접속 코드" 참고).
- downgrade는 평문을 되살릴 수 없다(해시는 되돌릴 수 없다). 접속 코드를 근로자 id로 채우므로
  되돌린 뒤에는 코드를 모두 재발급해야 한다.

이 파일은 배포 후 고치지 않는다. 해시 공식은 이 시점의 auth.hash_access_code와 같아야 하며,
test_migration.py가 둘이 같은지 확인한다(공식이 바뀌면 새 리비전으로 재해시가 필요하다는 뜻).
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002_workplace_code"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# codes.py와 같은 규칙을 여기 고정한다(앱 코드가 바뀌어도 이 리비전의 동작은 바뀌지 않게).
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_LENGTH = 6


def _new_code(used: set[str]) -> str:
    while True:
        code = "".join(secrets.choice(_ALPHABET) for _ in range(_LENGTH))
        if code not in used:
            used.add(code)
            return code


def _hash(secret: str, employer_id: str, code: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"{employer_id}:{code}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. 사업장 코드 --------------------------------------------------------------
    with op.batch_alter_table("employers") as batch:
        batch.add_column(sa.Column("workplace_code", sa.String(), nullable=True))
    used: set[str] = set()
    for (employer_id,) in bind.execute(sa.text("SELECT id FROM employers")).fetchall():
        bind.execute(sa.text("UPDATE employers SET workplace_code = :c WHERE id = :i"),
                     {"c": _new_code(used), "i": employer_id})
    with op.batch_alter_table("employers") as batch:
        batch.alter_column("workplace_code", existing_type=sa.String(), nullable=False)
        batch.create_index("ix_employers_workplace_code", ["workplace_code"], unique=True)

    # --- 2. 접속 코드 평문 → 해시 ---------------------------------------------------------
    with op.batch_alter_table("workers") as batch:
        batch.add_column(sa.Column("access_code_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("access_code_hint", sa.String(), nullable=True))
        batch.add_column(sa.Column("access_code_length", sa.Integer(), nullable=True))

    rows = bind.execute(sa.text("SELECT id, employer_id, access_code FROM workers")).fetchall()
    if rows:
        # 근로자가 있을 때만 시크릿을 읽는다. 운영에서 약한/빈 시크릿이면 여기서 RuntimeError로 멈춘다
        # (개발용 기본 키로 해시해 두면 backend가 진짜 키로 기동하는 순간 전원이 로그인하지 못한다).
        from auth import _secret

        secret = _secret()
        for worker_id, employer_id, code in rows:
            code = code or ""
            bind.execute(
                sa.text("UPDATE workers SET access_code_hash = :h, access_code_hint = :t, "
                        "access_code_length = :n WHERE id = :i"),
                {"h": _hash(secret, employer_id, code), "t": code[-2:], "n": len(code),
                 "i": worker_id},
            )

    with op.batch_alter_table("workers") as batch:
        batch.drop_index("ix_workers_access_code")
        batch.drop_column("access_code")
        batch.alter_column("access_code_hash", existing_type=sa.String(), nullable=False)
        batch.alter_column("access_code_hint", existing_type=sa.String(), nullable=False)
        batch.alter_column("access_code_length", existing_type=sa.Integer(), nullable=False)
        batch.create_unique_constraint("uq_worker_employer_code",
                                       ["employer_id", "access_code_hash"])


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("workers") as batch:
        batch.add_column(sa.Column("access_code", sa.String(), nullable=True))
    count = bind.execute(sa.text("SELECT COUNT(*) FROM workers")).scalar() or 0
    # 해시에서 평문을 되살릴 수 없다. baseline의 전역 unique를 만족하면서 추측할 수 없는 값으로
    # 근로자 id(UUID)를 넣는다 — 되돌린 뒤에는 접속 코드를 모두 재발급해야 한다.
    bind.execute(sa.text("UPDATE workers SET access_code = id"))
    if count:
        logger.warning("0002 downgrade: 근로자 %d명의 접속 코드를 복원할 수 없어 재발급이 필요합니다.",
                       count)
    with op.batch_alter_table("workers") as batch:
        batch.drop_constraint("uq_worker_employer_code", type_="unique")
        batch.drop_column("access_code_length")
        batch.drop_column("access_code_hint")
        batch.drop_column("access_code_hash")
        batch.alter_column("access_code", existing_type=sa.String(), nullable=False)
        batch.create_index("ix_workers_access_code", ["access_code"], unique=True)

    with op.batch_alter_table("employers") as batch:
        batch.drop_index("ix_employers_workplace_code")
        batch.drop_column("workplace_code")
