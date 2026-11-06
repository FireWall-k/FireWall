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

upgrade()는 시크릿을 DDL보다 먼저 확인하고, 각 단계를 "이미 돼 있으면 건너뛰기"로 써서
중간에 실패한 뒤 다시 돌려도 head에 도달한다(SQLite의 ALTER TABLE은 롤백되지 않기 때문).

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


def _column_info(bind, table: str) -> dict[str, dict]:
    # 매번 새 Inspector를 만든다. Inspector는 결과를 캐시하므로 DDL 뒤에 재사용하면 옛 모양을 본다.
    return {c["name"]: c for c in sa.inspect(bind).get_columns(table)}


def _index_names(bind, table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def _unique_names(bind, table: str) -> set[str]:
    return {u["name"] for u in sa.inspect(bind).get_unique_constraints(table)}


def upgrade() -> None:
    bind = op.get_bind()

    # --- 0. DDL 전에 시크릿부터 확인 ------------------------------------------------------
    # 왜 맨 앞인가: SQLite의 ALTER TABLE은 트랜잭션으로 되돌려지지 않는다. 예전에는 1단계(컬럼 추가)를
    # 한 뒤에 시크릿을 읽어서, 운영에서 약한 시크릿으로 한 번 실패하면 컬럼만 남고 alembic_version은
    # 0001에 머물렀다 → 시크릿을 고쳐 재시도해도 "duplicate column"으로 영원히 실패했다.
    # 근로자가 있을 때만 읽는다. 운영에서 약한/빈 시크릿이면 여기서 RuntimeError로 멈춘다
    # (개발용 기본 키로 해시해 두면 backend가 진짜 키로 기동하는 순간 전원이 로그인하지 못한다).
    secret: str | None = None
    if "access_code" in _column_info(bind, "workers"):
        if bind.execute(sa.text("SELECT COUNT(*) FROM workers")).scalar():
            from auth import _secret

            secret = _secret()

    # 아래 단계는 모두 "이미 돼 있으면 건너뛰기"로 쓴다. 시크릿 확인 뒤에도 디스크 부족·프로세스
    # 종료 등으로 중간에 멈출 수 있고, 그때 SQLite에는 앞 단계 DDL이 남는다. 그 상태에서 다시
    # 돌려도 head에 도달해야 한다(test_migration.py의 재시도 테스트가 확인한다).

    # --- 1. 사업장 코드 --------------------------------------------------------------
    if "workplace_code" not in _column_info(bind, "employers"):
        with op.batch_alter_table("employers") as batch:
            batch.add_column(sa.Column("workplace_code", sa.String(), nullable=True))
    used: set[str] = {c for (c,) in bind.execute(sa.text(
        "SELECT workplace_code FROM employers WHERE workplace_code IS NOT NULL")).fetchall()}
    for (employer_id,) in bind.execute(sa.text(
            "SELECT id FROM employers WHERE workplace_code IS NULL")).fetchall():
        bind.execute(sa.text("UPDATE employers SET workplace_code = :c WHERE id = :i"),
                     {"c": _new_code(used), "i": employer_id})
    emp_nullable = _column_info(bind, "employers")["workplace_code"]["nullable"]
    emp_has_index = "ix_employers_workplace_code" in _index_names(bind, "employers")
    if emp_nullable or not emp_has_index:
        with op.batch_alter_table("employers") as batch:
            if emp_nullable:
                batch.alter_column("workplace_code", existing_type=sa.String(), nullable=False)
            if not emp_has_index:
                batch.create_index("ix_employers_workplace_code", ["workplace_code"], unique=True)

    # --- 2. 접속 코드 평문 → 해시 ---------------------------------------------------------
    new_cols = [("access_code_hash", sa.String()), ("access_code_hint", sa.String()),
                ("access_code_length", sa.Integer())]
    cols = _column_info(bind, "workers")
    missing = [(n, t) for n, t in new_cols if n not in cols]
    if missing:
        with op.batch_alter_table("workers") as batch:
            for name, type_ in missing:
                batch.add_column(sa.Column(name, type_, nullable=True))

    if "access_code" in cols:
        # 평문 컬럼이 남아 있는 동안은 항상 전원을 다시 해시한다. 앞선 실패한 실행이 다른 시크릿으로
        # 일부를 채웠을 수 있으므로 "비어 있는 것만" 채우면 안 된다.
        rows = bind.execute(sa.text("SELECT id, employer_id, access_code FROM workers")).fetchall()
        if rows and secret is None:
            # 0단계 이후에 근로자가 생긴 경우(동시 실행 등). 시크릿 검사를 건너뛰지 않는다.
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

    cols = _column_info(bind, "workers")
    has_plain_index = "ix_workers_access_code" in _index_names(bind, "workers")
    has_unique = "uq_worker_employer_code" in _unique_names(bind, "workers")
    nullable_cols = [(n, t) for n, t in new_cols if cols[n]["nullable"]]
    if "access_code" in cols or has_plain_index or nullable_cols or not has_unique:
        with op.batch_alter_table("workers") as batch:
            if has_plain_index:
                batch.drop_index("ix_workers_access_code")
            if "access_code" in cols:
                batch.drop_column("access_code")
            for name, type_ in nullable_cols:
                batch.alter_column(name, existing_type=type_, nullable=False)
            if not has_unique:
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
