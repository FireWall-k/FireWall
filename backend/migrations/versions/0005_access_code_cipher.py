"""근로자 접속 코드 암호문 컬럼(workers.access_code_cipher).

Revision ID: 0005_access_code_cipher
Revises: 0004_media_files
Create Date: 2026-11-07

왜: 0002에서 접속 코드를 HMAC 해시로만 저장하게 바꾸자 사업주가 근로자에게 코드를 다시 알려 줄 방법이 없어졌다
(목록에는 뒤 2자리만). 사용자 요청으로 사업주 화면에 전체 코드를 보여 준다. 평문 대신 서버 시크릿으로 암호화한
값(auth.encrypt_access_code, AES-256-GCM)을 둔다 — DB 파일만으로는 코드를 알 수 없다는 성질은 그대로다.

기존 행은 평문을 알 수 없어(해시만 있음) 비워 둔다. 그 근로자가 다음에 로그인하면(서버가 평문을 받는 순간)
채워지고, 사업주가 코드를 재발급해도 채워진다. 이 리비전은 앱 모듈을 import하지 않는다.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005_access_code_cipher"
down_revision: Union[str, None] = "0004_media_files"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("workers")}
    if "access_code_cipher" not in cols:  # 중간에 멈춘 뒤 다시 돌려도 head에 도달하게
        with op.batch_alter_table("workers") as batch:
            batch.add_column(sa.Column("access_code_cipher", sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("workers") as batch:
        batch.drop_column("access_code_cipher")
