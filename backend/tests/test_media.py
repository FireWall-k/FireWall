"""Phase 0.3 사진·TTS 파일 보호 테스트.

지키는 것:
1. 사진·TTS는 무인증 정적 경로(/api/photos, /api/tts)로 나가지 않는다. 응답에 실린 단기 서명 URL로만 받는다.
2. 서명을 위조하거나 만료된 URL, 다른 media id에 옮겨 붙인 서명은 거부한다(타 테넌트 접근 포함).
3. 업로드한 사진은 EXIF(GPS 포함)가 지워지고 긴 변 1600px 이하 WebP로 다시 인코딩된다.
4. 단계에 붙일 수 있는 사진은 이 사업장 소유 레코드뿐이다(update_step이 타 테넌트 media id를 거부).
5. 고아 파일·참조 없는 레코드는 gc-media가 지운다(dry-run은 아무것도 지우지 않는다).
6. TTS 파일은 사업장별로 따로 만든다(문장에 이름이 들어갈 수 있어 테넌트 간 공유 캐시를 쓰지 않는다).
"""
import os
import time
import uuid
from io import BytesIO
from urllib.parse import parse_qs, urlparse

import pytest
from PIL import Image
from sqlalchemy import select

import main
import manage
import media
import photos
import tts
from conftest import auth, publish, delete_task
from database import SessionLocal
from models import MediaFile, Step


# --- 도우미 ------------------------------------------------------------------

def _new_employer(client) -> str:
    login = f"media-{uuid.uuid4().hex[:8]}"
    manage.create_employer(login, "", "미디어 테스트", "correct-horse-1")
    r = client.post("/api/auth/login", json={"login_id": login, "password": "correct-horse-1"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _jpeg_with_gps(size=(2400, 1800)) -> bytes:
    """GPS·카메라 정보가 든 JPEG. 휴대폰 사진처럼 촬영 위치가 EXIF에 들어 있다."""
    img = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    exif[0x010F] = "TestCam"  # Make
    gps = exif.get_ifd(0x8825)  # GPSInfo
    gps[1] = "N"
    gps[2] = (37.0, 33.0, 59.0)
    gps[3] = "E"
    gps[4] = (126.0, 58.0, 40.0)
    buf = BytesIO()
    img.save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def _png(size=(32, 32)) -> bytes:
    buf = BytesIO()
    Image.new("RGBA", size, (0, 128, 0, 200)).save(buf, "PNG")
    return buf.getvalue()


def _task(client, token) -> dict:
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client, token, task, step_index=0, data=None) -> dict:
    step_id = task["steps"][step_index]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{step_id}/photo",
                    files={"file": ("photo.jpg", data or _jpeg_with_gps(), "image/jpeg")},
                    headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _path_of(url: str) -> str:
    """절대 URL을 TestClient가 받는 경로+쿼리로 바꾼다."""
    p = urlparse(url)
    return f"{p.path}?{p.query}" if p.query else p.path


def _media_id(url: str) -> str:
    return urlparse(url).path.rsplit("/", 1)[-1]


# --- 1. 공개 정적 경로 제거 ------------------------------------------------------

def test_legacy_static_paths_are_gone(client, tmp_path):
    photo_dir = photos.get_photo_dir()
    name = uuid.uuid4().hex + ".png"
    (photo_dir / name).write_bytes(_png())
    tts_name = uuid.uuid4().hex + ".mp3"
    (tts.get_tts_cache_dir() / tts_name).write_bytes(b"ID3")
    try:
        assert client.get(f"/api/photos/{name}").status_code == 404
        assert client.get(f"/api/tts/{tts_name}").status_code == 404
    finally:
        (photo_dir / name).unlink(missing_ok=True)
        (tts.get_tts_cache_dir() / tts_name).unlink(missing_ok=True)


def test_aac_images_stay_public(client):
    # 자체 AAC 그림은 공개 자산이라 서명 없이 그대로 나간다(마운트가 남아 있어야 한다).
    assert any(getattr(r, "path", "") == "/api/aac/images" for r in main.app.routes)


# --- 2. 업로드 → EXIF 제거·리사이즈·재인코딩 -------------------------------------

def test_upload_strips_exif_gps_and_resizes(client, employer_token):
    original = _jpeg_with_gps()
    # 전제: 픽스처에 GPS가 실제로 들어 있다.
    assert dict(Image.open(BytesIO(original)).getexif().get_ifd(0x8825))

    task = _task(client, employer_token)
    step = _upload(client, employer_token, task, data=original)
    assert step["symbol_source"] == "photo"
    assert "/api/media/" in step["symbol_url"]

    r = client.get(_path_of(step["symbol_url"]))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "image/webp"
    assert r.headers.get("x-content-type-options") == "nosniff"
    served = Image.open(BytesIO(r.content))
    assert served.format == "WEBP"
    assert max(served.size) <= 1600
    assert not dict(served.getexif())
    assert "exif" not in served.info and "xmp" not in served.info
    assert b"Exif" not in r.content and b"TestCam" not in r.content

    with SessionLocal() as db:
        rec = db.get(MediaFile, _media_id(step["symbol_url"]))
        assert rec is not None and rec.kind == "photo"
        assert rec.storage_key.endswith(".webp") and "/" not in rec.storage_key
        assert rec.bytes == len(r.content)
        # DB에는 URL이 아니라 media id만 남는다.
        row = db.get(Step, step["id"])
        assert row.symbol_media_id == rec.id and row.symbol_url is None


def test_upload_rejects_svg_and_garbage(client, employer_token):
    task = _task(client, employer_token)
    step_id = task["steps"][0]["id"]
    for data in (b"<svg xmlns='http://www.w3.org/2000/svg'></svg>",
                 b"\x89PNG\r\n\x1a\n" + b"\x00" * 64):  # 매직바이트만 맞고 디코딩 안 되는 파일
        r = client.post(f"/api/tasks/{task['id']}/steps/{step_id}/photo",
                        files={"file": ("x.png", data, "image/png")}, headers=auth(employer_token))
        assert r.status_code == 400, r.text


def test_upload_rejects_decompression_bomb(client, employer_token, monkeypatch):
    # 작은 파일이 거대한 픽셀 수로 풀리는 이미지는 디코딩 전에 거부한다.
    monkeypatch.setattr(photos, "MAX_PHOTO_PIXELS", 1000)
    task = _task(client, employer_token)
    step_id = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{step_id}/photo",
                    files={"file": ("big.png", _png((100, 100)), "image/png")},
                    headers=auth(employer_token))
    assert r.status_code == 413, r.text


# --- 3. 서명 URL ------------------------------------------------------------

def test_forged_or_expired_signature_is_rejected(client, employer_token):
    task = _task(client, employer_token)
    url = _upload(client, employer_token, task)["symbol_url"]
    mid = _media_id(url)
    q = parse_qs(urlparse(url).query)
    exp, sig = q["exp"][0], q["sig"][0]

    assert client.get(f"/api/media/{mid}").status_code == 403  # 서명 없음
    assert client.get(f"/api/media/{mid}?exp={exp}&sig={'0' * len(sig)}").status_code == 403
    assert client.get(f"/api/media/{mid}?exp={int(exp) + 3600}&sig={sig}").status_code == 403  # 만료 늘리기
    assert client.get(f"/api/media/{mid}?exp=abc&sig={sig}").status_code == 403

    past = int(time.time()) - 10
    expired = f"/api/media/{mid}?exp={past}&sig={media.signature(mid, past)}"
    assert client.get(expired).status_code == 403


def test_other_tenant_cannot_fetch_photo(client, employer_token):
    task = _task(client, employer_token)
    url = _upload(client, employer_token, task)["symbol_url"]
    mid = _media_id(url)
    other = _new_employer(client)
    # 다른 사업장은 이 사진의 서명 URL을 받을 길이 없다. id만 알아도, 토큰을 붙여도 받을 수 없다.
    assert client.get(f"/api/media/{mid}", headers=auth(other)).status_code == 403
    # 자기 사진의 서명을 남의 media id에 옮겨 붙여도 안 된다(서명이 id에 묶여 있다).
    other_task = _task(client, other)
    own = _upload(client, other, other_task)["symbol_url"]
    q = urlparse(own).query
    assert client.get(f"/api/media/{mid}?{q}").status_code == 403


def test_signed_url_bucket_is_stable_and_expires(monkeypatch):
    monkeypatch.setenv("MEDIA_URL_TTL_SECONDS", "600")
    now = 1_000_000_000
    a = media.signed_url("m1", now=now)
    b = media.signed_url("m1", now=now + 10)
    # 같은 구간 안의 응답은 같은 URL이라 브라우저 캐시가 그대로 쓰인다.
    assert a == b
    exp = int(parse_qs(urlparse(a).query)["exp"][0])
    assert now + 600 <= exp <= now + 600 + media.EXP_BUCKET_SECONDS
    assert media.verify("m1", str(exp), parse_qs(urlparse(a).query)["sig"][0], now=now)
    assert not media.verify("m1", str(exp), parse_qs(urlparse(a).query)["sig"][0], now=exp + 1)


def test_worker_today_returns_fresh_signed_urls(client, employer_token, worker_token):
    task = _task(client, employer_token)
    _upload(client, employer_token, task)
    publish(client, employer_token, task["id"])
    client.post(f"/api/tasks/{task['id']}/assignments", json={"worker_ids": ["wrk-demo"]},
                headers=auth(employer_token))
    cards = client.get("/api/worker/me/today", headers=auth(worker_token)).json()
    card = next(c for c in cards if c["task_id"] == task["id"])
    url = card["steps"][0]["symbol_url"]
    assert "/api/media/" in url
    assert client.get(_path_of(url)).status_code == 200


# --- 4. update_step: 소유 레코드 조회 ----------------------------------------------

def test_update_step_accepts_own_photo_media(client, employer_token):
    task = _task(client, employer_token)
    url = _upload(client, employer_token, task, step_index=0)["symbol_url"]
    step2 = task["steps"][1]["id"]
    r = client.patch(f"/api/tasks/{task['id']}/steps/{step2}", json={"symbol_url": url},
                     headers=auth(employer_token))
    assert r.status_code == 200, r.text
    assert r.json()["symbol_source"] == "photo"
    assert _media_id(r.json()["symbol_url"]) == _media_id(url)


def test_update_step_rejects_other_tenant_media(client, employer_token):
    task = _task(client, employer_token)
    url = _upload(client, employer_token, task)["symbol_url"]
    other = _new_employer(client)
    other_task = _task(client, other)
    step_id = other_task["steps"][0]["id"]
    for candidate in (url, f"/api/media/{_media_id(url)}", f"/api/media/{uuid.uuid4()}"):
        r = client.patch(f"/api/tasks/{other_task['id']}/steps/{step_id}", json={"symbol_url": candidate},
                         headers=auth(other))
        assert r.status_code == 400, (candidate, r.text)
    with SessionLocal() as db:
        assert db.get(Step, step_id).symbol_media_id is None


# --- 5. 정리: 사진 교체·되돌리기, gc-media -----------------------------------------

def test_replacing_or_removing_photo_deletes_old_file(client, employer_token):
    task = _task(client, employer_token)
    first = _upload(client, employer_token, task)["symbol_url"]
    with SessionLocal() as db:
        first_path = photos.get_photo_dir() / db.get(MediaFile, _media_id(first)).storage_key
    assert first_path.exists()
    second = _upload(client, employer_token, task, data=_png())["symbol_url"]
    # 교체된 옛 사진은 어느 단계도 쓰지 않으므로 레코드와 파일을 바로 지운다(사람이 찍힌 사진일 수 있다).
    assert not first_path.exists()
    with SessionLocal() as db:
        assert db.get(MediaFile, _media_id(first)) is None
        second_path = photos.get_photo_dir() / db.get(MediaFile, _media_id(second)).storage_key
    r = client.delete(f"/api/tasks/{task['id']}/steps/{task['steps'][0]['id']}/photo",
                      headers=auth(employer_token))
    assert r.status_code == 200 and r.json()["symbol_url"] is None
    assert not second_path.exists()


def test_deleting_task_releases_its_photos(client, employer_token):
    task = _task(client, employer_token)
    url = _upload(client, employer_token, task)["symbol_url"]
    with SessionLocal() as db:
        path = photos.get_photo_dir() / db.get(MediaFile, _media_id(url)).storage_key
    assert delete_task(client, task['id'], auth(employer_token)).status_code == 200
    assert not path.exists()
    assert client.get(_path_of(url)).status_code == 404


def test_gc_media_removes_orphans_and_respects_dry_run(client, employer_token, capsys):
    task = _task(client, employer_token)
    kept_url = _upload(client, employer_token, task)["symbol_url"]
    photo_dir = photos.get_photo_dir()
    tts_dir = tts.get_tts_cache_dir()
    old = time.time() - 3 * 86400

    orphan_file = photo_dir / f"{uuid.uuid4().hex}.webp"   # 레코드 없는 파일
    orphan_file.write_bytes(b"x")
    os.utime(orphan_file, (old, old))
    fresh_orphan = photo_dir / f"{uuid.uuid4().hex}.webp"  # 막 저장돼 아직 커밋 전일 수 있는 파일
    fresh_orphan.write_bytes(b"x")
    stray_tts = tts_dir / f"{uuid.uuid4().hex}.mp3"
    stray_tts.write_bytes(b"ID3")
    os.utime(stray_tts, (old, old))
    unrelated = photo_dir / "README.txt"                    # 이름 규칙에 안 맞는 파일은 건드리지 않는다
    unrelated.write_bytes(b"keep")

    # 참조 없는 레코드(+ 그 파일)
    dangling_key = f"{uuid.uuid4().hex}.webp"
    (photo_dir / dangling_key).write_bytes(b"x")
    os.utime(photo_dir / dangling_key, (old, old))
    with SessionLocal() as db:
        emp = db.get(Step, task["steps"][0]["id"]).task.employer_id
        rec = MediaFile(employer_id=emp, kind="photo", storage_key=dangling_key, sha256="0" * 64, bytes=1)
        db.add(rec)
        db.flush()
        rec.created_at = rec.created_at.replace(year=rec.created_at.year - 1)
        db.commit()
        dangling_id = rec.id

    try:
        manage.main(["gc-media", "--dry-run"])
        out = capsys.readouterr().out
        assert "dry-run" in out or "지울 대상" in out
        assert orphan_file.exists() and stray_tts.exists() and (photo_dir / dangling_key).exists()
        with SessionLocal() as db:
            assert db.get(MediaFile, dangling_id) is not None

        manage.main(["gc-media"])
        assert not orphan_file.exists()
        assert not stray_tts.exists()
        assert not (photo_dir / dangling_key).exists()
        assert fresh_orphan.exists()
        assert unrelated.exists()
        with SessionLocal() as db:
            assert db.get(MediaFile, dangling_id) is None
            kept = db.get(MediaFile, _media_id(kept_url))
            assert kept is not None and (photo_dir / kept.storage_key).exists()
    finally:
        for p in (fresh_orphan, unrelated):
            p.unlink(missing_ok=True)


# --- 6. TTS: 사업장별 소유 ----------------------------------------------------------

def test_tts_is_owned_per_employer_and_served_signed(client, monkeypatch):
    calls = []

    def fake_google(text, out_path):
        calls.append(text)
        out_path.write_bytes(b"ID3" + text.encode("utf-8"))

    tts._reset_state()
    monkeypatch.setattr(tts, "_synthesize_google", fake_google)
    monkeypatch.setattr(main, "synthesize_tts", tts.synthesize_tts)
    a, b = _new_employer(client), _new_employer(client)
    ta, tb = _task(client, a), _task(client, b)
    url_a = ta["steps"][0]["tts_audio_url"]
    url_b = tb["steps"][0]["tts_audio_url"]
    assert url_a and url_b and "/api/media/" in url_a
    # 같은 문장이라도 사업장마다 따로 합성·저장한다(공유 캐시 = 다른 사업장 문장 존재 여부를 알려 주는 통로).
    assert len(calls) == 4
    with SessionLocal() as db:
        ra, rb = db.get(MediaFile, _media_id(url_a)), db.get(MediaFile, _media_id(url_b))
        assert ra.kind == rb.kind == "tts"
        assert ra.storage_key != rb.storage_key
    r = client.get(_path_of(url_a))
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"
    assert client.get(f"/api/media/{_media_id(url_a)}").status_code == 403


def test_tts_scope_changes_cache_key():
    assert tts._google_voice_key("같은 문장", "emp-a") != tts._google_voice_key("같은 문장", "emp-b")
    with pytest.raises(ValueError):
        tts.synthesize_tts("문장", "")


# --- 7. AAC 그림 URL: 퍼센트 인코딩 경로 조작 ---------------------------------------

@pytest.mark.parametrize("url", [
    "http://localhost:8000/api/aac/images/%2e%2e/%2e%2e/etc/passwd",
    "/api/aac/images/%2E%2E/photos/x.webp",
    "/api/aac/images/..%2f..%2fapi/media/x",
    "/api/aac/images/retail%2f%2fevil.example/x.webp",
    "/api/aac/images/%252e%252e/x.webp",       # 이중 인코딩(한 번 디코딩하면 %2e%2e)
    "/api/aac/images/retail%5c..%5c..%5cx.webp",  # 역슬래시
    "/api/aac/images/retail/x.webp%00.png",
    "/api/aac/images/./retail/x.webp",
    # 브라우저 URL 파서는 탭·줄바꿈을 지운 뒤 경로를 정규화한다. "." + 탭 + "."은 서버 검사에서는 "."도 ".."도
    # 아니지만 브라우저에서는 ".."이 되어 AAC 폴더 밖을 가리킨다.
    "/api/aac/images/.\t./x",
    "/api/aac/images/.\n./.\r./api/media/x",
    "/api/aac/images/retail/%09x.webp",
    "/api/aac/images/retail/x\x7f.webp",
])
def test_own_image_url_rejects_encoded_traversal(url):
    """브라우저·프록시는 %2e%2e를 ..로 풀어 경로를 정규화한다. 인코딩된 채로 검사하면 ".."이 안 보여
    통과하고, 근로자 화면에서는 AAC 폴더 밖 경로를 요청하게 된다."""
    assert main._is_own_image_url(url) is False


def test_own_image_url_accepts_plain_aac_paths():
    assert main._is_own_image_url("http://localhost:8000/api/aac/images/retail/RETAIL_001.webp")
    assert main._is_own_image_url("/api/aac/images/retail/RETAIL_001.webp")
    # 한글 등 정상 문자를 인코딩한 경로는 디코딩해도 안전하므로 받는다.
    assert main._is_own_image_url("/api/aac/images/retail/%EC%83%81%EC%9E%90.webp")


def test_update_step_rejects_encoded_traversal(client, employer_token):
    task = _task(client, employer_token)
    step_id = task["steps"][0]["id"]
    r = client.patch(f"/api/tasks/{task['id']}/steps/{step_id}",
                     json={"symbol_url": "/api/aac/images/%2e%2e/%2e%2e/etc/passwd"},
                     headers=auth(employer_token))
    assert r.status_code == 400


# --- 8. release()와 update_step 경합 ----------------------------------------------

def test_update_step_does_not_attach_media_released_concurrently(client, employer_token, monkeypatch):
    """update_step이 소유 레코드를 확인한 직후, 다른 요청(사진 되돌리기)이 마지막 참조를 떼고 release()로
    레코드·파일을 지우면, 예전에는 update_step이 그대로 커밋해 단계가 지워진 media id를 가리켰다
    (근로자 화면에 깨진 그림, 레코드 없는 id). 이제는 붙이지 않고 409로 다시 시도하게 한다."""
    task = _task(client, employer_token)
    url = _upload(client, employer_token, task, step_index=0)["symbol_url"]
    media_id = _media_id(url)
    step0, step1 = task["steps"][0]["id"], task["steps"][1]["id"]
    real_owned = media.owned

    def owned_then_concurrent_release(db, employer_id, mid, kind):
        rec = real_owned(db, employer_id, mid, kind)
        # 확인과 붙이기 사이에 끼어드는 다른 요청(DELETE .../photo와 같은 일).
        with SessionLocal() as other:
            other.get(Step, step0).symbol_media_id = None
            other.commit()
            assert media.release(other, [mid]) == 1
        return rec

    monkeypatch.setattr(media, "owned", owned_then_concurrent_release)
    r = client.patch(f"/api/tasks/{task['id']}/steps/{step1}", json={"symbol_url": url},
                     headers=auth(employer_token))
    assert r.status_code == 409, r.text
    with SessionLocal() as db:
        assert db.get(MediaFile, media_id) is None
        assert db.get(Step, step1).symbol_media_id is None  # 지워진 media를 가리키지 않는다
    # 경합이 없으면 정상으로 붙는다(회귀 확인).
    monkeypatch.setattr(media, "owned", real_owned)
    url2 = _upload(client, employer_token, task, step_index=0)["symbol_url"]
    r = client.patch(f"/api/tasks/{task['id']}/steps/{step1}", json={"symbol_url": url2},
                     headers=auth(employer_token))
    assert r.status_code == 200, r.text


def test_update_step_revalidates_after_commit(client, employer_token, monkeypatch):
    """잠금을 잡은 뒤에도(다른 DB 엔진에서 격리 수준이 달라도) 커밋 직후 레코드가 사라졌으면 단계를 되돌린다."""
    task = _task(client, employer_token)
    url = _upload(client, employer_token, task, step_index=0)["symbol_url"]
    media_id = _media_id(url)
    step0, step1 = task["steps"][0]["id"], task["steps"][1]["id"]
    real_release = media.release

    def release_and_steal(db, ids):
        # update_step의 커밋 직후 다른 연결이 레코드를 강제로 지운 상황(FK 미적용 SQLite 기준).
        if not getattr(release_and_steal, "done", False):
            release_and_steal.done = True
            with SessionLocal() as other:
                other.get(Step, step0).symbol_media_id = None
                other.get(Step, step1).symbol_media_id = None
                other.commit()
                real_release(other, [media_id])
                other.get(Step, step1).symbol_media_id = media_id  # 커밋된 참조만 남기고 레코드는 없음
                other.commit()
        return real_release(db, ids)

    monkeypatch.setattr(media, "release", release_and_steal)
    r = client.patch(f"/api/tasks/{task['id']}/steps/{step1}", json={"symbol_url": url},
                     headers=auth(employer_token))
    assert r.status_code == 409, r.text
    with SessionLocal() as db:
        assert db.get(Step, step1).symbol_media_id is None
