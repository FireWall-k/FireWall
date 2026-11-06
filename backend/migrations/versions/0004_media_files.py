"""사진·TTS 소유 레코드(media_files)와 단계의 media id 컬럼, 기존 URL 이관 (Phase 0.3).

Revision ID: 0004_media_files
Revises: 0003_privacy
Create Date: 2026-11-07

왜: 사진(/api/photos)·TTS(/api/tts)가 무인증 정적 경로로 나갔고, 누가 올린 파일인지 기록이 없었다. 단계에는
절대 URL이 저장돼 있어 update_step이 prefix만 맞으면 다른 사업장 사진 URL도 받아들였다. 이 리비전은
1. media_files(소유 레코드: employer_id, kind, 상대 키, sha256, 크기)를 만들고,
2. steps.symbol_media_id / steps.tts_media_id를 추가한 뒤,
3. 기존 steps.symbol_url(…/api/photos/<파일>)·steps.tts_audio_url(…/api/tts/<파일>)을 레코드로 옮긴다.
   파일이 디스크에 있으면 소유자는 그 단계가 속한 직무의 사업주(tasks.employer_id)다. 파일이 없으면(이미 깨진 링크)
   URL만 비운다(사진은 그림 없음 + 폴백 상태로 되돌린다).
   기존 사진은 이관하면서 EXIF(GPS)를 지운 WebP로 다시 저장한다(실패하면 원본을 그대로 레코드로 둔다).
   WebP를 다 쓴 뒤 옛 원본(EXIF·GPS 포함)은 바로 지운다. 예전에는 gc-media가 유예시간 뒤에 지우게 두었는데,
   그동안 촬영 위치가 든 원본이 디스크·백업에 그대로 남았다.
   재실행 안전성: WebP 파일 이름을 원본 이름에서 결정적으로 만든다(_converted_key, uuid5). 원본을 지운 뒤 DB
   변경이 롤백되거나 중간에 멈춰도, 다시 돌리면 단계가 가리키는 원본 대신 같은 이름의 WebP를 찾아 이어 간다.
   WebP는 임시 파일에 쓴 뒤 이름을 바꿔(원자적) 반쯤 쓴 파일을 완성본으로 오인하지 않게 한다.
4. steps.tts_audio_url 컬럼을 지운다(이제 응답 때 서명 URL을 만든다). symbol_url은 AAC 그림(공개 자산)용으로 남는다.

파일 위치는 앱과 같은 환경변수(PHOTO_DIR, TTS_CACHE_DIR; 기본 ./data/photos, ./data/tts)를 쓴다. migrate 서비스에도
backend와 같은 값과 볼륨이 있어야 한다(docker-compose.yml).

0002·0003과 같이 각 단계를 "이미 돼 있으면 건너뛰기"로 써서, SQLite에서 중간에 멈춘 뒤 다시 돌려도 head에 도달한다.
앱 모듈(photos.py 등)을 import하지 않는다 — 앱 코드가 나중에 바뀌어도 이 리비전의 동작은 그대로여야 한다.
이 파일은 배포 후 고치지 않는다(원본 즉시 삭제는 배포 전 0.3 보완에서 고쳤다).
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004_media_files"
down_revision: Union[str, None] = "0003_privacy"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PHOTO_URL_RE = re.compile(r"/api/photos/([0-9a-f]{32}\.(?:png|jpg|gif|webp))$")
_TTS_URL_RE = re.compile(r"/api/tts/([0-9a-f]{32}\.mp3)$")
_MAX_EDGE = 1600


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _photo_dir() -> Path:
    return Path(os.getenv("PHOTO_DIR", "./data/photos"))


def _tts_dir() -> Path:
    return Path(os.getenv("TTS_CACHE_DIR", "./data/tts"))


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _strip_metadata(data: bytes) -> bytes | None:
    """EXIF 등 메타데이터를 버린 WebP 바이트. Pillow가 없거나 열 수 없으면 None(원본 유지)."""
    try:
        from PIL import Image, ImageOps
    except Exception:  # noqa: BLE001 - Pillow 없는 환경이면 원본 그대로 레코드만 만든다
        return None
    try:
        img = Image.open(io.BytesIO(data), formats=("JPEG", "PNG", "WEBP", "GIF"))
        img = ImageOps.exif_transpose(img)
        has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if has_alpha else "RGB")
        img.thumbnail((_MAX_EDGE, _MAX_EDGE))
        img.info.clear()
        out = io.BytesIO()
        img.save(out, "WEBP", quality=85, method=4)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - 깨진 옛 파일은 원본 그대로 둔다(이관 자체를 멈추지 않는다)
        return None


# _converted_key의 uuid5 네임스페이스. 바꾸면 재실행 때 이미 만든 WebP를 못 찾으므로 고정이다.
_CONVERTED_NS = uuid.UUID("5b0e7f3c-2f6a-4c1e-9a52-0004e0f1a7c3")


def _converted_key(original_name: str) -> str:
    """원본 파일 이름 → 메타데이터를 지운 WebP 파일 이름(서버 키 모양 "<32 hex>.webp"). 같은 입력이면 늘 같다."""
    return f"{uuid.uuid5(_CONVERTED_NS, original_name).hex}.webp"


def _write_atomic(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _insert_media(bind, media, employer_id: str, kind: str, key: str, data: bytes) -> str:
    media_id = str(uuid.uuid4())
    bind.execute(media.insert().values(
        id=media_id, employer_id=employer_id, kind=kind, storage_key=key,
        sha256=hashlib.sha256(data).hexdigest(), bytes=len(data), created_at=_now()))
    return media_id


def _migrate_photos(bind, media) -> None:
    rows = bind.execute(sa.text(
        "SELECT s.id, s.symbol_url, t.employer_id FROM steps s JOIN tasks t ON t.id = s.task_id "
        "WHERE s.symbol_media_id IS NULL AND s.symbol_url LIKE '%/api/photos/%'")).all()
    # 같은 사업장이 같은 사진을 여러 단계에 붙였으면 레코드 하나를 같이 쓴다. 0004 이전 버그로 다른 사업장의
    # 단계에 붙은 사진은 규칙대로(단계의 사업주) 그 사업장 레코드를 따로 만든다 — 파일은 레코드가 모두 사라질 때 지워진다.
    by_owner: dict[tuple[str, str], str] = {}
    converted: dict[str, tuple[str, bytes]] = {}
    for step_id, url, employer_id in rows:
        m = _PHOTO_URL_RE.search(url or "")
        path = _photo_dir() / m.group(1) if m else None
        done = _photo_dir() / _converted_key(path.name) if path is not None else None
        if path is not None and path.name not in converted and not path.is_file()                 and done is not None and done.is_file():
            # 앞선 실행이 WebP를 만들고 원본을 지운 뒤 멈췄다(DB는 롤백). 만들어 둔 WebP로 이어 간다.
            converted[path.name] = (done.name, done.read_bytes())
        if path is None or (path.name not in converted and not path.is_file()):
            bind.execute(sa.text(
                "UPDATE steps SET symbol_url = NULL, symbol_source = 'fallback', needs_fallback = 1 "
                "WHERE id = :id"), {"id": step_id})
            continue
        if path.name not in converted:
            original = path.read_bytes()
            clean = _strip_metadata(original)
            if clean is not None:
                _write_atomic(done, clean)
                # WebP를 다 쓴 뒤에만 원본(EXIF·GPS)을 지운다. 같은 원본을 가리키는 다른 단계는 converted로 이어 간다.
                path.unlink(missing_ok=True)
                converted[path.name] = (done.name, clean)
            else:
                converted[path.name] = (path.name, original)
        key, data = converted[path.name]
        owner_key = (employer_id, key)
        if owner_key not in by_owner:
            by_owner[owner_key] = _insert_media(bind, media, employer_id, "photo", key, data)
        bind.execute(sa.text(
            "UPDATE steps SET symbol_media_id = :mid, symbol_url = NULL, symbol_source = 'photo' WHERE id = :id"),
            {"mid": by_owner[owner_key], "id": step_id})


def _migrate_tts(bind, media) -> None:
    rows = bind.execute(sa.text(
        "SELECT s.id, s.tts_audio_url, t.employer_id FROM steps s JOIN tasks t ON t.id = s.task_id "
        "WHERE s.tts_media_id IS NULL AND s.tts_audio_url IS NOT NULL")).all()
    for step_id, url, employer_id in rows:
        m = _TTS_URL_RE.search(url or "")
        path = _tts_dir() / m.group(1) if m else None
        media_id = None
        if path is not None and path.is_file():
            # TTS 레코드는 단계마다 하나(앱과 같은 규칙, main._tts_media_id). 옛 공유 캐시 파일은 여러 사업장의
            # 레코드가 같은 키를 가리킬 수 있다 — 접근은 레코드별 서명 URL로만 되므로 사업장 사이에 새지 않는다.
            media_id = _insert_media(bind, media, employer_id, "tts", path.name, path.read_bytes())
        bind.execute(sa.text("UPDATE steps SET tts_media_id = :mid, tts_audio_url = NULL WHERE id = :id"),
                     {"mid": media_id, "id": step_id})


def upgrade() -> None:
    bind = op.get_bind()

    # --- 1. 소유 레코드 테이블 ------------------------------------------------------
    if "media_files" not in _tables(bind):
        op.create_table(
            "media_files",
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("employer_id", sa.String(), sa.ForeignKey("employers.id"), nullable=False),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("storage_key", sa.String(), nullable=False),
            sa.Column("sha256", sa.String(), nullable=False),
            sa.Column("bytes", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("media_files")}
    for name, column in (("ix_media_files_employer_id", "employer_id"),
                         ("ix_media_files_storage_key", "storage_key")):
        if name not in indexes:
            op.create_index(name, "media_files", [column])

    # --- 2. 단계 → media id --------------------------------------------------------
    cols = _columns(bind, "steps")
    if "symbol_media_id" not in cols or "tts_media_id" not in cols:
        with op.batch_alter_table("steps") as batch:
            if "symbol_media_id" not in cols:
                batch.add_column(sa.Column("symbol_media_id", sa.String(), nullable=True))
                batch.create_foreign_key("fk_steps_symbol_media_id", "media_files",
                                         ["symbol_media_id"], ["id"])
            if "tts_media_id" not in cols:
                batch.add_column(sa.Column("tts_media_id", sa.String(), nullable=True))
                batch.create_foreign_key("fk_steps_tts_media_id", "media_files", ["tts_media_id"], ["id"])
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("steps")}
    for name, column in (("ix_steps_symbol_media_id", "symbol_media_id"),
                         ("ix_steps_tts_media_id", "tts_media_id")):
        if name not in indexes:
            op.create_index(name, "steps", [column])

    # --- 3. 기존 절대 URL → 레코드 ---------------------------------------------------
    media = sa.table(
        "media_files",
        sa.column("id", sa.String()), sa.column("employer_id", sa.String()), sa.column("kind", sa.String()),
        sa.column("storage_key", sa.String()), sa.column("sha256", sa.String()),
        sa.column("bytes", sa.Integer()), sa.column("created_at", sa.DateTime()),
    )
    _migrate_photos(bind, media)
    if "tts_audio_url" in _columns(bind, "steps"):
        _migrate_tts(bind, media)

        # --- 4. tts_audio_url 제거 ---------------------------------------------------
        with op.batch_alter_table("steps") as batch:
            batch.drop_column("tts_audio_url")


def downgrade() -> None:
    """0003 모양으로 되돌린다. 레코드가 가리키던 파일은 옛 정적 경로 URL로 다시 적는다(옛 코드가 그 경로를 연다)."""
    bind = op.get_bind()
    base = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
    with op.batch_alter_table("steps") as batch:
        batch.add_column(sa.Column("tts_audio_url", sa.String(), nullable=True))
    bind.execute(sa.text(
        "UPDATE steps SET tts_audio_url = :base || '/api/tts/' || "
        "(SELECT storage_key FROM media_files m WHERE m.id = steps.tts_media_id) "
        "WHERE tts_media_id IS NOT NULL"), {"base": base})
    bind.execute(sa.text(
        "UPDATE steps SET symbol_url = :base || '/api/photos/' || "
        "(SELECT storage_key FROM media_files m WHERE m.id = steps.symbol_media_id) "
        "WHERE symbol_media_id IS NOT NULL"), {"base": base})
    op.drop_index("ix_steps_tts_media_id", table_name="steps")
    op.drop_index("ix_steps_symbol_media_id", table_name="steps")
    with op.batch_alter_table("steps") as batch:
        batch.drop_constraint("fk_steps_tts_media_id", type_="foreignkey")
        batch.drop_constraint("fk_steps_symbol_media_id", type_="foreignkey")
        batch.drop_column("tts_media_id")
        batch.drop_column("symbol_media_id")
    op.drop_index("ix_media_files_storage_key", table_name="media_files")
    op.drop_index("ix_media_files_employer_id", table_name="media_files")
    op.drop_table("media_files")
