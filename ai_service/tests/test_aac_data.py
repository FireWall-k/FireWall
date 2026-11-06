"""AAC 데이터셋 정합성 테스트 — 이미지·메타데이터·인덱스·임베딩이 서로 맞는지 CI에서 확인한다.

2026-11 점검에서 드러난 문제를 회귀 방지한다: README와 실제 장수 불일치, 메타데이터 없는 고아
이미지, 768이 아닌 원본 해상도 커밋, 같은 그림이 다른 ID로 두 번 등록, 동작 카드인데 동사가
없는 라벨(장면 묘사문), `도구 ` 접두사가 남은 라벨, 라벨을 고친 뒤 재생성하지 않은 인덱스·임베딩.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path

import pytest

import embeddings
import local_aac

DATA_DIR = local_aac.get_data_dir()
ASSETS_PATH = DATA_DIR / "aac_assets.json"
INDEX_PATH = DATA_DIR / "aac_index.json"
IMAGE_DIR = DATA_DIR / "images"
EXPECTED_SIZE = (768, 768)

pytestmark = pytest.mark.skipif(not ASSETS_PATH.exists(), reason="AAC 데이터셋이 없는 환경")


def _webp_size(path: Path) -> tuple[int, int] | None:
    """WebP 헤더만 읽어 (너비, 높이)를 돌려준다 — Pillow 없이 동작한다."""
    with path.open("rb") as f:
        head = f.read(40)
    if head[:4] != b"RIFF" or head[8:12] != b"WEBP":
        return None
    chunk = head[12:16]
    if chunk == b"VP8 ":
        w, h = struct.unpack("<HH", head[26:30])
        return w & 0x3FFF, h & 0x3FFF
    if chunk == b"VP8L":
        bits = int.from_bytes(head[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        return (int.from_bytes(head[24:27], "little") + 1,
                int.from_bytes(head[27:30], "little") + 1)
    return None


def _is_present_tense_sentence(label: str) -> bool:
    """'…한다/…는다/…ㄴ다'(놓는다·가리킨다·민다)로 끝나는 평서문인지 — 끝 '다' 앞 음절의 받침이 ㄴ이어야 한다."""
    label = label.strip()
    if len(label) < 2 or not label.endswith("다"):
        return False
    prev = ord(label[-2]) - 0xAC00
    return 0 <= prev < 11172 and prev % 28 == 4  # 받침 ㄴ


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(ASSETS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def assets(payload: dict) -> list[dict]:
    return payload["assets"]


@pytest.fixture(scope="module")
def index() -> dict:
    return json.loads(INDEX_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def disk_images() -> dict[str, Path]:
    return {f"{p.parent.name}/{p.name}": p for p in IMAGE_DIR.glob("*/*.webp")}


def test_header_counts_match_assets(payload: dict, assets: list[dict]) -> None:
    assert payload["asset_count"] == len(assets)
    per_job = Counter(a["job"].upper() for a in assets)
    assert payload["jobs"] == dict(per_job)
    assert tuple(payload["image_size"]) == EXPECTED_SIZE


def test_ids_unique(assets: list[dict]) -> None:
    dup = [i for i, n in Counter(a["id"] for a in assets).items() if n > 1]
    assert not dup, f"중복 ID: {dup}"


def test_every_asset_has_image_and_every_image_has_asset(assets: list[dict], disk_images: dict) -> None:
    meta = {a["image"] for a in assets}
    missing = sorted(meta - set(disk_images))
    orphan = sorted(set(disk_images) - meta)
    assert not missing, f"메타데이터만 있고 그림이 없음: {missing[:10]}"
    assert not orphan, f"그림만 있고 메타데이터가 없음: {orphan[:10]}"


def test_images_are_normalized_webp(disk_images: dict) -> None:
    wrong = {k: _webp_size(p) for k, p in disk_images.items() if _webp_size(p) != EXPECTED_SIZE}
    assert not wrong, f"768x768이 아닌 이미지 {len(wrong)}장: {list(wrong.items())[:5]}"


def test_no_byte_identical_duplicate_images(disk_images: dict) -> None:
    by_hash: dict[str, list[str]] = {}
    for key, path in disk_images.items():
        by_hash.setdefault(hashlib.md5(path.read_bytes()).hexdigest(), []).append(key)
    dups = [v for v in by_hash.values() if len(v) > 1]
    assert not dups, f"같은 그림이 다른 ID로 등록됨: {dups[:5]}"


def test_labels_follow_style(assets: list[dict]) -> None:
    bad_prefix = [a["id"] for a in assets if a["label"].startswith("도구 ")]
    assert not bad_prefix, f"'도구 ' 접두사가 남은 라벨: {bad_prefix[:10]}"
    # 동작 카드는 '한 단계 = 한 동작' 문장이어야 한다(…한다/…는다). 장면 묘사("…하는 작업자")는 support.
    not_sentence = [(a["id"], a["label"]) for a in assets
                    if a["asset_type"] == "action" and not _is_present_tense_sentence(a["label"])]
    assert not not_sentence, f"동작 카드인데 동작문이 아님: {not_sentence[:10]}"
    empty = [a["id"] for a in assets if not a["label"].strip()]
    assert not empty


def test_index_covers_all_assets(assets: list[dict], index: dict) -> None:
    ids = {a["id"] for a in assets}
    entries = {e["id"] for e in index["entries"]}
    assert ids == entries, f"인덱스 누락 {sorted(ids - entries)[:5]} / 잉여 {sorted(entries - ids)[:5]}"
    assert index["entry_count"] == len(index["entries"])
    assert index["source_count"] == len(assets)


def test_index_digest_matches_assets(assets: list[dict], index: dict) -> None:
    """라벨을 고치고 인덱스를 재생성하지 않으면 여기서 걸린다(scripts/build_aac_index.py 기준)."""
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import build_aac_index  # noqa: WPS433
    finally:
        sys.path.remove(str(scripts_dir))
    assert index["source_digest"] == build_aac_index.source_digest(assets)


def test_action_cards_have_verb_in_index(assets: list[dict], index: dict) -> None:
    frames = {e["id"]: e.get("frame") or {} for e in index["entries"]}
    missing = [a["id"] for a in assets if a["asset_type"] == "action" and not frames[a["id"]].get("verb")]
    assert not missing, f"동작 카드인데 인덱스 verb가 없음: {missing[:10]}"
    wrong_card = [a["id"] for a in assets if a["asset_type"] == "action" and frames[a["id"]].get("is_object_card")]
    assert not wrong_card, f"동작 카드인데 is_object_card=true: {wrong_card[:10]}"


def test_embeddings_are_fresh() -> None:
    """라벨·검색어를 고친 뒤 build_aac_embeddings.py를 다시 돌리지 않으면 서비스가 임베딩을 끈다."""
    np = pytest.importorskip("numpy")
    store = DATA_DIR / embeddings.STORE_FILENAME
    assert store.exists(), f"없음: {store}"
    stored = str(np.load(store, allow_pickle=False)["digest"])
    assert stored == embeddings.current_digest(), "임베딩이 낡음 — scripts/build_aac_embeddings.py 재실행"
