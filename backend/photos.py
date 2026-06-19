"""단계별 실제 사진 업로드 저장/검증.

ARASAAC 자동 상징은 '초안'일 뿐이라, 사업주가 현장 사진으로 교체하면 발달장애인의
인지부하를 가장 확실히 낮출 수 있다(개별화). 이 모듈은 안전한 저장만 담당한다.

보안:
- 매직바이트로 실제 이미지인지 검사(content-type/확장자 신뢰 안 함).
- 허용 포맷: jpg/png/webp/gif. (SVG는 스크립트 삽입 위험으로 불허.)
- 파일명은 서버가 UUID로 생성(클라이언트 파일명 미사용 → 경로 조작 차단).
- 크기 상한(기본 5MB).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

MAX_PHOTO_BYTES = int(os.getenv("MAX_PHOTO_BYTES", str(5 * 1024 * 1024)))


def get_photo_dir() -> Path:
    d = Path(os.getenv("PHOTO_DIR", "./data/photos"))
    d.mkdir(parents=True, exist_ok=True)
    return d


def sniff_image(data: bytes) -> str | None:
    """매직바이트로 이미지 포맷을 판별한다. 지원 포맷이면 확장자, 아니면 None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def save_photo(data: bytes) -> str:
    """검증된 이미지 바이트를 저장하고 파일명을 돌려준다."""
    ext = sniff_image(data) or ".bin"
    name = f"{uuid.uuid4().hex}{ext}"
    (get_photo_dir() / name).write_bytes(data)
    return name
