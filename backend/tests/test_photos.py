"""단계별 사진 업로드 테스트 (기능 5)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import photos  # noqa: E402
from conftest import auth  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPG = b"\xff\xd8\xff" + b"\x00" * 64
GIF = b"GIF89a" + b"\x00" * 64
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64


# ---------- 매직바이트 판별 ----------
def test_sniff_image_formats():
    assert photos.sniff_image(PNG) == ".png"
    assert photos.sniff_image(JPG) == ".jpg"
    assert photos.sniff_image(GIF) == ".gif"
    assert photos.sniff_image(WEBP) == ".webp"
    assert photos.sniff_image(b"this is not an image") is None
    assert photos.sniff_image(b"<svg>...</svg>") is None  # SVG 불허


def _make_task(client, token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"},
                    headers=auth(token))
    return r.json()


# ---------- 업로드 ----------
def test_upload_photo_replaces_symbol(client, employer_token, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_DIR", str(tmp_path))
    monkeypatch.setenv("PUBLIC_BACKEND_URL", "http://localhost:8000")
    task = _make_task(client, employer_token)
    step_id = task["steps"][0]["id"]

    r = client.post(f"/api/tasks/{task['id']}/steps/{step_id}/photo",
                    files={"file": ("photo.png", PNG, "image/png")},
                    headers=auth(employer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["symbol_source"] == "photo"
    assert body["needs_fallback"] is False
    assert body["symbol_url"].startswith("http://localhost:8000/api/photos/")
    # 실제 파일이 기록됐는지
    assert len(list(tmp_path.glob("*.png"))) == 1


def test_upload_rejects_non_image(client, employer_token, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_DIR", str(tmp_path))
    task = _make_task(client, employer_token)
    step_id = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{step_id}/photo",
                    files={"file": ("evil.png", b"not really an image", "image/png")},
                    headers=auth(employer_token))
    assert r.status_code == 400


def test_upload_rejects_oversized(client, employer_token, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_DIR", str(tmp_path))
    monkeypatch.setattr(photos, "MAX_PHOTO_BYTES", 100)
    import main
    monkeypatch.setattr(main, "MAX_PHOTO_BYTES", 100)
    task = _make_task(client, employer_token)
    step_id = task["steps"][0]["id"]
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500
    r = client.post(f"/api/tasks/{task['id']}/steps/{step_id}/photo",
                    files={"file": ("big.png", big, "image/png")},
                    headers=auth(employer_token))
    assert r.status_code == 413


def test_upload_requires_employer(client, worker_token, employer_token, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_DIR", str(tmp_path))
    task = _make_task(client, employer_token)
    step_id = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{step_id}/photo",
                    files={"file": ("p.png", PNG, "image/png")},
                    headers=auth(worker_token))
    assert r.status_code == 403


def test_remove_photo_reverts(client, employer_token, tmp_path, monkeypatch):
    monkeypatch.setenv("PHOTO_DIR", str(tmp_path))
    task = _make_task(client, employer_token)
    step_id = task["steps"][0]["id"]
    client.post(f"/api/tasks/{task['id']}/steps/{step_id}/photo",
                files={"file": ("p.png", PNG, "image/png")}, headers=auth(employer_token))
    r = client.delete(f"/api/tasks/{task['id']}/steps/{step_id}/photo", headers=auth(employer_token))
    assert r.status_code == 200
    assert r.json()["symbol_source"] == "fallback"
