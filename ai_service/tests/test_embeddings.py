"""임베딩 가산 항 — 제공자·로더·폴백·점수 항·이중 임계값.

실제 OpenAI 호출도, 실제 로컬 모델 로딩도 하지 않는다(가짜 모델/가짜 응답). 실제 로컬 모델은
모델 캐시(AAC_EMBED_CACHE_DIR)가 있을 때만 맨 아래 스모크 테스트에서 한 번 돌린다.
"""
import os

import numpy as np
import pytest

import embeddings
import llm
import local_aac
from local_aac import _QueryFeatures, _score_asset, decide, load_assets, search_for_step_detailed


@pytest.fixture
def emb_on(monkeypatch):
    """임베딩을 켠 상태(로컬 제공자, mode=auto, OpenAI 키 없음). 프로세스 전역 캐시는 매번 비운다."""
    monkeypatch.setenv("AAC_EMBEDDINGS", "auto")
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "local")
    monkeypatch.delenv("AAC_LOCAL_EMBED_MODEL", raising=False)
    monkeypatch.delenv("AAC_LOCAL_EMBED_DIMS", raising=False)
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "")
    embeddings._reset_for_tests()
    yield
    embeddings._reset_for_tests()


class FakeModel:
    """fastembed TextEmbedding 대역 — embed가 불릴 때마다 기록하고 정해 둔 벡터를 준다."""

    def __init__(self, vec=None, error=None) -> None:
        self.calls = []
        self.vec = vec
        self.error = error

    def embed(self, texts, batch_size=64):
        self.calls.append(list(texts))
        if self.error is not None:
            raise self.error
        return [np.asarray(self.vec, dtype=np.float32) for _ in texts]


def _use_model(monkeypatch, model):
    monkeypatch.setattr(embeddings, "load_local_model", lambda: model)
    return model


def _fail(*_a, **_k):
    raise AssertionError("부르면 안 되는 호출")


class FakeSims:
    """QuerySims 대역 — 지정한 자산만 유사도를 주고 나머지는 0."""

    def __init__(self, table: dict[str, float]) -> None:
        self._table = table

    def get(self, asset_id: str) -> float | None:
        return self._table.get(asset_id, 0.0)


def _asset(asset_id: str) -> dict:
    return next(a for a in load_assets() if a["id"] == asset_id)


# ---------- 자산 임베딩 파일 ----------

def test_shipped_embeddings_match_current_index():
    """라벨·검색어를 고치고 임베딩을 다시 안 만들면 여기서 잡힌다(운영에서는 조용히 꺼진다)."""
    path = local_aac.get_data_dir() / embeddings.STORE_FILENAME
    assert path.exists(), "python scripts/build_aac_embeddings.py 로 만드세요"
    stored = str(np.load(path, allow_pickle=False)["digest"])
    assert stored == embeddings.current_digest(), (
        "자산 임베딩이 낡았습니다 — python scripts/build_aac_embeddings.py 를 다시 돌리세요")


def test_shipped_store_is_built_with_the_default_local_model():
    """배포 파일은 기본 제공자(local)의 기본 모델로 만든다 — 다르면 운영에서 임베딩이 꺼진다."""
    z = np.load(local_aac.get_data_dir() / embeddings.STORE_FILENAME, allow_pickle=False)
    assert str(z["model"]) == embeddings.DEFAULT_LOCAL_MODEL
    assert int(z["dims"]) == embeddings._LOCAL_MODELS[embeddings.DEFAULT_LOCAL_MODEL][0]


def test_store_loads_every_asset(emb_on):
    store = embeddings._load_store()
    assert store is not None
    assert set(store.row_of) == {a["id"] for a in load_assets()}
    # 벡터는 정규화돼 있어야 내적이 코사인이다.
    assert np.allclose(np.linalg.norm(store.label_vecs, axis=1), 1.0, atol=1e-3)


def test_stale_store_is_not_used(emb_on, monkeypatch):
    monkeypatch.setattr(embeddings, "current_digest", lambda: "different")
    embeddings._load_store.cache_clear()
    assert embeddings._load_store() is None
    assert embeddings.available() is False
    assert embeddings.query_similarities("의자를 정리하세요") is None


def test_mode_off_disables(emb_on, monkeypatch):
    model = _use_model(monkeypatch, FakeModel(np.ones(384)))
    monkeypatch.setenv("AAC_EMBEDDINGS", "off")
    assert embeddings.available() is False
    assert embeddings.query_similarities("의자") is None
    assert model.calls == []


def test_local_provider_needs_no_api_key(emb_on, monkeypatch):
    """로컬 제공자는 OpenAI 키와 무관하게 켜진다(예전에는 키가 없으면 무조건 꺼졌다)."""
    store = embeddings._load_store()
    model = _use_model(monkeypatch, FakeModel(store.label_vecs[0]))
    monkeypatch.setattr(llm, "embed_texts", _fail)
    assert llm.llm_available() is False
    assert embeddings.available() is True
    assert embeddings.query_similarities("의자") is not None
    assert len(model.calls) == 1


def test_openai_provider_without_key_disables(emb_on, monkeypatch):
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "openai")
    monkeypatch.setattr(llm, "embed_texts", _fail)
    assert embeddings.available() is False
    assert embeddings.query_similarities("의자") is None


def test_unknown_provider_falls_back_to_local(monkeypatch):
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "nope")
    assert embeddings.provider() == "local"


def test_store_from_another_model_is_not_used(emb_on, monkeypatch):
    """배포 파일은 로컬 모델로 만들었다 — openai 제공자(다른 모델·차원)에서는 키가 있어도 쓰지 않는다."""
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "openai")
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(llm, "embed_texts", _fail)
    embeddings._load_store.cache_clear()
    assert embeddings.active_model() == (llm.EMBED_MODEL, llm.EMBED_DIMS)
    assert embeddings._load_store() is None
    assert embeddings.query_similarities("의자") is None

    # 로컬 모델 이름을 바꿔도 마찬가지다.
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "local")
    monkeypatch.setenv("AAC_LOCAL_EMBED_MODEL", "intfloat/multilingual-e5-small")
    embeddings._load_store.cache_clear()
    assert embeddings._load_store() is None


def test_openai_provider_dispatches_to_openai(monkeypatch):
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "openai")
    monkeypatch.setattr(embeddings, "load_local_model", _fail)
    seen = []

    def fake(texts, timeout=0):
        seen.append(texts)
        return [[1.0, 0.0]]

    monkeypatch.setattr(llm, "embed_texts", fake)
    assert embeddings.embed_texts(["의자"]) == [[1.0, 0.0]]
    assert seen == [["의자"]]


def test_local_provider_checks_dims_and_prefix(emb_on, monkeypatch):
    model = _use_model(monkeypatch, FakeModel(np.ones(10)))
    with pytest.raises(RuntimeError):  # 모델 차원이 설정(384)과 다르면 쓰지 않는다
        embeddings.embed_texts(["의자"])
    # e5 계열은 입력 앞에 "query: "를 붙인다(자산·질의 모두 같은 함수라 대칭이다).
    monkeypatch.setenv("AAC_LOCAL_EMBED_MODEL", "intfloat/multilingual-e5-small")
    model.vec = np.ones(384)
    embeddings.embed_texts(["의자"])
    assert model.calls[-1] == ["query: 의자"]


# ---------- 질의 임베딩: 유사도·실패 폴백 ----------

def test_similarity_is_cosine_against_best_of_label_and_full(emb_on, monkeypatch):
    store = embeddings._load_store()
    target = "CAFE_078"
    vec = store.full_vecs[store.row_of[target]]
    _use_model(monkeypatch, FakeModel(vec))
    sims = embeddings.query_similarities("아무 질의")
    assert sims is not None
    assert sims.get(target) == pytest.approx(1.0, abs=1e-3)
    assert sims.get("없는-id") is None


def test_failure_returns_none_then_cools_down(emb_on, monkeypatch):
    model = _use_model(monkeypatch, FakeModel(error=RuntimeError("model broken")))
    calls = model.calls
    assert embeddings.query_similarities("첫 질의") is None
    assert len(calls) == 1
    # 쿨다운 중에는 시도하지 않는다 — 요청마다 타임아웃을 기다리면 안 된다.
    assert embeddings.query_similarities("다른 질의") is None
    assert len(calls) == 1
    # 쿨다운이 끝나면 다시 시도한다.
    monkeypatch.setattr(embeddings, "_cooldown_until", 0.0)
    embeddings.query_similarities("또 다른 질의")
    assert len(calls) == 2


def test_query_vectors_are_cached(emb_on, monkeypatch):
    store = embeddings._load_store()
    model = _use_model(monkeypatch, FakeModel(store.label_vecs[0]))
    embeddings.query_similarities("같은 질의")
    embeddings.query_similarities("같은 질의")
    assert len(model.calls) == 1


def test_model_load_failure_falls_back(emb_on, monkeypatch):
    """모델 파일이 없거나(오프라인) 깨졌으면 예외 대신 None — 임베딩 없는 방식으로 물러난다."""
    def broken():
        raise OSError("model not found")

    monkeypatch.setattr(embeddings, "load_local_model", broken)
    assert embeddings.query_similarities("의자") is None
    assert embeddings.warm_up() is False


# ---------- 점수 항 ----------

@pytest.mark.parametrize("provider", ["local", "openai"])
def test_embedding_term_is_additive_only(monkeypatch, provider):
    monkeypatch.setenv("AAC_EMBED_PROVIDER", provider)
    monkeypatch.delenv(local_aac.embed_env_name("WEIGHT", provider), raising=False)
    monkeypatch.delenv(local_aac.embed_env_name("BASE", provider), raising=False)
    weight, emb_base, _, _ = local_aac._EMBED_DEFAULTS[provider]
    asset = _asset("CAFE_078")
    qf = _QueryFeatures("의자를 정리하세요")
    base = _score_asset(asset, qf, None, None, False)
    assert _score_asset(asset, qf, None, None, False, emb_sim=None) == base
    for sim in (-0.3, 0.0, 0.2, emb_base):  # 기준 이하는 잡음 — 절대 깎지 않는다
        assert _score_asset(asset, qf, None, None, False, emb_sim=sim) == base
    raised = _score_asset(asset, qf, None, None, False, emb_sim=0.9)
    assert raised == pytest.approx(min(1.0, base + weight * (0.9 - emb_base)))
    assert raised > base


def test_embedding_term_env_overrides_provider_defaults(monkeypatch):
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "local")
    monkeypatch.setenv("AAC_LOCAL_EMBED_WEIGHT", "0.2")
    monkeypatch.setenv("AAC_LOCAL_EMBED_BASE", "0.7")
    assert local_aac._embed_term_params() == (0.2, 0.7)
    monkeypatch.setenv("AAC_LOCAL_EMBED_WEIGHT", "")  # compose가 넘기는 빈 값은 기본값
    assert local_aac._embed_term_params()[0] == local_aac._EMBED_DEFAULTS["local"][0]


_OPENAI_ERA_ENV = {"AAC_EMBED_WEIGHT": "0.5", "AAC_EMBED_BASE": "0.4",
                   "AAC_EMBED_MATCH_THRESHOLD": "0.35", "AAC_EMBED_MATCH_MIN_MARGIN": "0.02"}


def test_old_openai_env_values_do_not_reach_local_provider(monkeypatch, caplog):
    """예전 .env.example(3068dd2~)이 적어 둔 OpenAI 보정값이 남아 있어도 로컬 제공자는 자기 기본값을 쓴다.
    (그 값을 MiniLM에 쓰면 개발 sentence 오답 채택 9→10, top1 116→114로 나빠졌다.) 기동 로그는 경고한다."""
    import logging
    for key in ("WEIGHT", "BASE", "MATCH_THRESHOLD", "MATCH_MIN_MARGIN"):
        monkeypatch.delenv("AAC_LOCAL_EMBED_" + key, raising=False)
    for key, value in _OPENAI_ERA_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "local")
    weight, base, threshold, margin = local_aac._EMBED_DEFAULTS["local"]
    assert local_aac.embed_settings() == {"provider": "local", "weight": weight, "base": base,
                                          "threshold": threshold, "min_margin": margin}
    with caplog.at_level(logging.INFO, logger="ai_harness.local_aac"):
        local_aac.log_embed_settings()
    assert any(r.levelno == logging.WARNING and "AAC_EMBED_WEIGHT" in r.getMessage()
               for r in caplog.records)
    # openai 제공자는 같은 이름을 그대로 쓴다.
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "openai")
    assert local_aac.embed_settings() == {"provider": "openai", "weight": 0.5, "base": 0.4,
                                          "threshold": 0.35, "min_margin": 0.02}


def test_score_never_exceeds_one():
    asset = _asset("CAFE_078")
    qf = _QueryFeatures("의자를 테이블에 맞춰 놓는다 의자")
    assert _score_asset(asset, qf, "cafe", "move", True, emb_sim=1.0) <= 1.0


# ---------- 이중 임계값 ----------

def test_decide_uses_embedding_thresholds_only_when_flagged(monkeypatch):
    for key in ("AAC_EMBED_MATCH_THRESHOLD", "AAC_EMBED_MATCH_MIN_MARGIN",
                "AAC_LOCAL_EMBED_MATCH_THRESHOLD", "AAC_LOCAL_EMBED_MATCH_MIN_MARGIN"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "local")
    # 임베딩 없음: 0.215/0.018(P5 재보정) — 0.23은 임계값을 넘고 여유도 충분 → 채택
    plain = [{"asset_id": "A", "score": 0.23}, {"asset_id": "B", "score": 0.10}]
    assert decide(plain)["reason"] == "accepted"
    # 같은 점수라도 임베딩을 썼다면 점수 척도가 올라가 있으므로 로컬 임계값 0.24 미만은 거절
    assert decide(plain, embedding=True)["reason"] == "low_score"
    assert decide(plain, embedding=True)["embedding"] is True
    # OpenAI 제공자는 가산 폭이 커서 임계값이 더 높다(0.35) — 0.30도 거절
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "openai")
    higher = [{"asset_id": "A", "score": 0.30}, {"asset_id": "B", "score": 0.20}]
    assert decide(higher)["reason"] == "accepted"
    assert decide(higher, embedding=True)["reason"] == "low_score"

    # 여유 임계값: 임베딩 없음 0.018, openai 0.02(독립 블라인드 393문장 스윕), local 0.015(개발셋 스윕).
    close = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.484}]  # 여유 0.016
    assert decide(close)["reason"] == "low_margin"
    assert decide(close, embedding=True)["reason"] == "low_margin"  # openai 0.02
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "local")
    assert decide(close, embedding=True)["reason"] == "accepted"    # local 0.015
    tight = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.49}]  # 여유 0.01
    assert decide(tight, embedding=True)["reason"] == "low_margin"
    wide = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.47}]  # 여유 0.03
    assert decide(wide)["reason"] == "accepted"
    assert decide(wide, embedding=True)["reason"] == "accepted"
    # 그 제공자의 환경변수가 기본값을 이긴다(local은 AAC_LOCAL_EMBED_*, OpenAI용 이름은 무시).
    monkeypatch.setenv("AAC_EMBED_MATCH_THRESHOLD", "0.6")
    assert decide(wide, embedding=True)["reason"] == "accepted"
    monkeypatch.setenv("AAC_LOCAL_EMBED_MATCH_THRESHOLD", "0.6")
    assert decide(wide, embedding=True)["reason"] == "low_score"
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "openai")
    monkeypatch.delenv("AAC_LOCAL_EMBED_MATCH_THRESHOLD")
    assert decide(wide, embedding=True)["reason"] == "low_score"


def test_search_flags_embedding_usage(monkeypatch):
    ctx = {"business_type": "카페", "sentence": "의자들을 정리하세요.", "action_type": "sort"}

    monkeypatch.setattr(embeddings, "query_similarities", lambda q: None)
    assert search_for_step_detailed(["의자", "chair"], ctx)["embedding"] is False

    monkeypatch.setattr(embeddings, "query_similarities", lambda q: FakeSims({}))
    assert search_for_step_detailed(["의자", "chair"], ctx)["embedding"] is True


def test_embedding_promotes_the_semantically_correct_asset(monkeypatch):
    """실사용에서 발견: '의자들을 정리하세요'가 라벨에 '정리'가 박힌 '상품을 한 줄로 정리한다'에
    밀렸다. 뜻이 가까운 CAFE_078에 임베딩 유사도가 붙으면 1위가 되어야 한다.
    (OpenAI 척도의 유사도 0.85 — 가산 폭이 큰 openai 기본값으로 잰다. 로컬은 아래 테스트.)"""
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "openai")
    for key in ("AAC_EMBED_WEIGHT", "AAC_EMBED_BASE"):
        monkeypatch.delenv(key, raising=False)
    ctx = {"business_type": "청소", "sentence": "의자들을 정리하세요.", "action_type": "sort"}
    query = "의자들을 정리하세요. 의자 chair"

    monkeypatch.setattr(embeddings, "query_similarities", lambda q: None)
    without = local_aac.search_assets(query, ctx, limit=5)

    monkeypatch.setattr(embeddings, "query_similarities",
                        lambda q: FakeSims({"CAFE_078": 0.85}))
    with_emb = local_aac.search_assets(query, ctx, limit=5)

    assert without[0]["asset_id"] != "CAFE_078"   # 임베딩이 없으면 라벨 글자 겹침에 밀린다
    assert with_emb[0]["asset_id"] == "CAFE_078"  # 뜻이 가까운 쪽이 1위로 올라온다


def test_local_embedding_breaks_close_rule_ties(monkeypatch):
    """로컬 기본값(가중치 0.3, 기준 0.65)은 가산 폭이 작다 — 규칙 점수가 근소하게 갈린 후보끼리만
    뒤집는다. 규칙 2위가 뜻이 같고(유사도 1.0) 1위가 기준 이하면 2위가 1위로 올라온다."""
    monkeypatch.setenv("AAC_EMBED_PROVIDER", "local")
    for key in ("AAC_LOCAL_EMBED_WEIGHT", "AAC_LOCAL_EMBED_BASE"):
        monkeypatch.delenv(key, raising=False)
    weight, emb_base, _, _ = local_aac._EMBED_DEFAULTS["local"]
    ctx = {"business_type": "청소", "sentence": "의자들을 정리하세요.", "action_type": "sort"}
    query = "의자들을 정리하세요. 의자 chair"

    monkeypatch.setattr(embeddings, "query_similarities", lambda q: None)
    first, second = local_aac.search_assets(query, ctx, limit=5)[:2]
    gap = first["score"] - second["score"]
    assert 0 < gap < weight * (1.0 - emb_base), "전제: 가산 폭 안쪽에서 갈린 두 후보"

    monkeypatch.setattr(embeddings, "query_similarities",
                        lambda q: FakeSims({first["asset_id"]: emb_base, second["asset_id"]: 1.0}))
    with_emb = local_aac.search_assets(query, ctx, limit=5)
    assert with_emb[0]["asset_id"] == second["asset_id"]
    assert with_emb[0]["score"] == pytest.approx(second["score"] + weight * (1.0 - emb_base))


# ---------- 실제 로컬 모델(모델 캐시가 있을 때만) ----------

@pytest.mark.skipif(not os.getenv("AAC_EMBED_CACHE_DIR"),
                    reason="AAC_EMBED_CACHE_DIR(내려받은 로컬 모델)가 없다 — CI는 모델을 받지 않는다")
def test_real_local_model_ranks_paraphrase_higher(emb_on):
    """실제 모델로: 같은 뜻의 다른 표현이 무관한 문장보다 가깝고, 배포 파일 벡터와 같은 척도다."""
    store = embeddings._load_store()
    assert store is not None
    vecs = [embeddings.normalize(v) for v in embeddings.embed_texts(
        ["바닥을 걸레로 닦으세요", "걸레로 바닥을 닦는다", "컵에 얼음을 담는다"])]
    assert float(vecs[0] @ vecs[1]) > float(vecs[0] @ vecs[2])
    # 자산 텍스트를 다시 임베딩하면 저장된 벡터와 같다(같은 모델·같은 입력 규칙).
    ids, labels, _ = embeddings._current_texts()
    again = embeddings.normalize(embeddings.embed_texts([labels[0]])[0])
    assert float(again @ store.label_vecs[store.row_of[ids[0]]]) == pytest.approx(1.0, abs=1e-3)
