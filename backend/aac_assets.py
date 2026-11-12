"""Helpers for serving project-owned AAC assets from the backend."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path


def _default_data_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "aac"


def get_aac_data_dir() -> Path:
    return Path(os.getenv("AAC_DATA_DIR", str(_default_data_dir()))).resolve()


def get_aac_image_dir() -> Path:
    return get_aac_data_dir() / "images"


def public_aac_url(url: str | None) -> str | None:
    """Convert AI service's backend-relative AAC URL to a browser-visible URL."""
    if not url:
        return url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("/api/aac/"):
        base = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
        return f"{base}{url}"
    return url


# --- (2b-1) 편집기 그림 정보(card_id·label) ---------------------------------------------------
# 그림 이름(label)은 단계에 저장하지 않는다. 자산 목록(aac_assets.json, ai_service와 같은 파일)에서 id로 찾는다.
# 그림 파일 이름 = 자산 id다(images/<job>/<ID>.webp).
_AAC_PATH = "/api/aac/images/"


def card_id_from_url(url: str | None) -> str | None:
    """AAC 그림 주소(공개 주소 포함)에서 그림 id를 꺼낸다. AAC 그림이 아니면 None."""
    if not url:
        return None
    path = url.split("?", 1)[0].split("#", 1)[0]
    i = path.find(_AAC_PATH)
    if i < 0:
        return None
    name = path[i + len(_AAC_PATH):].rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0]
    return stem or None


@lru_cache(maxsize=1)
def _labels() -> dict[str, str]:
    path = get_aac_data_dir() / "aac_assets.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(a.get("id")): str(a.get("label") or "") for a in payload.get("assets", []) if a.get("id")}


def asset_label(card_id: str | None) -> str:
    """그림 id의 이름(없으면 빈 글)."""
    return _labels().get(card_id or "", "") if card_id else ""
