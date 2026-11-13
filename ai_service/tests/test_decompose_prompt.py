"""3a 문장·그림 정확도(M2·M3·N9) — 단계 나누기 지시문과 GPT 호출 값.

실제 API는 부르지 않는다: llm.chat_json 또는 llm._http만 가짜로 바꾼다. 예시 문장은 분할 정답셋·realsmoke 직무
문장이 아니다.
"""
import json
import os
import re
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import decompose as dec  # noqa: E402
import llm  # noqa: E402

P = llm._DECOMPOSE_SYSTEM


# ---------- 지시문 규칙 ----------

def test_prompt_keeps_employer_haeyo_tone_and_forbids_command_tone():
    assert "'~해요/~어요/~아요' 말투" in P
    for command in ("'~하세요'", "'~하십시오'", "'~해라'"):
        assert command in P
    assert "명령조로 바꾸지 않습니다" in P
    assert "원문이 '~세요'로 쓰였어도 sentence는 '~해요' 말투" in P
    assert "명령형" not in P   # 예전 '짧고 명확한 한국어 명령형' 지시가 남아 있지 않다


def test_prompt_reminds_irregular_conjugation():
    assert "'줍다' → '주워요'('줍어요'는 틀림)" in P


def test_prompt_keeps_tool_words():
    for tool in ("'행주로'", "'빗자루로'", "'집게로'"):
        assert tool in P
    assert "도구 낱말을 빼지 않습니다" in P


def test_prompt_one_action_per_sentence():
    assert "1) 단계 나누기: 한 단계 = 동작 하나 = AAC 그림 한 장" in P
    assert "sentence 하나에는 그림 한 장으로 그릴 동작 하나만" in P
    assert "sentence 하나에 동작이 하나뿐인지" in P


def test_prompt_keeps_negation_and_condition_meaning():
    assert "금지 지시와 부정 의미는 긍정 행동으로 바꾸지 않습니다" in P
    assert "조건과 동작의 짝·뜻을 뒤집지 않습니다" in P
    assert "'~하면 안 돼요'" in P


def test_prompt_title_covers_all_groups():
    assert "10) task_title" in P
    assert "제목에는 모든 묶음의 이름이 들어갑니다" in P
    assert "첫 문장부터 마지막 문장까지 빠지는 묶음이 없어야" in P
    assert "'박스 접기·라벨 붙이기·바닥 청소'" in P        # 세 부분 예시
    assert "짧게 하려고 묶음을 빼지 않습니다" in P
    assert "task_title이 모든 일 묶음을 담았는지" in P
    assert "20자 안팎)입니다" not in P                       # 제목을 두 부분으로 줄이게 하던 글자 수 지시가 없다


def _quoted_sentences(prompt: str) -> list[str]:
    out = re.findall(r"sentence: '([^']+)'", prompt)
    out += re.findall(r'"sentence":"([^"]+)"', prompt)
    return [s for s in out if not s.startswith("'")]


def test_prompt_examples_are_haeyo_and_keep_tools():
    """예시 출력 문장이 명령조면 GPT가 그 말투를 따라 한다(실제 시험에서 12단계 중 11단계)."""
    sentences = _quoted_sentences(P)
    assert len(sentences) >= 7
    for s in sentences:
        assert not s.rstrip(".").endswith(("세요", "십시오")), s
    assert "드라이버로 나사를 조여요." in sentences   # 도구 낱말을 남긴 예시
    example = json.loads(P[P.index("예시 출력:\n") + len("예시 출력:\n"):])
    assert example["task_title"] == "부품 나누기·커넥터 연결"   # 두 묶음을 모두 담은 제목


# ---------- temperature 0 ----------

def test_llm_decompose_asks_temperature_zero(monkeypatch):
    seen = {}

    def fake(system, user, **kw):
        seen.update(kw, system=system)
        return {"task_title": "t", "steps": [{"sentence": "컵을 닦아요.", "action_type": "clean"}]}

    monkeypatch.setattr(llm, "chat_json", fake)
    llm.llm_decompose("컵을 닦아요.", {})
    assert seen["temperature"] == 0
    assert seen["system"] is llm._DECOMPOSE_SYSTEM


class _Resp:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": json.dumps(
            {"task_title": "t", "steps": [{"sentence": "컵을 닦아요.", "action_type": "clean"}]})}}]}


def _capture_http(monkeypatch):
    bodies = []
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "_http", types.SimpleNamespace(
        post=lambda url, headers=None, json=None, timeout=None: bodies.append(json) or _Resp()))
    return bodies


def test_wire_body_has_temperature_zero_for_decompose_only(monkeypatch):
    bodies = _capture_http(monkeypatch)
    llm.llm_decompose("컵을 닦아요.", {})
    assert bodies[-1]["temperature"] == 0
    assert bodies[-1]["messages"][0]["content"] == llm._DECOMPOSE_SYSTEM
    # 재순위·코칭 등 다른 호출의 기본값은 그대로(재순위 판정 캐시·측정이 0.2 기준이다).
    llm.chat_json("sys", "usr")
    assert bodies[-1]["temperature"] == 0.2


# ---------- 규칙을 따른 GPT 응답이 그대로 남는가(가짜 GPT) ----------

def _gpt(monkeypatch, reply):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: reply)


def test_haeyo_tool_sentences_and_full_title_survive_post_processing(monkeypatch):
    _gpt(monkeypatch, {
        "task_title": "빵 담기와 컵 씻기", "job": "cafe",
        "steps": [
            {"sentence": "집게로 빵을 쟁반에 담아요.", "symbol_query": ["집게로 빵을 쟁반에 담다"],
             "action_type": "pack", "safety_flags": [], "src": 1},
            {"sentence": "수세미로 컵을 씻어요.", "symbol_query": ["수세미로 컵을 씻다"],
             "action_type": "clean", "safety_flags": [], "src": 2},
        ]})
    result = dec.decompose("집게로 빵을 쟁반에 담아요. 수세미로 컵을 씻어요.", {})
    assert [s.sentence for s in result.steps] == ["집게로 빵을 쟁반에 담아요.", "수세미로 컵을 씻어요."]
    assert result.task_title == "빵 담기와 컵 씻기"


def test_seyo_from_gpt_on_haeyo_input_is_turned_back(monkeypatch):
    """GPT가 지시를 어겨 '~세요'로 써도 사업주가 '~해요'로 쓴 지시문이면 되돌린다(8df0c99 규칙, 그대로)."""
    _gpt(monkeypatch, {
        "task_title": "t", "job": "cafe",
        "steps": [{"sentence": "집게로 빵을 쟁반에 담으세요.", "symbol_query": ["집게로 빵을 쟁반에 담다"],
                   "action_type": "pack", "safety_flags": [], "src": 1}]})
    result = dec.decompose("집게로 빵을 쟁반에 담아요.", {})
    assert [s.sentence for s in result.steps] == ["집게로 빵을 쟁반에 담아요."]


def test_haeyo_prohibition_passes_negation_check(monkeypatch):
    """금지를 '~하면 안 돼요'로 바꿔 써도 금지 검사를 통과한다(뜻 뒤집힘 아님)."""
    _gpt(monkeypatch, {
        "task_title": "t", "job": "cafe",
        "steps": [{"sentence": "젖은 손으로 콘센트를 만지면 안 돼요.", "symbol_query": ["젖은 손으로 콘센트를 만지지 않다"],
                   "action_type": "other", "safety_flags": [], "src": 1}]})
    result = dec.decompose("젖은 손으로 콘센트를 만지지 마세요.", {})
    assert [s.sentence for s in result.steps] == ["젖은 손으로 콘센트를 만지면 안 돼요."]


def test_flipped_prohibition_still_falls_back_to_rules(monkeypatch):
    """금지를 뒤집은 응답('만져요')은 지금처럼 버린다 — 근로자가 반대로 듣지 않게."""
    _gpt(monkeypatch, {
        "task_title": "t", "job": "cafe",
        "steps": [{"sentence": "젖은 손으로 콘센트를 만져요.", "symbol_query": ["콘센트를 만지다"],
                   "action_type": "other", "safety_flags": [], "src": 1}]})
    result = dec.decompose("젖은 손으로 콘센트를 만지지 마세요.", {})
    assert all("만지지" in s.sentence or "안 돼" in s.sentence for s in result.steps)


# ---------- 개발 정답셋(eval/dataset.json acc3a_*) 정확도 검사 ----------

def _case(cid):
    from eval import run_eval
    data = json.loads(run_eval.DATASET_PATH.read_text(encoding="utf-8"))
    return next(c for c in data["cases"] if c["id"] == cid)


def test_dataset_has_3a_accuracy_cases():
    from eval import run_eval
    data = json.loads(run_eval.DATASET_PATH.read_text(encoding="utf-8"))
    acc = [c for c in data["cases"] if c["id"].startswith("acc3a_")]
    assert len(acc) == 11
    assert sum(1 for c in acc if c["expect"].get("keep_in_sentence")) >= 4
    assert sum(1 for c in acc if c["expect"].get("keep_negation")) >= 3
    assert sum(1 for c in acc if c["expect"]["min_steps"] == 2) >= 3     # 두 동작 문장
    assert sum(1 for c in acc if c["raw_input"].rstrip(".").endswith("요")
               and not c["raw_input"].rstrip(".").endswith("세요")) >= 6  # '~어요' 원문


def test_accuracy_checks_pass_for_rule_following_gpt(monkeypatch):
    from eval import run_eval
    case = _case("acc3a_tool_two_actions")
    _gpt(monkeypatch, {"task_title": "복도 닦기와 쓰레기통 비우기", "job": "cleaning", "steps": [
        {"sentence": "걸레로 복도를 닦아요.", "symbol_query": ["걸레로 복도를 닦다"], "action_type": "clean", "src": 1},
        {"sentence": "쓰레기통을 비워요.", "symbol_query": ["쓰레기통을 비우다"], "action_type": "clean", "src": 1}]})
    result = dec.decompose(case["raw_input"], case["context"])
    assert run_eval.accuracy_checks(result, case) == {"steps": True, "tone": True, "keep_words": True}


def test_accuracy_checks_catch_command_tone_dropped_tool_and_merged_actions(monkeypatch):
    from eval import run_eval
    case = _case("acc3a_tool_two_actions")
    _gpt(monkeypatch, {"task_title": "복도 청소", "job": "cleaning", "steps": [
        {"sentence": "복도를 닦으세요.", "symbol_query": ["걸레로 복도를 닦다"], "action_type": "clean", "src": 1}]})
    result = dec.decompose(case["raw_input"], case["context"])
    checks = run_eval.accuracy_checks(result, case)
    assert checks["keep_words"] is False
    # 규칙 검산(_reconcile)이 원문 한 줄로 되돌리면 말투는 사업주 것이 되지만 단계 수가 틀린다.
    assert checks["steps"] is False or checks["tone"] is False


def test_accuracy_checks_catch_flipped_negation():
    from eval import run_eval
    from schemas import DecomposeResult, Step
    case = _case("acc3a_condition_negation")
    flipped = DecomposeResult(task_title="t", job="cleaning", steps=[
        Step(order=1, sentence="바닥이 젖어 있으면 뛰어요.", keywords=[], action_type="other")])
    assert run_eval.accuracy_checks(flipped, case)["negation"] is False
    kept = DecomposeResult(task_title="t", job="cleaning", steps=[
        Step(order=1, sentence="바닥이 젖어 있으면 뛰면 안 돼요.", keywords=[], action_type="other")])
    assert run_eval.accuracy_checks(kept, case) == {"steps": True, "tone": True, "keep_words": True, "negation": True}


# ---------- 깨진 불규칙 활용 고치기(run2 '영수증을 줍어요.') ----------

import pytest  # noqa: E402

import step_split  # noqa: E402


@pytest.mark.parametrize("broken,fixed", [
    ("영수증을 줍어요.", "영수증을 주워요."),
    ("동료를 돕아요.", "동료를 도와요."),
    ("매트에 눕어요.", "매트에 누워요."),
    ("물을 주전자에 붓어요.", "물을 주전자에 부어요."),
    ("소스를 젓어요.", "소스를 저어요."),
    ("자로 선을 긋어요.", "자로 선을 그어요."),
    ("호스를 잇어요.", "호스를 이어요."),
    ("상자를 수레에 싣어요.", "상자를 수레에 실어요."),
    ("안내 방송을 듣어요.", "안내 방송을 들어요."),
    ("영수증을 줍었어요.", "영수증을 주웠어요."),
    ("영수증을 줍으세요.", "영수증을 주우세요."),
    ("떨어지면 줍으면 돼요.", "떨어지면 주우면 돼요."),
    ("영수증 줍어서 버리기", "영수증 주워서 버리기"),
])
def test_fix_irregular_fixes_unambiguous_stems(broken, fixed):
    assert step_split.broken_irregular(broken)
    assert step_split.fix_irregular(broken) == fixed
    assert step_split.fix_irregular(fixed) == fixed and not step_split.broken_irregular(fixed)


@pytest.mark.parametrize("text", [
    "소매를 걷어요.", "길을 걸어요.", "장갑에 흙이 묻어요.", "길을 물어요.", "빵을 굽어요.", "고기를 구워요.",
    "손을 씻어요.", "앞치마를 벗어요.", "물건이 있어요.", "잇몸", "붓으로 칠해요.", "붓이 젖었어요.", "듣는 사람", "듣기 연습", "줍다",
    "영수증을 주워요.", "물을 부어요.",
])
def test_fix_irregular_leaves_regular_and_ambiguous_words(text):
    assert step_split.fix_irregular(text) == text
    assert step_split.broken_irregular(text) == []


def test_decompose_fixes_broken_irregular_in_gpt_sentence_and_title(monkeypatch):
    _gpt(monkeypatch, {"task_title": "영수증 줍어 버리기", "job": "cleaning", "steps": [
        {"sentence": "영수증을 줍어요.", "symbol_query": ["영수증을 줍다"], "action_type": "move", "src": 1},
        {"sentence": "영수증을 버려요.", "symbol_query": ["영수증을 버리다"], "action_type": "clean", "src": 1}]})
    result = dec.decompose("바닥에 떨어진 영수증을 주워서 버려요.", {})
    assert [s.sentence for s in result.steps] == ["영수증을 주워요.", "영수증을 버려요."]
    assert result.task_title == "영수증 주워 버리기"
