"""Helpers for serving project-owned AAC assets from the backend."""
from __future__ import annotations

import os
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
