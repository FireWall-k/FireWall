"""단계별 실제 사진 업로드 저장/검증.

ARASAAC 자동 상징은 '초안'일 뿐이라, 사업주가 현장 사진으로 교체하면 발달장애인의
인지부하를 가장 확실히 낮출 수 있다(개별화). 이 모듈은 안전한 저장만 담당한다.

보안:
- 매직바이트로 실제 이미지인지 검사(content-type/확장자 신뢰 안 함).
- 허용 포맷: jpg/png/webp/gif. (SVG는 스크립트 삽입 위험으로 불허.)
- 파일명은 서버가 UUID로 생성(클라이언트 파일명 미사용 → 경로 조작 차단).
- 크기 상한(기본 5MB).
- (Phase 0.3) Pillow로 디코딩해 다시 인코딩한다. 휴대폰 사진의 EXIF에는 촬영 위치(GPS)·기기·시각이 들어 있고,
  현장 사진에는 근로자가 찍히기 쉽다 — 원본 바이트를 그대로 저장하면 그 정보가 함께 남는다.
  새 픽셀만 WebP로 저장해 EXIF/XMP/ICC 같은 메타데이터를 모두 버리고, 긴 변을 1600px로 줄인다
  (근로자 화면의 그림은 최대 수백 px라 원본 해상도가 필요 없고, 저장량도 줄어든다).
- 디컴프레션 폭탄: 5MB 이하 파일도 수억 픽셀로 풀릴 수 있다. 픽셀 수를 헤더에서 먼저 보고 거부한다.
"""
from __future__ import annotations

import io
import os
import uuid
import warnings
from pathlib import Path

from PIL import Image, ImageOps

MAX_PHOTO_BYTES = int(os.getenv("MAX_PHOTO_BYTES", str(5 * 1024 * 1024)))
# 휴대폰 사진은 48MP(8000x6000)까지 나온다. 그보다 크면 사진이 아니라 공격일 가능성이 높다.
MAX_PHOTO_PIXELS = int(os.getenv("MAX_PHOTO_PIXELS", str(50_000_000)))
# Pillow 자체 상한도 같은 값으로 둔다(이 값의 2배를 넘으면 Pillow가 DecompressionBombError를 낸다).
# 아래 sanitize_image가 먼저 거부하므로 이 설정은 다른 경로로 Pillow를 쓰게 될 때의 안전망이다.
Image.MAX_IMAGE_PIXELS = MAX_PHOTO_PIXELS
MAX_PHOTO_EDGE = 1600
_WEBP_QUALITY = 85
# 매직바이트 검사를 통과한 포맷만 Pillow가 열게 한다(다른 포맷 디코더의 공격면을 열지 않는다).
_PIL_FORMATS = ("JPEG", "PNG", "WEBP", "GIF")


class ImageRejected(ValueError):
    """사진으로 받을 수 없는 파일. status는 HTTP 상태 코드(400 형식 오류 / 413 너무 큼)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


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


def sanitize_image(data: bytes) -> bytes:
    """메타데이터를 버리고 긴 변 MAX_PHOTO_EDGE 이하 WebP로 다시 인코딩한 바이트를 돌려준다.

    받을 수 없는 파일이면 ImageRejected. 움직이는 GIF는 첫 프레임만 쓴다(단계 그림은 정지 화면이다).
    """
    if sniff_image(data) is None:
        raise ImageRejected("이미지 파일(jpg/png/webp/gif)만 업로드할 수 있습니다.")
    try:
        with warnings.catch_warnings():
            # Pillow는 상한~2배 사이를 경고만 하고 연다. 경고도 오류로 바꿔 거부한다.
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(io.BytesIO(data), formats=_PIL_FORMATS)
            width, height = img.size
            if width * height > MAX_PHOTO_PIXELS:
                # Image.open은 헤더만 읽는다. 픽셀을 풀기 전에 여기서 멈춘다.
                raise ImageRejected("사진 해상도가 너무 큽니다.", status=413)
            if img.format == "JPEG":
                # JPEG는 디코딩 단계에서 1/2·1/4·1/8로 줄여 읽을 수 있다 → 큰 사진의 메모리 사용을 줄인다.
                img.draft("RGB", (MAX_PHOTO_EDGE, MAX_PHOTO_EDGE))
            # 휴대폰 사진은 픽셀은 눕혀 두고 EXIF 방향값으로 세운다. EXIF를 버리기 전에 픽셀을 돌려 둬야
            # 근로자 화면에 사진이 옆으로 누워 나오지 않는다.
            img = ImageOps.exif_transpose(img)
            has_alpha = img.mode in ("RGBA", "LA", "PA") or (
                img.mode == "P" and "transparency" in img.info)
            img = img.convert("RGBA" if has_alpha else "RGB")
            img.thumbnail((MAX_PHOTO_EDGE, MAX_PHOTO_EDGE), Image.Resampling.LANCZOS)
            # convert/exif_transpose는 원본의 info(exif·icc_profile·xmp 등)를 그대로 복사한다.
            # WebP 저장은 지금 save 인자로 준 메타데이터만 쓰지만, Pillow 버전이 바뀌어도 새지 않게 비운다.
            img.info.clear()
            out = io.BytesIO()
            img.save(out, "WEBP", quality=_WEBP_QUALITY, method=4)
    except ImageRejected:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageRejected("사진 해상도가 너무 큽니다.", status=413) from None
    except Exception:  # noqa: BLE001 - 깨진 파일·지원 안 하는 변형은 모두 "이미지 아님"으로 거부
        raise ImageRejected("이미지를 읽을 수 없습니다. 다른 사진으로 다시 올려 주세요.") from None
    return out.getvalue()


def save_photo(data: bytes) -> str:
    """정제된(sanitize_image) WebP 바이트를 저장하고 상대 키(파일명)를 돌려준다."""
    name = f"{uuid.uuid4().hex}.webp"
    (get_photo_dir() / name).write_bytes(data)
    return name
