"""사업주 소유 파일(사진·TTS)의 레코드·서명 URL·정리 (Phase 0.3).

왜 서명 URL인가:
- 예전에는 /api/photos, /api/tts를 무인증 StaticFiles로 열어 두어, URL(=파일명)만 알면 누구나 현장 사진·음성을
  받을 수 있었다. 사진에는 근로자가 찍힐 수 있고, 음성 문장에는 이름이 들어갈 수 있다.
- 근로자 화면의 <img>/<audio>는 Authorization 헤더를 보낼 수 없다. 그래서 API 응답을 만들 때(= 이미 인증·소유권
  검사를 통과한 뒤) media id와 만료 시각에 HMAC 서명을 붙인 짧은 수명의 URL을 만들어 준다.
  GET /api/media/{id}는 서명과 만료만 확인한다. 서명은 id에 묶여 있어 다른 파일에 옮겨 쓸 수 없다.
- 만료된 URL은 403이다. 화면은 응답을 다시 조회해 새 URL을 받는다(frontend/src/media.ts).

DB에는 URL이 아니라 media id(Step.symbol_media_id/tts_media_id)와 상대 키(MediaFile.storage_key)만 둔다.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.orm import Session

from auth import media_signature
from models import MediaFile, Step
from photos import get_photo_dir
from tts import get_tts_cache_dir

KIND_PHOTO = "photo"
KIND_TTS = "tts"
KINDS = (KIND_PHOTO, KIND_TTS)

# 서버가 만든 파일명만 받는다("<uuid hex 32자>.<ext>"). 레코드의 키가 어떻게 들어왔든 경로 조작이 될 수 없다.
_KEY_RE = re.compile(r"^[0-9a-f]{32}\.(webp|png|jpg|gif|mp3)$")
_CONTENT_TYPES = {
    "webp": "image/webp", "png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "mp3": "audio/mpeg",
}
_MEDIA_PATH_RE = re.compile(r"^/api/media/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})(?:\?.*)?$")

# 만료 시각을 이 단위로 올림한다. 같은 구간 안에 다시 조회한 응답은 URL이 똑같아 브라우저 캐시를 그대로 쓴다
# (매 응답마다 exp가 1초씩 달라지면 근로자 화면이 다시 조회할 때마다 사진을 새로 받는다).
EXP_BUCKET_SECONDS = 300


def url_ttl_seconds() -> int:
    """서명 URL 수명(초). 기본 1시간.

    짧을수록 URL이 새어 나갔을 때(브라우저 기록, 화면 공유) 쓸 수 있는 시간이 줄어든다. 근로자 화면은 하루 종일
    켜 둘 수 있지만, 만료되면 화면이 오늘 카드를 다시 조회해 새 URL을 받는다. 60초 미만은 버킷 반올림 때문에
    의미가 없어 60으로 올린다.
    """
    raw = os.getenv("MEDIA_URL_TTL_SECONDS", "3600").strip()
    try:
        ttl = int(raw)
    except ValueError:
        raise ValueError(f"MEDIA_URL_TTL_SECONDS는 초 단위 정수여야 합니다: {raw!r}") from None
    return max(ttl, 60)


def orphan_grace_hours() -> float:
    """레코드 없는 파일·참조 없는 레코드를 지우기 전 유예시간. 예전 TTS_ORPHAN_GRACE_HOURS도 받는다."""
    raw = os.getenv("MEDIA_ORPHAN_GRACE_HOURS") or os.getenv("TTS_ORPHAN_GRACE_HOURS") or "24"
    return float(raw)


def media_dir(kind: str) -> Path:
    if kind == KIND_PHOTO:
        return get_photo_dir()
    if kind == KIND_TTS:
        return get_tts_cache_dir()
    raise ValueError(f"알 수 없는 media kind: {kind!r}")


def media_path(kind: str, storage_key: str) -> Path | None:
    """레코드의 파일 경로. 키가 서버가 만든 모양이 아니면 None(경로 조작 방지)."""
    if not _KEY_RE.match(storage_key or ""):
        return None
    return media_dir(kind) / storage_key


def content_type(storage_key: str) -> str:
    return _CONTENT_TYPES.get(storage_key.rsplit(".", 1)[-1], "application/octet-stream")


# --- 서명 URL ----------------------------------------------------------------

def signature(media_id: str, exp: int) -> str:
    return media_signature(media_id, int(exp))


def signed_url(media_id: str, now: float | None = None) -> str:
    """응답에 실을 절대 서명 URL(PUBLIC_BACKEND_URL 기준). 수명은 url_ttl_seconds() 이상, 버킷 하나만큼 더 길 수 있다."""
    now_i = int(time.time() if now is None else now)
    exp = (now_i // EXP_BUCKET_SECONDS + 1) * EXP_BUCKET_SECONDS + url_ttl_seconds()
    base = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/api/media/{media_id}?exp={exp}&sig={signature(media_id, exp)}"


def verify(media_id: str, exp: str, sig: str, now: float | None = None) -> bool:
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(time.time() if now is None else now):
        return False
    return hmac.compare_digest(signature(media_id, exp_i), sig or "")


def parse_media_url(url: str) -> str | None:
    """"<PUBLIC_BACKEND_URL>/api/media/<id>?..." 또는 "/api/media/<id>"에서 media id를 꺼낸다. 아니면 None.

    서명은 보지 않는다 — 이 함수를 쓰는 곳(update_step)은 서명 대신 소유 레코드를 조회한다.
    """
    base = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
    path = url[len(base):] if url.startswith(base + "/") else url
    m = _MEDIA_PATH_RE.match(path)
    return m.group(1) if m else None


# --- 레코드 ------------------------------------------------------------------

def create_record(db: Session, employer_id: str, kind: str, storage_key: str) -> MediaFile | None:
    """파일이 있으면 소유 레코드를 만들어 세션에 넣는다(커밋은 호출한 쪽). 파일이 없으면 None."""
    path = media_path(kind, storage_key)
    if path is None or not path.is_file():
        return None
    data = path.read_bytes()
    rec = MediaFile(employer_id=employer_id, kind=kind, storage_key=storage_key,
                    sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
    db.add(rec)
    db.flush()
    return rec


def owned(db: Session, employer_id: str, media_id: str, kind: str) -> MediaFile | None:
    rec = db.get(MediaFile, media_id)
    if rec is None or rec.employer_id != employer_id or rec.kind != kind:
        return None
    return rec


def _unreferenced():
    """어느 단계도 가리키지 않는 레코드 조건."""
    return ~exists().where(or_(Step.symbol_media_id == MediaFile.id, Step.tts_media_id == MediaFile.id))


def _key_in_use(db: Session, kind: str, storage_key: str) -> bool:
    return db.scalar(select(func.count()).select_from(MediaFile).where(
        MediaFile.kind == kind, MediaFile.storage_key == storage_key)) > 0


def release(db: Session, media_ids) -> int:
    """단계에서 떼어 낸 media를 바로 정리한다. 반드시 단계 변경을 커밋한 뒤에 부른다. 지운 레코드 수를 돌려준다.

    - 다른 단계가 아직 쓰는 레코드는 남긴다(사진은 update_step으로 여러 단계에 붙일 수 있다).
      "참조 없음" 확인과 삭제를 한 DELETE 문으로 해, 그 사이에 다른 요청이 붙이는 경합을 줄인다.
    - 사진 파일은 바로 지운다. 사람이 찍힐 수 있는 사진을 하루씩 남겨 둘 이유가 없고, 사진 키는 업로드마다
      새 UUID라 다른 요청이 같은 파일을 새로 쓰려는 경합이 없다.
    - TTS 파일은 지우지 않고 gc(유예시간)에 맡긴다. 같은 사업장의 다른 요청이 같은 문장의 캐시를 막 다시 쓰는
      중일 수 있다(tts.synthesize_tts가 수정 시각을 갱신하고, gc는 그 시각을 본다).
    """
    ids = [i for i in dict.fromkeys(media_ids) if i]
    removed = 0
    for media_id in ids:
        rec = db.get(MediaFile, media_id)
        if rec is None:
            continue
        kind, key = rec.kind, rec.storage_key
        result = db.execute(delete(MediaFile).where(MediaFile.id == media_id, _unreferenced())
                            .execution_options(synchronize_session=False))
        db.commit()
        if not result.rowcount:
            continue
        removed += 1
        if kind == KIND_PHOTO and not _key_in_use(db, kind, key):
            path = media_path(kind, key)
            if path is not None:
                path.unlink(missing_ok=True)
    db.expire_all()
    return removed


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _orphan_files(db: Session, cutoff_ts: float) -> list[tuple[str, Path]]:
    out = []
    for kind in KINDS:
        known = set(db.scalars(select(MediaFile.storage_key).where(MediaFile.kind == kind)).all())
        for path in media_dir(kind).iterdir():
            # 서버가 만든 이름 모양만 대상으로 한다. 운영자가 둔 다른 파일(README, .gitkeep)은 건드리지 않는다.
            if not _KEY_RE.match(path.name) or path.name in known or not path.is_file():
                continue
            try:
                if path.stat().st_mtime > cutoff_ts:
                    continue
            except FileNotFoundError:
                continue
            out.append((kind, path))
    return out


def gc(db: Session, *, dry_run: bool = False, grace_hours: float | None = None,
       before_unlink=None) -> dict:
    """고아 정리. 어느 단계도 가리키지 않는 레코드와, 어느 레코드도 가리키지 않는 파일을 지운다.

    유예시간보다 새 것은 건드리지 않는다. 직무 생성은 파일을 먼저 쓰고(네트워크 호출 중) 레코드·단계를 나중에
    커밋하므로, 막 생긴 파일은 잠시 레코드가 없다. 지운(dry_run이면 지울) 개수를 돌려준다.
    before_unlink: 지울 파일을 고른 뒤·다시 확인하기 전에 부를 함수(purge가 WAL 체크포인트를 여기서 한다).
    """
    grace = orphan_grace_hours() if grace_hours is None else grace_hours
    record_cutoff = _utcnow_naive() - timedelta(hours=grace)
    record_filter = (MediaFile.created_at < record_cutoff) & _unreferenced()
    report = {
        "media_records": db.scalar(select(func.count()).select_from(MediaFile).where(record_filter)) or 0,
        "dry_run": dry_run,
    }
    cutoff_ts = time.time() - grace * 3600
    if dry_run:
        # 지금 레코드를 지우면 고아가 될 파일까지 세지는 않는다(다음 실행에서 지운다).
        files = _orphan_files(db, cutoff_ts)
        report["photo_files"] = sum(1 for k, _ in files if k == KIND_PHOTO)
        report["tts_files"] = sum(1 for k, _ in files if k == KIND_TTS)
        return report

    result = db.execute(delete(MediaFile).where(record_filter).execution_options(synchronize_session=False))
    db.commit()
    report["media_records"] = result.rowcount or 0
    candidates = _orphan_files(db, cutoff_ts)
    if before_unlink is not None:
        before_unlink()
    # 고른 뒤 시간이 흘렀다. 그사이 직무 생성·단계 수정이 같은 문장의 TTS 캐시를 다시 썼으면(수정 시각 갱신 +
    # 레코드 생성) 지우면 안 된다. 지우기 직전에 레코드와 수정 시각을 한 번 더 확인하고, 실제로 지운 개수를 보고한다.
    still = {(k, p.name) for k, p in _orphan_files(db, cutoff_ts)}
    counts = {KIND_PHOTO: 0, KIND_TTS: 0}
    for kind, path in candidates:
        if (kind, path.name) not in still:
            continue
        path.unlink(missing_ok=True)
        counts[kind] += 1
    report["photo_files"] = counts[KIND_PHOTO]
    report["tts_files"] = counts[KIND_TTS]
    return report
