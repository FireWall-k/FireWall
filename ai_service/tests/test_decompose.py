"""AI 분해기 단위 테스트 — 특히 쉼표 분할 회귀를 막는다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decompose import decompose  # noqa: E402


def _sentences(raw: str) -> list[str]:
    return [s.sentence for s in decompose(raw, {}).steps]


def test_sample_task_splits_into_four_clean_steps():
    raw = ("택배 상자를 크기별로 분류하고, 큰 상자는 A구역으로 옮겨주세요. "
           "그리고 5개씩 쌓아주세요. 마지막에 수량을 확인하세요.")
    steps = _sentences(raw)
    assert len(steps) == 4, steps
    assert "분류" in steps[0]
    assert "옮겨" in steps[1] or "옮기" in steps[1]
    assert "쌓" in steps[2]
    assert "확인" in steps[3]
    # '그리고'가 단계 문장 안에 남으면 안 된다.
    assert all("그리고" not in s for s in steps)


def test_list_commas_are_not_split():
    # 나열형 쉼표는 한 단계로 유지되어야 한다(기존 버그: 3조각으로 깨짐).
    steps = _sentences("사과, 배, 귤을 담으세요.")
    assert len(steps) == 1, steps
    assert "사과" in steps[0] and "배" in steps[0] and "귤" in steps[0]


def test_sequential_hago_comma_splits():
    steps = _sentences("재료를 씻고, 그릇에 담으세요.")
    # "씻고," 는 순차 연결어미+쉼표 → 분할
    assert len(steps) == 2, steps


def test_order_is_sequential_and_starts_at_one():
    result = decompose("문을 열고, 불을 켜세요. 그리고 청소를 하세요.", {})
    orders = [s.order for s in result.steps]
    assert orders == list(range(1, len(orders) + 1))


def test_action_type_detected():
    result = decompose("상자를 옮겨주세요.", {})
    assert result.steps[0].action_type == "move"


def test_single_sentence_no_connective():
    steps = _sentences("바닥을 깨끗하게 닦으세요")
    assert len(steps) == 1, steps


def test_adjective_go_is_not_split():
    # 형용사 연결 '~하고,'는 나열로 보고 한 단계로 유지(과분할 회귀 방지).
    steps = _sentences("작업대를 깨끗하고, 안전하게 정리하세요.")
    assert len(steps) == 1, steps


def test_verb_go_still_splits_after_adjective_fix():
    # 동작 동사 '~하고,'는 여전히 분할되어야 한다.
    steps = _sentences("상자를 분류하고, 선반에 올리세요.")
    assert len(steps) == 2, steps


def test_mixed_adjective_and_verb():
    steps = _sentences("그릇을 깨끗하고, 빠르게 씻고, 선반에 두세요.")
    # '깨끗하고,'(형용사)는 유지, '씻고,'(동사)는 분할 → 2단계
    assert len(steps) == 2, steps
    assert "씻" in steps[0]
    assert "선반" in steps[1]


def test_llm_job_keeps_all_registered_jobs():
    """LLM이 고른 직무가 나중에 추가된 직무(식당·진열·택배·주유)여도 버리지 않는다.

    직무 목록이 초기 5개에 머물러 있어 LLM이 'gas'라고 답해도 'unknown'으로 바뀌었다.
    """
    from decompose import _build_from_llm

    for job in ("serving", "display", "delivery", "gas"):
        raw = {"task_title": "t", "job": job,
               "steps": [{"sentence": "차 문을 닫으세요.", "symbol_query": ["문 닫기"],
                          "action_type": "operate"}]}
        assert _build_from_llm(raw).job == job


def test_fallback_job_inference_matches_matcher():
    """규칙 폴백의 직무 추론도 매칭과 같은 사전을 쓴다(세차장 → 주유, 매장 진열 → 진열)."""
    assert decompose("차에 물을 뿌리세요.", {"business_type": "주유소 세차장"}).job == "gas"
    assert decompose("상품을 앞으로 당기세요.", {"business_type": "매장 진열"}).job == "display"
    assert decompose("빈 그릇을 치우세요.", {"business_type": "식당"}).job == "serving"


def test_fallback_job_inference_uses_business_type_names():
    """업종명 별칭(taxonomy.JOB_ALIASES)은 매칭뿐 아니라 분해기의 직무 추론도 바꾼다.

    원문(raw_input)도 함께 보므로, 장소 이름(호텔·빌딩·오피스)은 별칭에 두지 않는다 — 그 안의
    카페·식당 일까지 청소로 잡게 된다.
    """
    assert decompose("침대 시트를 바꾸세요.", {"business_type": "호텔 객실 정비"}).job == "cleaning"
    assert decompose("불판을 갈아 주세요.", {"business_type": "고깃집"}).job == "serving"
    assert decompose("옷을 개어 걸어 두세요.", {"business_type": "옷가게"}).job == "display"
    assert decompose("컵을 씻으세요.", {"business_type": "빌딩 1층 카페"}).job == "cafe"
    assert decompose("빌딩 1층 카페에서 컵을 씻으세요.", {}).job == "cafe"
    assert decompose("호텔 레스토랑에서 접시를 치우세요.", {}).job != "cleaning"


# ---- 동작 분류(action_type) — 근로자 화면 꼬리표와 그림 검색 동사 계열 벌점에 쓰인다 ----
# 예전 규칙은 힌트 글자를 문장 어디서든 찾아서, 지시문 끝 "-세요"의 '세'(세다)를 observe로 읽었다.
# 상자 덮개를 접는 그림 밑에 '확인하기'·'담기' 같은 틀린 꼬리표가 붙던 원인이다.

def _action(sentence: str) -> str:
    return decompose(sentence, {}).steps[0].action_type


def test_seyo_ending_is_not_read_as_counting():
    # '-세요'의 '세'는 세다(observe)가 아니다. 접다는 그림 인덱스에서 pack 계열이다.
    assert _action("박스 바닥 덮개를 접으세요") == "pack"


def test_modifier_verb_does_not_decide_action():
    # 꾸미는 말 '포장된'이 아니라 서술어 '놓으세요'가 할 일이다.
    assert _action("포장된 상자를 카트에 놓으세요") == "move"


def test_noun_fragment_is_not_a_verb():
    # '입력'의 '입'은 입다(wear)가 아니다. '보관'의 '보'도 보다(observe)가 아니다.
    assert _action("포스기에 주문을 입력하세요") == "operate"
    assert _action("물건을 창고에 보관하세요") != "observe"


def test_ambiguous_verb_is_other():
    # 붙이다는 인덱스에서 계열이 갈린다(other·assemble·pack) — 확실하지 않으면 other(화면은 꼬리표를 숨긴다).
    assert _action("박스 바닥에 테이프를 붙이세요") == "other"


def test_two_actions_of_different_classes_is_other():
    assert _action("손을 씻고 위생 장갑을 끼세요") == "other"


def test_common_actions_are_classified():
    assert _action("상자 수량을 확인하세요") == "observe"
    assert _action("밀대로 바닥을 닦으세요") == "clean"
    assert _action("상자를 5개씩 쌓아주세요") == "stack"


def test_hada_with_action_noun():
    # "청소를 하세요"는 동사가 '하다'뿐이라 동작이 명사에 있다.
    assert _action("청소를 하세요") == "clean"


def test_push_with_cleaning_tool_is_clean():
    # 밀다는 인덱스에서 move지만, 청소 도구로 미는 것은 청소다(맞는 청소 그림이 계열 벌점을 받던 문제).
    assert _action("차 안 바닥을 청소기로 밀어주세요") == "clean"
    assert _action("대걸레로 바닥을 미세요") == "clean"
    assert _action("청소기를 돌리세요") == "clean"
    # 도구가 없으면 그대로 옮기기다.
    assert _action("카트를 밀어 주세요") == "move"
