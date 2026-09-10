"""Project-owned AAC mapping tests (no external network/API)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import symbols  # noqa: E402
from local_aac import search_assets  # noqa: E402


def test_local_aac_retail_exact_action():
    res = symbols.map_symbols(
        ["상품", "선반", "놓기"],
        {
            "business_type": "대형마트",
            "sentence": "상품을 선반에 놓으세요",
            "action_type": "move",
        },
    )

    s = res.symbols[0]

    assert s.source == "LOCAL_AAC"
    assert s.external_id == "RETAIL_029"
    assert s.needs_fallback is False
    assert s.image_url
    assert s.image_url.startswith("/api/aac/images/retail/")


def test_job_context_disambiguates_same_action():
    result = search_assets(
        "같은 상품끼리 모으세요",
        {
            "business_type": "마트",
            "action_type": "sort",
        },
        3,
    )

    assert result[0]["asset_id"] == "RETAIL_017"
    assert result[0]["job"] == "retail"


def test_results_have_no_duplicate_groups_or_labels():
    """같은 행동의 변형·중복 라벨이 결과에 두 번 나오면 안 된다."""
    results = search_assets(
        "부품 상자 뚜껑을 여세요",
        {"business_type": "조립", "sentence": "부품 상자 뚜껑을 여세요"},
        10,
    )

    groups = [r["group_id"] for r in results]
    labels = [(r["job"], r["label"]) for r in results]

    assert len(groups) == len(set(groups))
    assert len(labels) == len(set(labels))


def test_job_context_does_not_bury_cross_job_answer():
    """업종 맥락은 동점만 깨야 한다. 다른 직무의 더 적합한 자산을 묻으면 안 된다.

    '쓸어내기'는 cafe 자산(CAFE_080)뿐인데, 과거의 큰 불일치 벌점(-0.08)은 청소 맥락에서
    이 자산을 순위 밖으로 밀어냈다.
    """
    query = "바닥에 떨어진 것들을 빗자루로 쓸어주세요"
    results = search_assets(query, {"business_type": "청소", "sentence": query}, 5)

    assert "CAFE_080" in [r["asset_id"] for r in results]


def test_tool_mention_does_not_beat_the_action():
    """문장에 도구가 언급됐다고 도구 사진이 동작 사진을 이기면 안 된다.

    "테이블을 행주로 닦아주세요"는 '테이블 위를 닦는다'(동작)여야지 '행주'(도구)가 아니다.
    한 단어 라벨이 문장에 포함되기만 해도 포함 점수 만점을 받던 것이 원인이었다.
    """
    query = "테이블을 행주로 닦아주세요"
    results = search_assets(
        query,
        {"business_type": "카페", "sentence": query, "action_type": "clean"},
        3,
    )

    assert results[0]["asset_id"] == "CAFE_077"
    assert results[0]["asset_type"] == "action"


def test_short_label_containment_is_length_normalized():
    """포함 보정은 '언급됨'이 아니라 '거의 같은 말'일 때만 커야 한다."""
    from local_aac import _containment

    # 한 단어가 긴 문장에 포함된 경우 — 약한 증거
    weak = _containment("테이블을 행주로 닦아주세요", "행주", set(), set())
    # 거의 같은 문장 — 강한 증거
    strong = _containment("테이블 위를 닦는다", "테이블 위를 닦는다", set(), set())

    assert weak < 0.3
    assert strong == 1.0


def test_margin_gate_declines_a_near_tie(monkeypatch):
    """1·2순위 점수가 붙어 있으면 채택하지 않는다(동전 던지기 방지).

    "원두를 갈아주세요"는 '원두를 준비한다'와 '원두를 분쇄한다'가 완전 동점이라
    자산 id 정렬순으로 갈렸다. 이런 건 사람이 골라야 한다.
    """
    from local_aac import search_for_step_detailed

    monkeypatch.setenv("AAC_MATCH_THRESHOLD", "0.10")
    monkeypatch.setenv("AAC_MATCH_MIN_MARGIN", "0.02")

    query = "원두를 갈아주세요"
    decision = search_for_step_detailed(
        ["원두", "coffee bean"],
        {"business_type": "카페", "sentence": query},
    )

    assert decision["match"] is None
    assert decision["reason"] == "low_margin"
    # 거절했어도 후보는 넘겨야 한다 — 검토 화면에서 사람이 고를 수 있도록.
    assert len(decision["candidates"]) >= 2


def test_margin_gate_accepts_a_clear_winner(monkeypatch):
    from local_aac import search_for_step_detailed

    monkeypatch.setenv("AAC_MATCH_THRESHOLD", "0.14")
    monkeypatch.setenv("AAC_MATCH_MIN_MARGIN", "0.02")

    query = "앞치마를 착용하세요"
    decision = search_for_step_detailed(
        ["앞치마", "apron"],
        {"business_type": "카페", "sentence": query, "action_type": "other"},
    )

    assert decision["reason"] == "accepted"
    assert decision["match"]["asset_id"] == "CAFE_002"
    assert decision["margin"] >= 0.02


def test_decide_reasons_are_distinguished():
    """후보 없음 / 점수 미달 / 후보 경합을 구분해야 검토 화면에서 다르게 다룰 수 있다."""
    from local_aac import decide

    assert decide([])["reason"] == "no_candidate"
    assert decide([{"asset_id": "A", "score": 0.01}])["reason"] == "low_score"
    tie = decide([{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.499}])
    assert tie["reason"] == "low_margin"
    clear = decide([{"asset_id": "A", "score": 0.50}, {"asset_id": "B", "score": 0.20}])
    assert clear["reason"] == "accepted"
    assert clear["match"]["asset_id"] == "A"


def test_single_candidate_has_no_competitor_to_lose_to():
    """후보가 하나뿐이면 비교 대상이 없으므로 여유 부족으로 거절해선 안 된다."""
    from local_aac import decide

    assert decide([{"asset_id": "A", "score": 0.50}])["reason"] == "accepted"


def test_map_symbols_returns_candidates_when_it_cannot_choose(monkeypatch):
    """자동 채택을 못 하면 후보를 함께 넘겨 검토 화면에서 고를 수 있게 한다."""
    monkeypatch.setenv("AAC_MATCH_THRESHOLD", "0.10")
    monkeypatch.setenv("AAC_MATCH_MIN_MARGIN", "0.02")

    res = symbols.map_symbols(
        ["원두", "coffee bean"],
        {"business_type": "카페", "sentence": "원두를 갈아주세요"},
    )
    s = res.symbols[0]

    assert s.needs_fallback is True
    assert s.reason == "low_margin"
    assert s.image_url is None
    assert 2 <= len(s.candidates) <= 3
    assert all(c.image_url.startswith("/api/aac/images/") for c in s.candidates)


def test_map_symbols_omits_candidates_when_accepted():
    """채택했으면 후보를 보낼 이유가 없다(검토 화면에 선택 UI를 띄우지 않는다)."""
    res = symbols.map_symbols(
        ["앞치마", "apron"],
        {"business_type": "카페", "sentence": "앞치마를 착용하세요"},
    )
    s = res.symbols[0]

    assert s.reason == "accepted"
    assert s.needs_fallback is False
    assert s.external_id == "CAFE_002"
    assert s.candidates == []


def test_fallback_when_no_relevant_match(monkeypatch):
    monkeypatch.setenv("AAC_MATCH_THRESHOLD", "0.95")

    res = symbols.map_symbols(
        ["완전히없는검색어zzqx"],
        {
            "sentence": "완전히없는검색어zzqx"
        },
    )

    s = res.symbols[0]

    assert s.needs_fallback is True
    assert s.source == "fallback"