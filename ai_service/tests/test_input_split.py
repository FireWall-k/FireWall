"""입력 화면 단계 나누기 — GPT 분할 검산(_reconcile)과 계약 필드(split_group·split_check·source_text).

네트워크를 쓰지 않는다: llm.chat_json을 가짜 응답으로 바꾼다. 예시 문장은 분할 정답셋 밖의 문장이다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decompose  # noqa: E402
import llm  # noqa: E402
from decompose import decompose as run  # noqa: E402


def _gpt(monkeypatch, steps, seen=None):
    def fake(system, user, **kw):
        if seen is not None:
            seen.append(user)
        return {"task_title": "t", "job": "cafe", "steps": steps}
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", fake)


def _step(sentence, query, src=1, action="move"):
    return {"sentence": sentence, "symbol_query": [query], "action_type": action, "safety_flags": [], "src": src}


def test_gpt_split_of_a_listed_object_is_merged_back_without_flag(monkeypatch):
    # 동사가 하나뿐인 문장을 GPT가 물건별로 나눔 → 원문 한 단계로 되돌리고, 확실하므로 노란 표시 없음.
    _gpt(monkeypatch, [_step("자를 서랍에 넣으세요.", "자를 서랍에 넣다"),
                       _step("가위를 서랍에 넣으세요.", "가위를 서랍에 넣다")])
    steps = run("자와 가위를 서랍에 넣으세요.", {}).steps
    assert len(steps) == 1
    s = steps[0]
    assert s.sentence == "자와 가위를 서랍에 넣으세요."
    assert s.symbol_query == ["가위를 서랍에 넣다"]  # 마지막 단계의 검색어
    assert (s.split_group, s.split_check, s.source_text) == (None, False, None)
    assert s.order == 1


def test_gpt_split_over_an_absorbed_verb_is_merged_and_flagged(monkeypatch):
    # '채워 넣다'는 규칙이 한 동작으로 묶은 보조 동사 묶음 — 합치되 확실하지 않으니 사업주 확인.
    _gpt(monkeypatch, [_step("빨대를 통에 채우세요.", "빨대를 채우다"),
                       _step("빨대를 통에 넣으세요.", "빨대를 통에 넣다")])
    steps = run("빨대를 통에 채워 넣으세요.", {}).steps
    assert len(steps) == 1
    assert steps[0].split_check is True
    assert steps[0].split_group is None


def test_gpt_split_agreeing_with_rules_is_sure_and_grouped(monkeypatch):
    _gpt(monkeypatch, [_step("컵을 씻으세요.", "컵을 씻다", action="clean"),
                       _step("컵을 건조대에 올리세요.", "컵을 건조대에 올리다")])
    steps = run("컵을 씻어서 건조대에 올리세요.", {}).steps
    assert [s.sentence for s in steps] == ["컵을 씻으세요.", "컵을 건조대에 올리세요."]
    assert [s.split_group for s in steps] == [1, 1]
    assert [s.split_check for s in steps] == [False, False]
    assert all(s.source_text == "컵을 씻어서 건조대에 올리세요." for s in steps)
    assert [s.order for s in steps] == [1, 2]


def test_gpt_left_two_actions_together_is_flagged(monkeypatch):
    # 규칙은 동작 둘(씻다·올리다), GPT는 한 단계 → GPT를 두고 노란 표시.
    _gpt(monkeypatch, [_step("컵을 씻어서 건조대에 올리세요.", "컵을 건조대에 올리다")])
    steps = run("컵을 씻어서 건조대에 올리세요.", {}).steps
    assert len(steps) == 1
    assert steps[0].split_check is True
    assert steps[0].split_group is None


def test_gpt_split_beyond_two_rule_actions_is_kept_and_flagged(monkeypatch):
    _gpt(monkeypatch, [_step("컵을 씻으세요.", "컵을 씻다"), _step("컵을 헹구세요.", "컵을 헹구다"),
                       _step("컵을 건조대에 올리세요.", "컵을 건조대에 올리다")])
    steps = run("컵을 씻어서 건조대에 올리세요.", {}).steps
    assert len(steps) == 3
    assert all(s.split_check for s in steps)
    assert {s.split_group for s in steps} == {1}


def test_gpt_gets_numbered_clauses_and_src_maps_steps_to_sentences(monkeypatch):
    seen = []
    _gpt(monkeypatch, [_step("자와 가위를 서랍에 넣으세요.", "자와 가위를 서랍에 넣다", src=1),
                       _step("컵을 씻으세요.", "컵을 씻다", src=2),
                       _step("컵을 건조대에 올리세요.", "컵을 건조대에 올리다", src=2)], seen)
    steps = run("자와 가위를 서랍에 넣으세요. 컵을 씻어서 건조대에 올리세요.", {}).steps
    assert "원문 조각:\n1) 자와 가위를 서랍에 넣으세요\n2) 컵을 씻어서 건조대에 올리세요" in seen[0]
    assert [s.split_group for s in steps] == [None, 1, 1]
    assert steps[1].source_text == "컵을 씻어서 건조대에 올리세요."
    assert not any(s.split_check for s in steps)


def test_bad_src_falls_back_to_text_overlap(monkeypatch):
    # src가 없거나 범위를 벗어나면 글자 겹침으로 조각을 정한다(순서는 되돌아가지 않음).
    _gpt(monkeypatch, [{**_step("자와 가위를 서랍에 넣으세요.", "자와 가위를 서랍에 넣다"), "src": 9},
                       {**_step("컵을 건조대에 올리세요.", "컵을 건조대에 올리다"), "src": None}])
    steps = run("자와 가위를 서랍에 넣으세요. 컵을 건조대에 올리세요.", {}).steps
    assert [s.sentence for s in steps] == ["자와 가위를 서랍에 넣으세요.", "컵을 건조대에 올리세요."]
    assert [s.split_group for s in steps] == [None, None]


def test_comma_split_steps_share_the_sentence_group():
    # 규칙 경로: 한 문장이 쉼표 순차 어미로 둘이 되면 같은 묶음, 원문 문장이 source_text.
    steps = run("재료를 씻고, 그릇에 담으세요. 불을 끄세요.", {}).steps
    assert [s.split_group for s in steps] == [1, 1, None]
    assert steps[0].source_text == "재료를 씻고, 그릇에 담으세요."
    assert steps[2].source_text is None


def test_rule_path_auto_split_fills_fields():
    steps = run("상자를 접고 테이프를 붙이세요.", {}).steps
    assert [s.sentence for s in steps] == ["상자를 접으세요", "테이프를 붙이세요"]
    assert [s.split_group for s in steps] == [1, 1]
    assert not any(s.split_check for s in steps)
    assert steps[0].source_text == "상자를 접고 테이프를 붙이세요."


def test_rule_path_flags_two_actions_it_could_not_split():
    steps = run("손님이 오면 인사하고 메뉴판을 드리세요.", {}).steps
    assert len(steps) == 1
    assert steps[0].split_check is True
    assert steps[0].split_group is None


def test_rule_path_one_action_is_sure():
    steps = run("자와 가위를 서랍에 넣으세요.", {}).steps
    assert len(steps) == 1
    assert (steps[0].split_group, steps[0].split_check, steps[0].source_text) == (None, False, None)


def test_contract_fields_are_serialized():
    d = run("상자를 접고 테이프를 붙이세요.", {}).model_dump()
    assert {"split_group", "split_check", "source_text"} <= set(d["steps"][0])


def test_llm_decompose_without_clauses_keeps_old_message(monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: seen.append(user) or {})
    llm.llm_decompose("컵을 닦으세요.", {})
    assert "원문 조각" not in seen[0]


def test_decompose_prompt_drops_split_per_object_rule():
    # 과분할의 원인이던 '물건별 단계로 나눈다' 지시가 돌아오지 않게.
    assert "물건별 단계로 나눕니다" not in llm._DECOMPOSE_SYSTEM
    assert "src" in llm._DECOMPOSE_SYSTEM


def test_rule_path_uses_split_suggestion_as_yellow_split(monkeypatch):
    # GPT가 안 될 때(키 오류 등): 규칙이 확실하진 않지만 나누기 제안을 냈으면 제안대로 나누고 노란 표시.
    # 한 줄에 동작 둘이 남지 않게 하고, 틀렸으면 사업주가 [합치기]로 원문(source_text)을 되돌린다.
    monkeypatch.setattr(llm, "llm_available", lambda: False)
    steps = run("그릇을 헹궈서 선반에 올려 두세요.", {}).steps
    # 뒤 단계는 대상이 없어 앞 단계 대상을 이어 붙인다(2차 검증 — 무엇을 올리는지 남기기).
    assert [s.sentence for s in steps] == ["그릇을 헹구세요", "그릇을 선반에 올려 두세요"]
    assert [s.split_group for s in steps] == [1, 1]
    assert all(s.split_check for s in steps)
    assert {s.source_text for s in steps} == {"그릇을 헹궈서 선반에 올려 두세요."}


def test_decompose_http_response_carries_contract_fields(monkeypatch):
    # 백엔드가 받는 실제 HTTP 응답(JSON)에 세 칸이 그대로 실린다(response_model이 버리지 않는다).
    from fastapi.testclient import TestClient

    import main as ai_main

    monkeypatch.setattr(llm, "llm_available", lambda: False)
    r = TestClient(ai_main.app).post("/ai/decompose", json={
        "raw_input": "상자를 접고 테이프를 붙이세요. 그릇을 헹궈서 선반에 올려 두세요. 불을 끄세요.",
        "context": {}})
    assert r.status_code == 200, r.text
    steps = r.json()["steps"]
    assert [(s["split_group"], s["split_check"]) for s in steps] == [
        (1, False), (1, False), (2, True), (2, True), (None, False)]
    assert steps[0]["source_text"] == "상자를 접고 테이프를 붙이세요."
    assert steps[2]["source_text"] == "그릇을 헹궈서 선반에 올려 두세요."
    assert steps[4]["source_text"] is None


# ---- 1차 검증 반영 -----------------------------------------------------------------------------

def _rule(text):
    return [(s.sentence, s.split_check) for s in decompose._rule_decompose(text, {}).steps]


def test_rule_path_comma_fragment_with_negation_is_not_its_own_step():
    # 쉼표 앞 부정 조각("컵을 씻지 말고.")이 따로 단계가 되면 씻는 그림이 붙을 수 있다 — 한 단계로, 노란 줄.
    for text in ("컵을 씻지 말고, 바로 버리세요.", "냅킨은 버리지 말고, 모아 두세요.",
                 "상자를 접고, 테이프는 붙이지 마세요."):
        steps = _rule(text)
        assert len(steps) == 1, (text, steps)
        assert steps[0][1] is True
        assert "말고." not in steps[0][0]


def test_rule_path_comma_fragment_of_another_person_is_not_a_worker_step():
    steps = _rule("손님이 나가고, 테이블을 치우세요.")
    assert len(steps) == 1
    assert steps[0][0].startswith("손님이 나가고, 테이블을 치우세요")


def test_rule_path_comma_split_writes_imperatives_not_fragments():
    assert _rule("물기를 닦은 후, 전원을 켜세요.") == [("물기를 닦으세요", False), ("전원을 켜세요", False)]
    assert _rule("상자를 접고, 테이프를 붙이세요.") == [("상자를 접으세요", False), ("테이프를 붙이세요", False)]
    # 지시형 문장을 못 만든 조각은 남기되 노란 줄이다(말없이 "~다음."이 나가지 않게).
    steps = _rule("컵을 헹군 다음, 건조대에 엎어 두세요.")
    assert all(check for _, check in steps), steps


def test_gpt_sees_the_same_comma_pieces_but_negation_clause_is_checked(monkeypatch):
    # GPT 입력의 원문 조각은 전과 같다(응답 캐시·측정이 그대로). 검산은 문장 전체(부정) 단위다.
    seen = []
    _gpt(monkeypatch, [_step("컵을 씻지 마세요.", "컵 씻다", 1), _step("바로 버리세요.", "컵 버리다", 2)], seen)
    steps = run("컵을 씻지 말고, 바로 버리세요.", {}).steps
    assert "1) 컵을 씻지 말고\n2) 바로 버리세요" in seen[0]
    assert [s.split_check for s in steps] == [True, True]


def test_gpt_split_is_flagged_when_rule_misses_a_light_verb_or_conditioned_verb(monkeypatch):
    # 규칙이 '정리를 하고'·'맡아 보고(이상하면)'를 동작으로 못 세 하나로 본다 — 맞는 GPT 분할을 말없이 합치지 않는다.
    _gpt(monkeypatch, [_step("창고를 정리하세요.", "창고 정리하다"), _step("4시에 퇴근하세요.", "퇴근하다")])
    steps = run("오후 3시에 창고 정리를 하고 4시에 퇴근하세요.", {}).steps
    assert all(s.split_check for s in steps)
    _gpt(monkeypatch, [_step("냄새를 맡아 보세요.", "냄새 맡다"), _step("이상하면 버리세요.", "버리다")])
    steps = run("냄새를 맡아 보고 이상하면 버리세요.", {}).steps
    assert all(s.split_check for s in steps)


def test_gpt_extra_verb_without_rule_explanation_is_flagged(monkeypatch):
    # 동사 하나인 문장에 GPT가 다른 동작을 덧붙임 → 합치되 확인(규칙이 나열·갈라 담기 같은 근거를 못 찾음).
    _gpt(monkeypatch, [_step("컵을 닦으세요.", "컵 닦다"), _step("컵을 확인하세요.", "컵 확인하다")])
    steps = run("컵을 닦으세요.", {}).steps
    assert len(steps) == 1 and steps[0].split_check is True
    # 갈라 담기는 규칙이 아는 한 동작이라 확인 없이 합친다.
    _gpt(monkeypatch, [_step("사과를 크기별로 나누세요.", "사과 나누다"), _step("바구니에 담으세요.", "사과 담다")])
    steps = run("사과를 크기별로 나눠 바구니에 담으세요.", {}).steps
    assert len(steps) == 1 and steps[0].split_check is False


def test_src_that_leaves_a_clause_empty_is_rejected(monkeypatch):
    # [1, 1]은 범위 안·순서대로지만 2번 조각에 단계가 없다 → 글자 겹침으로 다시 맞춘다(테이프 단계가 사라지지 않게).
    _gpt(monkeypatch, [_step("상자를 접으세요.", "상자 접다", 1), _step("테이프를 붙이세요.", "테이프 붙이다", 1)])
    steps = run("상자를 접고, 테이프를 붙이세요.", {}).steps
    assert [s.sentence for s in steps] == ["상자를 접으세요.", "테이프를 붙이세요."]
    assert [s.symbol_query for s in steps] == [["상자 접다"], ["테이프 붙이다"]]


def test_dropped_clause_flags_its_sentence(monkeypatch):
    # GPT가 두 원문 조각을 한 단계로 묶었다 → 그 문장의 단계는 노란 줄.
    _gpt(monkeypatch, [_step("상자를 접고 테이프를 붙이세요.", "상자 접다", 1)])
    steps = run("상자를 접고, 테이프를 붙이세요.", {}).steps
    assert len(steps) == 1 and steps[0].split_check is True


def test_invented_step_does_not_lend_its_picture_to_a_merged_step(monkeypatch):
    # GPT가 src 없이 원문에 없는 '바닥 쓸기'를 덧붙였다 → 합친 단계의 검색어는 원문에 기댄 단계 것, 노란 줄.
    _gpt(monkeypatch, [_step("테이블을 닦으세요.", "테이블 닦다", None), _step("의자를 넣으세요.", "의자 넣다", None),
                       _step("바닥을 쓰세요.", "바닥 쓸다", None)])
    steps = run("테이블을 닦으세요. 의자를 넣으세요.", {}).steps
    assert [s.symbol_query for s in steps] == [["테이블 닦다"], ["의자 넣다"]]
    assert steps[1].split_check is True


def test_rule_path_flags_press_or_pour_hidden_as_manner():
    assert _rule("도착하면 벨을 누르고 기다리세요.")[0][1] is True
    assert _rule("물을 두 잔 따라서 손님께 갖다 드리세요.")[0][1] is True
    # 한 동작 묶음("눌러 뚫다")은 그대로.
    assert _rule("상자 옆면의 손잡이 구멍을 눌러 뚫어 주세요.")[0][1] is False


def test_dependent_noun_object_blocks_auto_split():
    # "지난 것은 빼세요"는 혼자 읽으면 무엇이 지났는지 모른다 — 자동 분할이 아니라 노란 제안.
    steps = _rule("유통기한을 확인하고 지난 것은 빼세요.")
    assert len(steps) == 2 and all(check for _, check in steps)


def test_decimal_point_is_not_a_sentence_end():
    assert _rule("2.5L 생수를 하나씩 꺼내세요.") == [("2.5L 생수를 하나씩 꺼내세요", False)]
    assert decompose._split_steps("2.5L 생수를 꺼내세요. 상자를 접으세요.") == ["2.5L 생수를 꺼내세요", "상자를 접으세요"]


# ---- 2차 검증 회귀 ------------------------------------------------------------------------------

def _no_gpt(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: False)


def test_rule_path_connective_pieces_are_checked_like_comma_pieces(monkeypatch):
    # '그리고/그다음'에서 먼저 자르면 부정·남의 일·끝나지 않은 조각이 노란 표시 없이 단계가 됐다.
    _no_gpt(monkeypatch)
    steps = _rule("컵은 씻지 말고 그다음 선반에 올리세요.")
    assert len(steps) == 1 and steps[0][1] is True
    assert not steps[0][0].endswith("말고.")
    steps = _rule("손님이 나가고 그리고 테이블을 닦으세요.")
    assert len(steps) == 1 and steps[0][1] is True
    assert _rule("먼저 손을 씻고 그다음 앞치마를 입으세요.") == [("먼저 손을 씻으세요", False),
                                                       ("앞치마를 입으세요", False)]
    # 앞부분이 이미 끝난 지시면 접속어에서 그대로 나눈다.
    assert _rule("테이블을 닦으세요 그리고 의자를 넣으세요.") == [("테이블을 닦으세요", False),
                                                       ("의자를 넣으세요", False)]


def test_connective_pieces_shown_to_gpt_are_unchanged(monkeypatch):
    seen = []
    _gpt(monkeypatch, [_step("손을 씻으세요.", "손 씻다", 1), _step("앞치마를 입으세요.", "앞치마 입다", 2)], seen)
    steps = run("먼저 손을 씻고 그다음 앞치마를 입으세요.", {}).steps
    assert "1) 먼저 손을 씻고" + chr(10) + "2) 앞치마를 입으세요" in seen[0]
    assert [s.split_check for s in steps] == [False, False]


def test_sort_with_go_or_comma_is_two_actions(monkeypatch):
    # '-고'·쉼표로 이은 나누기·모으기 + 놓기는 두 동작(갈라 담기 한 동작은 '-어' 연결일 때만).
    _no_gpt(monkeypatch)
    for text in ("빨래를 색깔별로 분류하고 세탁기에 넣으세요.", "물건을 종류별로 나누고, 선반에 놓으세요.",
                 "숟가락과 포크를 모으고 서랍에 넣으세요.",
                 "도착한 우편물을 부서별로 분류하고, 각 부서 자리에 가져다 놓으세요."):
        steps = _rule(text)
        assert len(steps) == 2 or steps[0][1] is True, (text, steps)
        assert decompose.clauses_of(text)[0].plan.actions == 2 or len(decompose.clauses_of(text)) == 2, text
    assert _rule("숟가락을 종류별로 나눠 담으세요.") == [("숟가락을 종류별로 나눠 담으세요", False)]
    # GPT가 맞게 둘로 나눈 것을 다시 합치지 않는다.
    _gpt(monkeypatch, [_step("빨래를 색깔별로 분류하세요.", "빨래 분류하다"), _step("세탁기에 넣으세요.", "빨래 넣다")])
    steps = run("빨래를 색깔별로 분류하고 세탁기에 넣으세요.", {}).steps
    assert len(steps) == 2


def test_comma_go_with_manner_verb_counts_two_actions(monkeypatch):
    _gpt(monkeypatch, [_step("컵에 물을 따르세요.", "물 따르다", 1), _step("테이블에 놓으세요.", "컵 놓다", 2)])
    steps = run("컵에 물을 따르고, 테이블에 놓으세요.", {}).steps
    assert [s.sentence for s in steps] == ["컵에 물을 따르세요.", "테이블에 놓으세요."]
    assert [s.split_check for s in steps] == [False, False]
    # 쉼표 없는 방법 동사는 그대로 한 동작.
    _no_gpt(monkeypatch)
    assert _rule("손잡이를 잡고 당기세요.") == [("손잡이를 잡고 당기세요", False)]


def test_rule_path_cuts_commas_when_actions_outnumber_pieces(monkeypatch):
    _no_gpt(monkeypatch)
    steps = _rule("서류를 복사기에 넣고 복사한 뒤, 클립으로 묶어 테이블에 놓으세요.")
    assert len(steps) >= 2 and all(check for _, check in steps)
    assert steps[0][0] == "서류를 복사기에 넣고 복사하세요"
    # 부정이 있으면 자르지 않는다.
    steps = _rule("컵을 씻고 헹구지 말고, 바로 버리세요.")
    assert len(steps) == 1 and steps[0][1] is True


def test_unknown_verb_before_after_is_flagged(monkeypatch):
    _no_gpt(monkeypatch)
    assert _rule("물을 끓인 뒤 티백을 넣으세요.")[0][1] is True
    assert all(check for _, check in _rule("물을 끓인 뒤 티백을 넣고 3분 기다리세요."))


def test_object_is_carried_into_a_yellow_draft_step(monkeypatch):
    _no_gpt(monkeypatch)
    steps = run("걸레를 빨아서 짜 주세요.", {}).steps
    assert [s.sentence for s in steps] == ["걸레를 빨아 주세요", "걸레를 짜 주세요"]
    assert all(s.split_check for s in steps)
    assert "주세요" not in [k.term for s in steps for k in s.keywords]


def test_gpt_lost_condition_is_restored(monkeypatch):
    # 한 동작 문장: 사업주 원문을 쓴다(조건·받는 사람·도구를 지킨다).
    _gpt(monkeypatch, [_step("밖에서 기다리세요.", "기다리다")])
    steps = run("고객이 화장실을 쓰고 있으면 밖에서 기다리세요.", {}).steps
    assert [s.sentence for s in steps] == ["고객이 화장실을 쓰고 있으면 밖에서 기다리세요."]
    assert steps[0].symbol_query == ["기다리다"]
    # 나뉜 문장: 첫 단계 앞에 조건 절을 붙인다.
    _gpt(monkeypatch, [_step("앞치마를 입으세요.", "앞치마 입다"), _step("손을 씻으세요.", "손 씻다")])
    steps = run("출근하면 앞치마를 입고 손을 씻으세요.", {}).steps
    assert [s.sentence for s in steps] == ["출근하면 앞치마를 입으세요.", "손을 씻으세요."]
    # 조건을 지켰으면 그대로, 순서 말(뒤)은 조건이 아니다.
    _gpt(monkeypatch, [_step("쓰레기통이 차면 비우세요.", "비우다")])
    assert run("쓰레기통이 꽉 차면 비우세요.", {}).steps[0].sentence == "쓰레기통이 차면 비우세요."
    _gpt(monkeypatch, [_step("컵을 씻으세요.", "컵 씻다"), _step("컵을 건조대에 올리세요.", "컵 올리다")])
    steps = run("컵을 씻은 뒤 건조대에 올리세요.", {}).steps
    assert steps[0].sentence == "컵을 씻으세요."


def test_gpt_wrong_polite_form_is_fixed_or_flagged(monkeypatch):
    _gpt(monkeypatch, [_step("원두를 눌러세요.", "원두 누르다")])
    steps = run("탬퍼로 원두를 꾹 눌러 주세요.", {}).steps
    assert steps[0].sentence == "원두를 누르세요."
    _gpt(monkeypatch, [_step("앞치마를 둘러세요.", "앞치마 두르다")])
    assert run("앞치마를 두르세요.", {}).steps[0].sentence == "앞치마를 두르세요."
    # 원형을 하나로 못 정하면(걸어: 걷다/걸다) 문장을 두고 노란 줄.
    _gpt(monkeypatch, [_step("천천히 걸어세요.", "걷다")])
    steps = run("천천히 걸으세요.", {}).steps
    assert steps[0].split_check is True
