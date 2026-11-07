"""매칭 평가 하네스와 정답셋의 무결성 테스트 (외부 네트워크/API 없음).

정답셋(match_dataset.json·dev_set.json)은 손으로 쓰는 데이터라 자산 id 오타·중복 케이스로
조용히 썩기 쉽다. 여기서 막는다. 또 기준선(eval/baselines/) 대비 오답 채택·정답 자동 채택
건수가 허용치를 넘어 나빠지면 실패시켜, 스코어러 수정이 회귀를 몰래 들여오지 못하게 한다.
"""
import json
import os
import sys
from functools import lru_cache

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pytest  # noqa: E402

import embeddings  # noqa: E402
import local_aac  # noqa: E402
from eval import run_match_eval as rme  # noqa: E402
from eval.run_match_eval import (  # noqa: E402
    DATASET_PATH, DATASETS, EmbeddingCacheMiss, MixedEmbeddingError, _expand_accept,
    _group_index, baseline_path, case_query, check_embedding_consistency,
    compare_to_baseline, data_fingerprint, query_cache_path, run,
)
from local_aac import load_assets  # noqa: E402


@lru_cache(maxsize=None)
def _report(name: str, query_mode: str) -> dict:
    """전체 채점은 데이터셋·모드마다 수십 초 걸린다. 여러 테스트가 같은 결과를 보므로 한 번만 돌린다."""
    return run(query_mode=query_mode, dataset=DATASETS[name], embedding="off")


def _load(name: str) -> dict:
    return json.loads(DATASETS[name].read_text(encoding="utf-8"))


# --- 정답셋 무결성 -------------------------------------------------------------

@pytest.mark.parametrize("name", sorted(DATASETS))
def test_every_accept_id_exists(name):
    """정답셋이 참조하는 asset_id가 모두 실제 데이터셋에 있어야 한다."""
    known = {a["id"] for a in load_assets()}
    unknown = {
        asset_id
        for case in _load(name)["cases"]
        for asset_id in case.get("accept", [])
        if asset_id not in known
    }
    assert not unknown, f"데이터셋에 없는 asset_id: {sorted(unknown)}"


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_case_ids_unique(name):
    ids = [c["id"] for c in _load(name)["cases"]]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"중복 케이스 id: {sorted(dupes)}"


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_gap_and_normal_cases_are_well_formed(name):
    """갭 케이스는 정답이 없어야 하고, 일반 케이스는 정답이 있어야 한다.

    note(갭 사유)는 골든셋에만 요구한다 — 개발셋은 판정자 2명이 이미지를 보고 합의한 라벨이라
    사유 대신 confidence를 남겼다.
    """
    for case in _load(name)["cases"]:
        if case.get("gap"):
            assert not case.get("accept"), f"{case['id']}: 갭 케이스에 accept가 있다"
            if name == "golden":
                assert case.get("note"), f"{case['id']}: 갭 케이스에 note(사유)가 없다"
        else:
            assert case.get("accept"), f"{case['id']}: 일반 케이스에 accept가 비었다"


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_sentence_does_not_copy_asset_label(name):
    """정답셋 문장이 자산 label을 그대로 베끼면 하네스가 쉬워져 회귀를 못 잡는다."""
    labels = {a["label"] for a in load_assets()}
    for case in _load(name)["cases"]:
        stem = case["sentence"].rstrip(".").strip()
        assert stem not in labels, f"{case['id']}: 문장이 자산 label과 동일하다"


@pytest.mark.parametrize("name", sorted(DATASETS))
def test_gap_cases_are_mostly_in_domain(name):
    """갭 케이스는 자산이 있는 직무 안의 문장이어야 한다.

    타 업종 문장(사무직 등)은 업종 가중치만으로 걸러져 거절이 쉽다. 그런 것만 모으면
    gap_declined_rate가 실제보다 높게 나온다 — 실제로 v1 정답셋이 그랬다.
    """
    jobs_with_assets = {a["job"] for a in load_assets()}
    gaps = [c for c in _load(name)["cases"] if c.get("gap")]
    in_domain = [c for c in gaps if c.get("job") in jobs_with_assets]

    assert gaps, "갭 케이스가 없으면 wrong_accept를 제대로 못 잰다"
    assert len(in_domain) / len(gaps) >= 0.7, (
        f"같은 업종 갭이 {len(in_domain)}/{len(gaps)}뿐이다. "
        "타 업종 문장 위주면 거절이 쉬워 지표가 실제보다 좋게 나온다."
    )


def test_accept_expands_to_variant_group():
    """대표 변형 1개만 적어도 같은 group_id의 모든 변형이 정답으로 확장된다."""
    id_to_group, group_to_ids = _group_index()
    expanded = _expand_accept(["ASSEMBLY_031_01"], id_to_group, group_to_ids)
    assert expanded == {
        "ASSEMBLY_031_01", "ASSEMBLY_031_02",
        "ASSEMBLY_031_03", "ASSEMBLY_031_04",
    }


def test_unknown_accept_id_is_rejected():
    id_to_group, group_to_ids = _group_index()
    with pytest.raises(SystemExit):
        _expand_accept(["NO_SUCH_ASSET"], id_to_group, group_to_ids)


# --- 하네스 지표 ---------------------------------------------------------------

@pytest.mark.parametrize("query_mode", ["full", "sentence"])
def test_harness_runs_and_reports_sane_metrics(query_mode):
    report = _report("golden", query_mode)

    assert report["query_mode"] == query_mode
    assert report["n_cases"] == report["n_normal"] + report["n_gap"]
    assert report["n_gap"] > 0, "갭 케이스가 없으면 wrong_accept를 제대로 못 잰다"

    for name, value in report["metrics"].items():
        assert 0.0 <= value <= 1.0, f"{name}이 비율 범위를 벗어났다: {value}"

    # recall은 단조적이어야 한다: top1 <= recall@3 <= recall@20
    m = report["metrics"]
    assert m["top1_accuracy"] <= m["recall@3"] <= m["recall@20"]


@pytest.mark.parametrize("query_mode", ["full", "sentence"])
def test_precision_and_correct_auto_are_consistent(query_mode):
    """채택 정밀도·정답 자동 채택은 봉인 시험지와 비교하는 지표다. 건수와 비율이 서로 맞아야 한다."""
    report = _report("golden", query_mode)
    c, m = report["counts"], report["metrics"]
    rows = report["cases"]

    assert c["accepted"] == sum(r["accepted"] for r in rows)
    assert c["wrong_accept"] == sum(r["wrong_accept"] for r in rows)
    assert c["correct_auto"] == c["accepted"] - c["wrong_accept"]
    assert c["wrong_accept"] == c["wrong_accept_normal"] + c["wrong_accept_gap"]
    assert m["accept_precision"] == round(c["correct_auto"] / c["accepted"], 3)
    assert m["correct_auto_rate"] == round(c["correct_auto"] / report["n_cases"], 3)
    # 갭 케이스는 정답이 없으니 정답 자동 채택은 전부 일반 케이스에서 나온다.
    assert m["normal_correct_auto_rate"] == round(c["correct_auto"] / report["n_normal"], 3)


def test_full_mode_is_not_worse_than_sentence_mode():
    """symbol_query가 붙은 LLM 경로가 문장만 쓰는 폴백보다 나빠지면 회귀다.

    골든셋에만 건다 — 개발셋은 symbol_query에 영어 키워드가 섞여 full이 오히려 낮다(P7 과제).
    """
    full = _report("golden", "full")["metrics"]
    sentence = _report("golden", "sentence")["metrics"]
    assert full["top1_accuracy"] >= sentence["top1_accuracy"]


def test_dataset_argument_selects_dev_set():
    report = _report("dev", "sentence")
    assert report["n_cases"] == len(_load("dev")["cases"])
    assert report["dataset"] == "dev"


def test_one_search_per_case(monkeypatch):
    """케이스당 검색은 한 번이어야 한다 — 순위와 채택 판정이 서로 다른 검색에서 나오면 어긋날 수 있고 느리다."""
    calls = []
    original = local_aac._search

    def counting(query, context=None, limit=5):
        calls.append(query)
        return original(query, context, limit)

    monkeypatch.setattr(local_aac, "_search", counting)
    case_id = _load("golden")["cases"][0]["id"]
    run(only_case=case_id, dataset=DATASET_PATH, embedding="off")
    assert len(calls) == 1


# --- 임베딩 모드 ---------------------------------------------------------------

def _row(embedding: bool) -> dict:
    return {"id": "x", "embedding": embedding}


def test_mixed_embedding_rows_fail():
    """일부 케이스만 임베딩을 쓰면 임계값 두 벌이 섞여 수치가 무의미하다."""
    with pytest.raises(MixedEmbeddingError):
        check_embedding_consistency([_row(True), _row(False)], "cached")
    with pytest.raises(MixedEmbeddingError):
        check_embedding_consistency([_row(False), _row(True)], "off")
    check_embedding_consistency([_row(False), _row(False)], "off")
    check_embedding_consistency([_row(True), _row(True)], "cached")


def test_off_mode_never_uses_embedding():
    report = _report("golden", "full")
    assert report["embedding_mode"] == "off"
    assert not any(r["embedding"] for r in report["cases"])


def _store_or_skip():
    store = embeddings._load_store()
    if store is None:
        pytest.skip("자산 임베딩 파일이 없거나 낡았다")
    return store


def test_cached_mode_misses_raise_instead_of_calling_api(tmp_path, monkeypatch):
    _store_or_skip()

    def forbidden(*a, **k):
        raise AssertionError("cached 모드에서 API를 부르면 안 된다")

    monkeypatch.setattr(embeddings.llm, "embed_texts", forbidden)
    case_id = _load("golden")["cases"][0]["id"]
    with pytest.raises(EmbeddingCacheMiss):
        run(only_case=case_id, dataset=DATASET_PATH, embedding="cached", cache_dir=tmp_path)


def test_cached_mode_uses_disk_vectors(tmp_path):
    store = _store_or_skip()
    case = _load("golden")["cases"][0]
    query = case_query(case, "full")
    vec = np.asarray(store.full_vecs[0], dtype=np.float32)
    path = query_cache_path(tmp_path, query)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, vec)

    report = run(only_case=case["id"], dataset=DATASET_PATH, embedding="cached",
                 cache_dir=tmp_path)
    assert report["embedding_mode"] == "cached"
    assert all(r["embedding"] for r in report["cases"])


def test_cache_key_depends_on_model_dims_and_query(tmp_path, monkeypatch):
    a = query_cache_path(tmp_path, "앞치마를 입으세요.")
    assert a != query_cache_path(tmp_path, "앞치마를 벗으세요.")
    monkeypatch.setattr(embeddings.llm, "EMBED_DIMS", 1024)
    assert a != query_cache_path(tmp_path, "앞치마를 입으세요.")


def test_fill_cache_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr(embeddings.llm, "llm_available", lambda: False)
    with pytest.raises(SystemExit):
        rme.fill_embed_cache([DATASET_PATH], ["full"], tmp_path)


# --- 기준선(CI 안전장치) ---------------------------------------------------------

# 동점 순서 등 사소한 흔들림까지 막으면 쓸 만한 변경도 막힌다. 1건까지는 허용한다.
WRONG_ACCEPT_SLACK = 1
CORRECT_AUTO_SLACK = 1


def test_compare_to_baseline_flags_regressions():
    base = {"counts": {"wrong_accept": 10, "correct_auto": 50}}
    ok = {"counts": {"wrong_accept": 11, "correct_auto": 49}}
    bad_wa = {"counts": {"wrong_accept": 12, "correct_auto": 50}}
    bad_ca = {"counts": {"wrong_accept": 10, "correct_auto": 48}}
    assert compare_to_baseline(ok, base, WRONG_ACCEPT_SLACK, CORRECT_AUTO_SLACK) == []
    assert compare_to_baseline(bad_wa, base, WRONG_ACCEPT_SLACK, CORRECT_AUTO_SLACK)
    assert compare_to_baseline(bad_ca, base, WRONG_ACCEPT_SLACK, CORRECT_AUTO_SLACK)


@pytest.mark.parametrize("name,query_mode", [
    ("golden", "full"), ("golden", "sentence"), ("dev", "full"), ("dev", "sentence"),
])
def test_no_regression_against_baseline(name, query_mode):
    path = baseline_path(name, query_mode)
    assert path.exists(), f"기준선이 없다: {path} — python -m eval.run_match_eval --write-baseline"
    baseline = json.loads(path.read_text(encoding="utf-8"))
    assert baseline["embedding"] == "off"

    # 정답셋·자산 데이터가 바뀌면 건수를 비교할 수 없다. 같은 커밋에서 기준선도 갱신해야 한다.
    assert baseline["fingerprint"] == data_fingerprint(DATASETS[name]), (
        "정답셋 또는 자산 데이터가 기준선을 만든 뒤 바뀌었다 — "
        "python -m eval.run_match_eval --write-baseline 로 갱신하고 전후 수치를 커밋에 남길 것"
    )

    report = _report(name, query_mode)
    problems = compare_to_baseline(report, baseline, WRONG_ACCEPT_SLACK, CORRECT_AUTO_SLACK)
    assert not problems, "; ".join(problems)
