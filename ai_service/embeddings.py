"""질의·자산 임베딩 유사도 — 규칙 점수에 '더하기만' 하는 보조 신호.

왜 있나: 규칙 점수(자카드·동사 원형 등)는 표현이 달라지면 정답을 못 올린다("정리하세요"↔"놓는다").
임베딩은 뜻이 가까운 후보를 올려 주고, 그러면 채택 게이트(임계값·여유)가 정답과 오답을 더 잘 가른다.
블라인드 실측(독립 249단계): 오답 채택 19건 → 9건(개선 10 / 악화 0, McNemar p=0.002), 커버리지 유지.

지켜야 할 것:
- 어떤 이유로든(키 없음, 파일 없음/낡음, 호출 실패·지연) 임베딩을 못 쓰면 None을 돌려주고,
  호출자는 임베딩 없는 기존 방식(기존 임계값)으로 물러난다. 임베딩 장애가 서비스 장애가 되면 안 된다.
- 점수 척도가 임베딩 유무로 달라지므로 임계값도 두 벌이다(local_aac.decide).
- 자산 벡터가 현재 라벨·검색어와 어긋나면(인덱스를 고치고 다시 안 만든 경우) 쓰지 않는다.

제공자(AAC_EMBED_PROVIDER):
- local(기본) — 무료 로컬 모델(fastembed/ONNX, CPU). 키·네트워크가 필요 없다. 모델은 처음 쓸 때
  한 번 불러온다. 도커 이미지는 빌드할 때 모델을 AAC_EMBED_CACHE_DIR에 받아 두고 실행 중에는
  내려받지 않는다(HF_HUB_OFFLINE=1).
- openai — text-embedding-3-large(OPENAI_EMBED_MODEL/DIMS). 키가 있을 때만 켜진다.
자산 벡터 파일에는 만든 모델·차원이 적혀 있고, 지금 제공자의 모델·차원과 다르면 쓰지 않는다.
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
# 타임아웃은 openai 제공자(네트워크 호출)에만 적용된다. local은 요청 안에서 바로 추론하고(질의 하나
# 7~14ms) 타임아웃이 없다 — 모델 로딩·추론이 예외를 내면 쿨다운만 걸린다.
_QUERY_TIMEOUT = float(os.getenv("AAC_EMBED_TIMEOUT", "3"))
_COOLDOWN_SEC = float(os.getenv("AAC_EMBED_COOLDOWN", "60"))
_CACHE_SIZE = 512

_lock = threading.Lock()
_cache: "OrderedDict[tuple, np.ndarray]" = OrderedDict()
_cooldown_until = 0.0


def mode() -> str:
    """AAC_EMBEDDINGS: 'off'면 끈다. 그 외에는 제공자를 쓸 수 있고 자산 파일이 맞으면 켠다."""
    return os.getenv("AAC_EMBEDDINGS", "auto").strip().lower()


# --- 제공자 -----------------------------------------------------------------------

PROVIDERS = ("local", "openai")
DEFAULT_LOCAL_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

# 로컬 모델 표: 이름 → (차원, 입력 앞에 붙일 말). fastembed 기본 목록에 없는 모델은
# _register_custom에서 등록한다. 표에 없는 모델도 AAC_LOCAL_EMBED_DIMS를 주면 쓸 수 있다.
_LOCAL_MODELS: dict[str, tuple[int, str]] = {
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2": (384, ""),
    "intfloat/multilingual-e5-small": (384, "query: "),
}
_CUSTOM_MODELS = {
    # fastembed 0.9 목록에 없다. HF 저장소의 onnx/model.onnx를 그대로 쓴다(평균 풀링 + 정규화).
    "intfloat/multilingual-e5-small": dict(dim=384, model_file="onnx/model.onnx"),
}


def provider() -> str:
    """AAC_EMBED_PROVIDER: local(기본) | openai. 알 수 없는 값은 local로 본다."""
    value = os.getenv("AAC_EMBED_PROVIDER", "local").strip().lower()
    return value if value in PROVIDERS else "local"


def local_model_name() -> str:
    return os.getenv("AAC_LOCAL_EMBED_MODEL", "").strip() or DEFAULT_LOCAL_MODEL


def local_model_dims() -> int:
    env = os.getenv("AAC_LOCAL_EMBED_DIMS", "").strip()
    if env:
        return int(env)
    return _LOCAL_MODELS.get(local_model_name(), (384, ""))[0]


def _local_prefix() -> str:
    return _LOCAL_MODELS.get(local_model_name(), (0, ""))[1]


def active_model() -> tuple[str, int]:
    """지금 제공자의 (모델 이름, 차원). 자산 파일 검사·digest·평가 캐시 키가 모두 이것을 쓴다."""
    if provider() == "openai":
        return llm.EMBED_MODEL, llm.EMBED_DIMS
    return local_model_name(), local_model_dims()


def provider_ready() -> bool:
    """제공자를 부를 수 있는가. openai는 키가 있어야 하고, local은 키와 무관하다."""
    if provider() == "openai":
        return llm.llm_available()
    return True


_local_lock = threading.Lock()
_local_models: dict[str, object] = {}


def _register_custom(name: str) -> None:
    spec = _CUSTOM_MODELS.get(name)
    if spec is None:
        return
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    if any(m["model"] == name for m in TextEmbedding.list_supported_models()):
        return
    TextEmbedding.add_custom_model(model=name, pooling=PoolingType.MEAN, normalization=True,
                                   sources=ModelSource(hf=name), **spec)


def load_local_model():
    """로컬 모델을 프로세스당 한 번 불러온다. 실패하면 예외(호출부가 임베딩 없이 진행한다)."""
    name = local_model_name()
    with _local_lock:
        model = _local_models.get(name)
        if model is None:
            from fastembed import TextEmbedding  # 무거운 import — 임베딩을 쓸 때만

            _register_custom(name)
            started = time.monotonic()
            threads = int(os.getenv("AAC_LOCAL_EMBED_THREADS", "2"))
            cache_dir = os.getenv("AAC_EMBED_CACHE_DIR", "").strip() or None
            model = TextEmbedding(model_name=name, cache_dir=cache_dir, threads=threads)
            _local_models[name] = model
            logger.info("로컬 임베딩 모델 %s 를 %.1f초에 불러왔습니다.", name,
                        time.monotonic() - started)
    return model


def embed_texts(texts: list[str], *, timeout: float = 20.0) -> list:
    """지금 제공자로 텍스트를 임베딩한다(정규화 전). 실패 시 예외. 자산·질의가 같은 함수를 쓴다."""
    if provider() == "openai":
        return llm.embed_texts(texts, timeout=timeout)
    model = load_local_model()
    prefix = _local_prefix()
    vecs = list(model.embed([prefix + t for t in texts], batch_size=64))
    dims = local_model_dims()
    if vecs and len(vecs[0]) != dims:
        raise RuntimeError(f"로컬 모델 차원이 설정과 다릅니다: {len(vecs[0])} != {dims}")
    return vecs


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
    model, dims = active_model()
    return texts_digest(ids, labels, fulls, model, dims)


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
    if (model, dims) != active_model():
        logger.warning("자산 임베딩 모델이 다릅니다(파일 %s/%s, 설정 %s/%s) — 쓰지 않습니다.",
                       model, dims, *active_model())
        return None
    if stored_digest != current_digest():
        logger.warning("자산 임베딩이 현재 라벨·검색어와 어긋납니다 — 쓰지 않습니다. "
                       "python scripts/build_aac_embeddings.py 로 다시 만드세요.")
        return None
    logger.info("자산 임베딩 %d개를 불러왔습니다.", len(ids))
    return _Store({i: n for n, i in enumerate(ids)}, label_vecs, full_vecs)


def available() -> bool:
    """이 프로세스에서 임베딩을 쓸 수 있는 상태인가(호출이 일시적으로 실패 중인 건 따로 본다)."""
    return mode() != "off" and provider_ready() and _load_store() is not None


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
    key = (provider(), *active_model(), query)
    with _lock:
        vec = _cache.get(key)
        if vec is not None:
            _cache.move_to_end(key)
            return vec
        if time.monotonic() < _cooldown_until:
            return None
    try:
        vec = normalize(embed_texts([query], timeout=_QUERY_TIMEOUT)[0])
        if vec is None:
            return None
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 임베딩 없이 계속한다
        with _lock:
            _cooldown_until = time.monotonic() + _COOLDOWN_SEC
        logger.warning("질의 임베딩 실패 — %.0f초 동안 임베딩 없이 진행합니다: %s", _COOLDOWN_SEC, e)
        return None
    with _lock:
        _cache[key] = vec
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return vec


def query_similarities(query: str) -> QuerySims | None:
    """질의와 각 자산의 유사도(라벨과 라벨+검색어 중 높은 쪽). 못 쓰면 None."""
    if not query.strip() or mode() == "off" or not provider_ready():
        return None
    store = _load_store()
    if store is None:
        return None
    vec = _query_vector(query)
    if vec is None:
        return None
    return sims_for_vector(store, vec)


def sims_for_vector(store: _Store, vec: np.ndarray) -> QuerySims:
    """정규화된 질의 벡터 → 자산별 유사도. 평가 하네스의 디스크 캐시 경로도 같은 식을 쓰게 따로 뺐다."""
    return QuerySims(store, np.maximum(store.label_vecs @ vec, store.full_vecs @ vec))


def normalize(raw) -> np.ndarray | None:
    """제공자가 준 벡터를 float32 단위 벡터로. 영벡터면 None."""
    vec = np.asarray(raw, dtype=np.float32)
    norm = float(np.linalg.norm(vec))
    return vec / norm if norm else None


def warm_up() -> bool:
    """서비스 시작 때 자산 파일과 로컬 모델을 미리 불러 둔다(첫 요청이 모델 로딩 ~3초를 기다리지
    않게). 실패해도 예외를 내지 않는다 — 요청 시점에 같은 폴백이 다시 적용된다."""
    try:
        if not available() or provider() != "local":
            return False
        load_local_model()
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("로컬 임베딩 모델을 미리 불러오지 못했습니다(요청 때 다시 시도): %s", e)
        return False


def _reset_for_tests() -> None:
    global _cooldown_until
    with _lock:
        _cache.clear()
        _cooldown_until = 0.0
    _load_store.cache_clear()
