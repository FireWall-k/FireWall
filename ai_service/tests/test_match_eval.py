"""매칭 평가 하네스와 정답셋의 무결성 테스트 (외부 네트워크/API 없음).

정답셋(match_dataset.json)은 손으로 쓰는 데이터라 자산 id 오타·중복 케이스로
조용히 썩기 쉽다. 여기서 막는다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from eval.run_match_eval import DATASET_PATH, _expand_accept, _group_index, run  # noqa: E402
from local_aac import load_assets  # noqa: E402


@pytest.fixture(scope="module")
def dataset():
    return json.loads(DATASET_PATH.read_text(encoding="utf-8"))


def test_every_accept_id_exists(dataset):
    """정답셋이 참조하는 asset_id가 모두 실제 데이터셋에 있어야 한다."""
    known = {a["id"] for a in load_assets()}
    unknown = {
        asset_id
        for case in dataset["cases"]
        for asset_id in case.get("accept", [])
        if asset_id not in known
    }
    assert not unknown, f"데이터셋에 없는 asset_id: {sorted(unknown)}"


def test_case_ids_unique(dataset):
    ids = [c["id"] for c in dataset["cases"]]
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"중복 케이스 id: {sorted(dupes)}"


def test_gap_and_normal_cases_are_well_formed(dataset):
    """갭 케이스는 정답이 없어야 하고, 일반 케이스는 정답이 있어야 한다."""
    for case in dataset["cases"]:
        if case.get("gap"):
            assert not case.get("accept"), f"{case['id']}: 갭 케이스에 accept가 있다"
            assert case.get("note"), f"{case['id']}: 갭 케이스에 note(사유)가 없다"
        else:
            assert case.get("accept"), f"{case['id']}: 일반 케이스에 accept가 비었다"


def test_sentence_does_not_copy_asset_label(dataset):
    """정답셋 문장이 자산 label을 그대로 베끼면 하네스가 쉬워져 회귀를 못 잡는다."""
    labels = {a["label"] for a in load_assets()}
    for case in dataset["cases"]:
        stem = case["sentence"].rstrip(".").strip()
        assert stem not in labels, f"{case['id']}: 문장이 자산 label과 동일하다"


def test_gap_cases_are_mostly_in_domain(dataset):
    """갭 케이스는 자산이 있는 직무 안의 문장이어야 한다.

    타 업종 문장(사무직 등)은 업종 가중치만으로 걸러져 거절이 쉽다. 그런 것만 모으면
    gap_declined_rate가 실제보다 높게 나온다 — 실제로 v1 정답셋이 그랬다.
    """
    jobs_with_assets = {a["job"] for a in load_assets()}
    gaps = [c for c in dataset["cases"] if c.get("gap")]
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


@pytest.mark.parametrize("query_mode", ["full", "sentence"])
def test_harness_runs_and_reports_sane_metrics(query_mode):
    report = run(query_mode=query_mode)

    assert report["query_mode"] == query_mode
    assert report["n_cases"] == report["n_normal"] + report["n_gap"]
    assert report["n_gap"] > 0, "갭 케이스가 없으면 wrong_accept를 제대로 못 잰다"

    for name, value in report["metrics"].items():
        assert 0.0 <= value <= 1.0, f"{name}이 비율 범위를 벗어났다: {value}"

    # recall은 단조적이어야 한다: top1 <= recall@3 <= recall@20
    m = report["metrics"]
    assert m["top1_accuracy"] <= m["recall@3"] <= m["recall@20"]


def test_full_mode_is_not_worse_than_sentence_mode():
    """symbol_query가 붙은 LLM 경로가 문장만 쓰는 폴백보다 나빠지면 회귀다."""
    full = run(query_mode="full")["metrics"]
    sentence = run(query_mode="sentence")["metrics"]
    assert full["top1_accuracy"] >= sentence["top1_accuracy"]
