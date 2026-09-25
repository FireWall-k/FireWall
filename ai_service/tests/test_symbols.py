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

    # SERVING_010(같은 동작, 서빙 직무)이 새로 생겼으므로 둘 다 정답이다.
    assert results[0]["asset_id"] in {"CAFE_077", "SERVING_010"}
    assert results[0]["asset_type"] == "action"


def test_object_card_loses_to_action_for_an_instruction():
    """지시문에는 동작 그림이 맞다. 도구 그림이 붙으면 무엇을 할지 알 수 없다.

    "얼음통을 씻어주세요"에 도구 카드 '얼음통'이 붙으면 근로자는 통을 보기만 한다.
    문장에 물건 이름이 있다고 그 물건 그림을 끌어오면 안 된다.
    """
    query = "얼음통을 씻어주세요."
    results = search_assets(
        query,
        {"business_type": "카페", "sentence": query, "action_type": "clean"},
        5,
    )
    assert results[0]["asset_id"] != "CAFE_TOOL_014"  # 도구 카드 '얼음통'


def test_object_card_wins_when_the_query_is_the_object_itself():
    """반대로 사물 자체를 찾을 때는 사물 카드가 맞다(검색창에 명사를 친 경우)."""
    results = search_assets("얼음통", {"business_type": "카페"}, 3)
    assert results[0]["asset_id"] == "CAFE_TOOL_014"


def test_verb_class_conflict_is_penalized():
    """동작 계열이 어긋나면 깎는다 — 명사만 겹쳐 올라오는 것을 막는다."""
    from local_aac import _verb_class_penalty, load_assets

    by = {a["id"]: a for a in load_assets()}
    # RETAIL_048 '냉동 상품을 냉동 진열대에 놓는다'는 move 계열이다.
    assert _verb_class_penalty(by["RETAIL_048"], "clean") < 1.0
    # 같은 계열이거나 판단 근거가 없으면 깎지 않는다.
    assert _verb_class_penalty(by["RETAIL_048"], "move") == 1.0
    assert _verb_class_penalty(by["RETAIL_048"], "other") == 1.0
    # move/pack/sort는 사람마다 다르게 분류해 정답 쌍에서도 섞였다 — 호환으로 둔다.
    assert _verb_class_penalty(by["RETAIL_048"], "pack") == 1.0


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

    "박스 아래쪽을 테이프로 막으세요"는 '박스 바닥에 테이프를 붙인다'와
    '박스 가운데에 테이프를 붙인다'가 거의 동점이다. 붙이는 위치가 다르므로
    아무거나 고르면 안 된다 — 사람이 골라야 한다.
    """
    from local_aac import search_for_step_detailed

    monkeypatch.setenv("AAC_MATCH_THRESHOLD", "0.10")
    monkeypatch.setenv("AAC_MATCH_MIN_MARGIN", "0.02")

    query = "박스 아래쪽을 테이프로 막으세요."
    decision = search_for_step_detailed(
        ["테이프", "tape"],
        {"business_type": "포장", "sentence": query, "action_type": "pack"},
    )

    assert decision["match"] is None
    assert decision["reason"] == "low_margin"
    # 거절했어도 후보는 넘겨야 한다 — 검토 화면에서 사람이 고를 수 있도록.
    assert len(decision["candidates"]) >= 2


def test_conjugated_verb_matches_the_lemma():
    """활용형 질의가 사전형 검색어와 만나야 한다.

    "갈아주세요"는 토큰으로 '갈아주'가 되고 인덱스 검색어는 '갈다'라, 형태를 맞추지
    않으면 교집합이 0이다. 그래서 예전에는 '원두를 준비한다'와 완전 동점(0.000)으로
    갈려 자산 id 정렬순으로 오답이 뽑혔다.
    """
    from local_aac import _verb_lemmas

    assert "갈다" in _verb_lemmas("원두를 갈아주세요")

    results = search_assets(
        "원두를 갈아주세요",
        {"business_type": "카페", "sentence": "원두를 갈아주세요", "action_type": "other"},
        3,
    )
    assert results[0]["asset_id"] == "CAFE_013"  # 원두를 분쇄한다
    assert results[0]["score"] - results[1]["score"] > 0.02  # 더는 동점이 아니다


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
        ["테이프", "tape"],
        {"business_type": "포장", "sentence": "박스 아래쪽을 테이프로 막으세요.",
         "action_type": "pack"},
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


def test_asset_keywords_from_data_are_searchable():
    """aac_assets.json에 채워진 keywords/aliases/objects(ta3woong님 브랜치 병합분)가
    실제로 검색에 쓰여야 한다. 병합 전에는 이 필드가 전부 비어 있어 데드 코드였다.
    """
    from local_aac import load_assets

    with_keywords = sum(1 for a in load_assets() if a.get("keywords") or a.get("aliases"))
    assert with_keywords > 300, "asset 데이터에 keywords/aliases가 채워져 있어야 한다"


def test_retail_barcode_matches_after_merged_keywords():
    """병합 전에는 "바코드를 찍어 계산하세요"가 1순위 오답이었다. 병합된 keywords가
    이를 고쳤는지 회귀 테스트로 고정한다.
    """
    query = "바코드를 찍어 계산하세요."
    results = search_assets(
        query, {"business_type": "마트", "sentence": query, "action_type": "observe"}, 3,
    )
    assert results[0]["asset_id"] == "RETAIL_060"


def test_raw_input_infers_job_when_business_type_is_blank():
    """업종/작업환경을 안 넣으면 단계 문장 하나로는 직무를 못 알아낼 때가 많다.

    실사용 버그: "큰 나사를 나누세요"만으로는 조립인지 알 수 없어 카페(컵/접시)·
    청소(수건/옷) 자산이 1순위로 올라왔다. raw_input 전체("부품 상자에서 나사를...")를
    보조 신호로 주면 조립으로 추론돼 엉뚱한 직무가 밀려나야 한다.
    """
    from local_aac import infer_job, search_assets

    raw_input = (
        "부품 상자에서 나사를 꺼내서 종류별로 나눠 담아주세요. "
        "큰 나사는 파란 통, 작은 나사는 빨간 통에 넣습니다."
    )
    sentence = "큰 나사를 나누세요."
    ctx = {"sentence": sentence, "action_type": "sort", "raw_input": raw_input}

    assert infer_job(ctx, sentence) == "assembly"

    # "나사" 자산 자체가 없어(알려진 커버리지 갭) 완벽한 정답은 못 낸다. 이 테스트가
    # 잡는 것은 그것과 별개인 버그다 — 1순위가 카페/청소로 새지 않고 조립이어야 한다.
    results = search_assets(sentence, ctx, limit=5)
    assert results[0]["job"] == "assembly"


def test_opposite_verb_does_not_win_by_shared_noun():
    """실사용 버그: "남은 재료를 꺼내세요"(냉장고에서 빼기)가 "남은 재료를 냉장고에
    넣는다"(CAFE_088, 정반대 동작)로 자신 있게 붙었다.

    verb_class는 방향을 구분 못 한다 — '넣다'/'꺼내다' 둘 다 move라 기존
    _verb_class_penalty가 안 걸렸다. '꺼내다 냉장고' 자산 자체가 없는 갭이라
    완벽한 정답은 못 내지만, 최소한 정반대 동작을 자신 있게 채택하면 안 된다.
    """
    query = "남은 재료를 꺼내세요."
    ctx = {"business_type": "카페", "work_environment": "바",
           "sentence": query, "action_type": "move"}
    results = search_assets(query, ctx, 3)
    assert results[0]["asset_id"] != "CAFE_088"


def test_verb_antonym_penalty_only_fires_on_true_opposites():
    from local_aac import _verb_antonym_penalty, load_assets

    by = {a["id"]: a for a in load_assets()}
    # CAFE_088 verb='넣다' — '꺼내다'(반대말)는 깎이고, '보관하다'(동의어)는 안 깎인다.
    assert _verb_antonym_penalty(by["CAFE_088"], {"꺼내다"}) < 1.0
    assert _verb_antonym_penalty(by["CAFE_088"], {"보관하다"}) == 1.0
    assert _verb_antonym_penalty(by["CAFE_088"], set()) == 1.0


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

def test_canonical_job_business_type_mapping():
    """업종명 → 직무 매핑 회귀 테스트(2026-09-25 최종 평가에서 발견한 결함)."""
    from local_aac import _canonical_job
    assert _canonical_job("주유소 세차장") == "gas"
    assert _canonical_job("세차장") == "gas"
    assert _canonical_job("매장 진열") == "display"
    assert _canonical_job("청소") == "cleaning"
    assert _canonical_job("세탁") == "cleaning"
    assert _canonical_job("마트") == "retail"
    assert _canonical_job("택배 배송") == "delivery"
