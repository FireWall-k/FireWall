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
    assert [s.sentence for s in steps] == ["그릇을 헹구세요", "선반에 올려 두세요"]
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
