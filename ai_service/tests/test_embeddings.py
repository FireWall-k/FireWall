"""임베딩 가산 항 — 로더·폴백·점수 항·이중 임계값 (실제 OpenAI 호출 없음)."""
import numpy as np
import pytest

import embeddings
import llm
import local_aac
from local_aac import _QueryFeatures, _score_asset, decide, load_assets, search_for_step_detailed


@pytest.fixture
def emb_on(monkeypatch):
    """임베딩을 켠 상태(키가 있고 mode=auto). 프로세스 전역 캐시는 매번 비운다."""
    monkeypatch.setenv("AAC_EMBEDDINGS", "auto")
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "test-key")
    embeddings._reset_for_tests()
    yield
    embeddings._reset_for_tests()


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


def test_mode_off_or_no_key_disables(monkeypatch):
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("AAC_EMBEDDINGS", "off")
    assert embeddings.available() is False
    assert embeddings.query_similarities("의자") is None

    monkeypatch.setenv("AAC_EMBEDDINGS", "auto")
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "")
    assert embeddings.available() is False
    assert embeddings.query_similarities("의자") is None


# ---------- 질의 임베딩: 유사도·실패 폴백 ----------

def test_similarity_is_cosine_against_best_of_label_and_full(emb_on, monkeypatch):
    store = embeddings._load_store()
    target = "CAFE_078"
    vec = store.full_vecs[store.row_of[target]]
    monkeypatch.setattr(llm, "embed_texts", lambda texts, timeout=0: [vec.tolist()])
    sims = embeddings.query_similarities("아무 질의")
    assert sims is not None
    assert sims.get(target) == pytest.approx(1.0, abs=1e-3)
    assert sims.get("없는-id") is None


def test_failure_returns_none_then_cools_down(emb_on, monkeypatch):
    calls = []

    def boom(texts, timeout=0):
        calls.append(texts)
        raise RuntimeError("api down")

    monkeypatch.setattr(llm, "embed_texts", boom)
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
    vec = store.label_vecs[0].tolist()
    calls = []

    def once(texts, timeout=0):
        calls.append(texts)
        return [vec]

    monkeypatch.setattr(llm, "embed_texts", once)
    embeddings.query_similarities("같은 질의")
    embeddings.query_similarities("같은 질의")
    assert len(calls) == 1


# ---------- 점수 항 ----------

def test_embedding_term_is_additive_only():
    asset = _asset("CAFE_078")
    qf = _QueryFeatures("의자를 정리하세요")
    base = _score_asset(asset, qf, None, None, False)
    assert _score_asset(asset, qf, None, None, False, emb_sim=None) == base
    for sim in (-0.3, 0.0, 0.2, 0.4):  # 기준(0.4) 이하는 잡음 — 절대 깎지 않는다
        assert _score_asset(asset, qf, None, None, False, emb_sim=sim) == base
    raised = _score_asset(asset, qf, None, None, False, emb_sim=0.8)
    assert raised == pytest.approx(min(1.0, base + 0.5 * (0.8 - 0.4)))
    assert raised > base


def test_score_never_exceeds_one():
    asset = _asset("CAFE_078")
    qf = _QueryFeatures("의자를 테이블에 맞춰 놓는다 의자")
    assert _score_asset(asset, qf, "cafe", "move", True, emb_sim=1.0) <= 1.0


# ---------- 이중 임계값 ----------

def test_decide_uses_embedding_thresholds_only_when_flagged():
    # 임베딩 없음: 0.22/0.02 — 0.30은 임계값을 넘고 여유 0.10도 충분 → 채택
    plain = [{"asset_id": "A", "score": 0.30}, {"asset_id": "B", "score": 0.20}]
    assert decide(plain)["reason"] == "accepted"
    # 같은 점수라도 임베딩을 썼다면 점수 척도가 올라가 있으므로 0.35 미만은 거절
    assert decide(plain, embedding=True)["reason"] == "low_score"
    assert decide(plain, embedding=True)["embedding"] is True

    # 여유 임계값 자체는 둘 다 0.02로 같다(독립 블라인드 393문장 스윕으로 확인 — 0.04는
    # 과했다: 정밀도는 거의 그대로인데 자동 채택만 놓쳤다). 점수 임계값(0.35 vs 0.22)만 다르다.
    close = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.485}]  # 여유 0.015
    assert decide(close)["reason"] == "low_margin"
    assert decide(close, embedding=True)["reason"] == "low_margin"
    wide = [{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.47}]  # 여유 0.03
    assert decide(wide)["reason"] == "accepted"
    assert decide(wide, embedding=True)["reason"] == "accepted"


def test_search_flags_embedding_usage(monkeypatch):
    ctx = {"business_type": "카페", "sentence": "의자들을 정리하세요.", "action_type": "sort"}

    monkeypatch.setattr(embeddings, "query_similarities", lambda q: None)
    assert search_for_step_detailed(["의자", "chair"], ctx)["embedding"] is False

    monkeypatch.setattr(embeddings, "query_similarities", lambda q: FakeSims({}))
    assert search_for_step_detailed(["의자", "chair"], ctx)["embedding"] is True


def test_embedding_promotes_the_semantically_correct_asset(monkeypatch):
    """실사용에서 발견: '의자들을 정리하세요'가 라벨에 '정리'가 박힌 '상품을 한 줄로 정리한다'에
    밀렸다. 뜻이 가까운 CAFE_078에 임베딩 유사도가 붙으면 1위가 되어야 한다."""
    ctx = {"business_type": "청소", "sentence": "의자들을 정리하세요.", "action_type": "sort"}
    query = "의자들을 정리하세요. 의자 chair"

    monkeypatch.setattr(embeddings, "query_similarities", lambda q: None)
    without = local_aac.search_assets(query, ctx, limit=5)

    monkeypatch.setattr(embeddings, "query_similarities",
                        lambda q: FakeSims({"CAFE_078": 0.85}))
    with_emb = local_aac.search_assets(query, ctx, limit=5)

    assert without[0]["asset_id"] != "CAFE_078"   # 임베딩이 없으면 라벨 글자 겹침에 밀린다
    assert with_emb[0]["asset_id"] == "CAFE_078"  # 뜻이 가까운 쪽이 1위로 올라온다
