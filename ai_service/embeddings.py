"""질의·자산 임베딩 유사도 — 규칙 점수에 '더하기만' 하는 보조 신호.

왜 있나: 규칙 점수(자카드·동사 원형 등)는 표현이 달라지면 정답을 못 올린다("정리하세요"↔"놓는다").
임베딩은 뜻이 가까운 후보를 올려 주고, 그러면 채택 게이트(임계값·여유)가 정답과 오답을 더 잘 가른다.
블라인드 실측(독립 249단계): 오답 채택 19건 → 9건(개선 10 / 악화 0, McNemar p=0.002), 커버리지 유지.

지켜야 할 것:
- 어떤 이유로든(키 없음, 파일 없음/낡음, 호출 실패·지연) 임베딩을 못 쓰면 None을 돌려주고,
  호출자는 임베딩 없는 기존 방식(기존 임계값)으로 물러난다. 임베딩 장애가 서비스 장애가 되면 안 된다.
- 점수 척도가 임베딩 유무로 달라지므로 임계값도 두 벌이다(local_aac.decide).
- 자산 벡터가 현재 라벨·검색어와 어긋나면(인덱스를 고치고 다시 안 만든 경우) 쓰지 않는다.
"""
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

import llm

logger = logging.getLogger("ai_harness.embeddings")

STORE_FILENAME = "aac_embeddings.npz"

# 질의 호출이 느리거나 실패하면 이 시간 동안은 시도조차 하지 않는다(요청마다 타임아웃을
# 기다리게 되는 걸 막는다). 짧은 타임아웃 + 쿨다운이 함께 있어야 장애가 번지지 않는다.
_QUERY_TIMEOUT = float(os.getenv("AAC_EMBED_TIMEOUT", "3"))
_COOLDOWN_SEC = float(os.getenv("AAC_EMBED_COOLDOWN", "60"))
_CACHE_SIZE = 512

_lock = threading.Lock()
_cache: "OrderedDict[str, np.ndarray]" = OrderedDict()
_cooldown_until = 0.0


def mode() -> str:
    """AAC_EMBEDDINGS: 'off'면 끈다. 그 외에는 키와 자산 파일이 있을 때 자동으로 켠다."""
    return os.getenv("AAC_EMBEDDINGS", "auto").strip().lower()


def asset_texts(asset: dict, index_entry: dict | None) -> tuple[str, str]:
    """(라벨, 라벨+검색어) — 자산 임베딩에 넣는 두 텍스트. 만들 때와 검사할 때 같아야 한다."""
    entry = index_entry or {}
    label = str(asset.get("label", ""))
    kws = list(entry.get("keywords_ko", [])) + list(entry.get("keywords_en", []))
    return label, label + ". " + ", ".join(kws)


def texts_digest(ids: list[str], label_texts: list[str], full_texts: list[str],
                 model: str, dims: int) -> str:
    h = hashlib.sha256()
    h.update(f"{model}|{dims}".encode())
    for i, lt, ft in zip(ids, label_texts, full_texts):
        h.update(f"\n{i}\t{lt}\t{ft}".encode())
    return h.hexdigest()


@dataclass(frozen=True)
class _Store:
    row_of: dict[str, int]
    label_vecs: np.ndarray  # (N, D) 정규화됨
    full_vecs: np.ndarray


def _current_texts() -> tuple[list[str], list[str], list[str]]:
    # local_aac가 이 모듈을 import하므로 순환을 피하려고 함수 안에서 가져온다.
    import local_aac

    index = local_aac.load_index()
    ids, labels, fulls = [], [], []
    for asset in local_aac.load_assets():
        lt, ft = asset_texts(asset, index.get(asset["id"]))
        ids.append(asset["id"])
        labels.append(lt)
        fulls.append(ft)
    return ids, labels, fulls


def current_digest() -> str:
    ids, labels, fulls = _current_texts()
    return texts_digest(ids, labels, fulls, llm.EMBED_MODEL, llm.EMBED_DIMS)


@lru_cache(maxsize=1)
def _load_store() -> _Store | None:
    import local_aac

    path = local_aac.get_data_dir() / STORE_FILENAME
    if not path.exists():
        logger.info("자산 임베딩 파일이 없어 임베딩을 쓰지 않습니다: %s", path)
        return None
    try:
        z = np.load(path, allow_pickle=False)
        ids = [str(i) for i in z["ids"]]
        stored_digest = str(z["digest"])
        model, dims = str(z["model"]), int(z["dims"])
        label_vecs, full_vecs = z["label_vecs"], z["full_vecs"]
    except Exception as e:  # noqa: BLE001 - 파일이 깨졌으면 없는 것과 같다
        logger.warning("자산 임베딩 파일을 읽지 못해 임베딩을 쓰지 않습니다: %s", e)
        return None
    if (model, dims) != (llm.EMBED_MODEL, llm.EMBED_DIMS):
        logger.warning("자산 임베딩 모델이 다릅니다(파일 %s/%s, 설정 %s/%s) — 쓰지 않습니다.",
                       model, dims, llm.EMBED_MODEL, llm.EMBED_DIMS)
        return None
    if stored_digest != current_digest():
        logger.warning("자산 임베딩이 현재 라벨·검색어와 어긋납니다 — 쓰지 않습니다. "
                       "python scripts/build_aac_embeddings.py 로 다시 만드세요.")
        return None
    logger.info("자산 임베딩 %d개를 불러왔습니다.", len(ids))
    return _Store({i: n for n, i in enumerate(ids)}, label_vecs, full_vecs)


def available() -> bool:
    """이 프로세스에서 임베딩을 쓸 수 있는 상태인가(호출이 일시적으로 실패 중인 건 따로 본다)."""
    return mode() != "off" and llm.llm_available() and _load_store() is not None


class QuerySims:
    """질의 하나에 대한 자산별 유사도."""

    def __init__(self, store: _Store, sims: np.ndarray) -> None:
        self._row_of = store.row_of
        self._sims = sims

    def get(self, asset_id: str) -> float | None:
        row = self._row_of.get(asset_id)
        return None if row is None else float(self._sims[row])


def _query_vector(query: str) -> np.ndarray | None:
    global _cooldown_until
    with _lock:
        vec = _cache.get(query)
        if vec is not None:
            _cache.move_to_end(query)
            return vec
        if time.monotonic() < _cooldown_until:
            return None
    try:
        raw = llm.embed_texts([query], timeout=_QUERY_TIMEOUT)[0]
        vec = np.asarray(raw, dtype=np.float32)
        norm = float(np.linalg.norm(vec))
        if not norm:
            return None
        vec = vec / norm
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 임베딩 없이 계속한다
        with _lock:
            _cooldown_until = time.monotonic() + _COOLDOWN_SEC
        logger.warning("질의 임베딩 실패 — %.0f초 동안 임베딩 없이 진행합니다: %s", _COOLDOWN_SEC, e)
        return None
    with _lock:
        _cache[query] = vec
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return vec


def query_similarities(query: str) -> QuerySims | None:
    """질의와 각 자산의 유사도(라벨과 라벨+검색어 중 높은 쪽). 못 쓰면 None."""
    if not query.strip() or mode() == "off" or not llm.llm_available():
        return None
    store = _load_store()
    if store is None:
        return None
    vec = _query_vector(query)
    if vec is None:
        return None
    return QuerySims(store, np.maximum(store.label_vecs @ vec, store.full_vecs @ vec))


def _reset_for_tests() -> None:
    global _cooldown_until
    with _lock:
        _cache.clear()
        _cooldown_until = 0.0
    _load_store.cache_clear()
