"""LLM 경로 테스트.

OpenAI 호출(chat_json)만 목으로 대체하고, 프롬프트→JSON 파싱→스키마 검증→
폴백까지 실제 코드를 실행한다. 실 네트워크/실 키 없이 동작을 보장한다.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import llm  # noqa: E402
import decompose as dec  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
import main as ai_main  # noqa: E402


# ---------- 1) 맥락적응 분해 ----------
def test_llm_decompose_builds_validated_steps(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {
        "task_title": "택배 분류",
        "steps": [
            {"sentence": "상자를 크기별로 나누세요.", "symbol_query": ["box", "size"],
             "action_type": "sort", "safety_flags": []},
            {"sentence": "큰 상자를 옮기세요.", "symbol_query": ["box"],
             "action_type": "move", "safety_flags": ["무거운 물건 주의"]},
        ],
    })
    result = dec.decompose("택배를 크기별로 나누고 큰 건 옮겨주세요", {"business_type": "물류"})
    assert result.task_title == "택배 분류"
    assert [s.order for s in result.steps] == [1, 2]
    assert result.steps[0].symbol_query == ["box", "size"]
    assert result.steps[0].action_type == "sort"
    assert result.steps[1].safety_flags == ["무거운 물건 주의"]


def test_llm_invalid_action_normalized(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {
        "task_title": "x", "steps": [{"sentence": "확인하세요.", "action_type": "WEIRD"}],
    })
    result = dec.decompose("확인", {})
    assert result.steps[0].action_type == "other"  # 잘못된 값 → 정규화


def test_llm_empty_steps_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {"steps": []})
    # 규칙 기반 폴백 → 나열 쉼표는 1단계로 유지(규칙 엔진 동작 확인)
    result = dec.decompose("사과, 배, 귤을 담으세요.", {})
    assert len(result.steps) == 1


def test_llm_exception_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    def boom(*a, **k):
        raise RuntimeError("openai 500")
    monkeypatch.setattr(llm, "chat_json", boom)
    result = dec.decompose("상자를 옮기고, 수량을 확인하세요.", {})
    assert len(result.steps) >= 1  # 폴백으로도 분해됨


def test_no_key_uses_rule_engine(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: False)
    result = dec.decompose("상자를 분류하고, 선반에 올리세요.", {})
    assert len(result.steps) == 2  # 규칙 기반 동사 '~고,' 분할


# ---------- 2) 사업주 코칭 ----------
def test_coaching_rule_fallback_flags_difficult_steps(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: False)
    client = TestClient(ai_main.app)
    r = client.post("/ai/coaching", json={
        "task_title": "분류 작업",
        "steps": [
            {"order": 1, "sentence": "상자를 옮기세요", "completed": True,
             "stuck": False, "replay_count": 0, "duration_sec": 10},
            {"order": 2, "sentence": "수량을 확인하세요", "completed": True,
             "stuck": True, "replay_count": 5, "duration_sec": 30},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    orders = [s["order"] for s in body["suggestions"]]
    assert orders == [2]  # 어려움 징후 있는 단계만


def test_coaching_via_llm(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {
        "summary": "2단계 개선 권장",
        "suggestions": [{"order": 2, "issue": "문장이 어려움",
                         "suggestion": "더 쉽게 바꾸세요", "action": "rephrase"}],
    })
    client = TestClient(ai_main.app)
    r = client.post("/ai/coaching", json={"task_title": "t", "steps": [
        {"order": 2, "sentence": "수량을 확인하세요", "stuck": True,
         "replay_count": 1, "duration_sec": 5}]})
    assert r.status_code == 200
    assert r.json()["suggestions"][0]["action"] == "rephrase"


def test_coaching_backfills_stuck_steps_the_llm_omitted(monkeypatch):
    """막힘 신호가 있는 단계는 LLM 응답에 없어도 서버가 채워 넣어야 한다."""
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    # LLM이 3단계(막힘)를 통째로 빠뜨리고 1단계(정상)만 답한 상황을 흉내낸다.
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {
        "summary": "1단계 확인",
        "suggestions": [{"order": 1, "issue": "가벼운 지연", "suggestion": "괜찮아요", "action": "ok"}],
    })
    client = TestClient(ai_main.app)
    r = client.post("/ai/coaching", json={"task_title": "t", "steps": [
        {"order": 1, "sentence": "상자를 옮기세요", "stuck": False, "replay_count": 0, "duration_sec": 5},
        {"order": 3, "sentence": "부품을 조립하세요", "action_type": "assemble",
         "stuck": True, "replay_count": 0, "duration_sec": 10},
    ]})
    assert r.status_code == 200
    orders = sorted(s["order"] for s in r.json()["suggestions"])
    assert orders == [1, 3]  # LLM이 준 1단계 + 서버가 보강한 3단계
    backfilled = next(s for s in r.json()["suggestions"] if s["order"] == 3)
    assert backfilled["action"] == "split"  # action_type=assemble 휴리스틱


def test_coaching_llm_response_already_covers_all_stuck_steps(monkeypatch):
    """LLM이 이미 다 다뤘으면 보강이 끼어들어 내용을 바꾸지 않는다."""
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {
        "summary": "요약",
        "suggestions": [{"order": 1, "issue": "LLM이 준 사유", "suggestion": "LLM이 준 조치", "action": "photo"}],
    })
    client = TestClient(ai_main.app)
    r = client.post("/ai/coaching", json={"task_title": "t", "steps": [
        {"order": 1, "sentence": "x", "stuck": True, "replay_count": 0, "duration_sec": 5},
    ]})
    body = r.json()
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0] == {"order": 1, "issue": "LLM이 준 사유",
                                      "suggestion": "LLM이 준 조치", "action": "photo"}


# ---------- chat_json: OpenAI 응답 파싱부 직접 검증 ----------
def test_chat_json_parses_openai_wire_format(monkeypatch):
    import types

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"task_title":"t","steps":[]}'}}]}

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["model"] = json["model"]
        captured["json_mode"] = json["response_format"]["type"]
        captured["auth"] = headers["Authorization"]
        return _Resp()

    monkeypatch.setattr(llm, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm, "_http", types.SimpleNamespace(post=fake_post))

    out = llm.chat_json("sys", "usr")
    assert out == {"task_title": "t", "steps": []}
    assert captured["url"].endswith("/chat/completions")
    assert captured["json_mode"] == "json_object"
    assert captured["auth"].startswith("Bearer ")


# ---------- 금지·부정 보존 ----------
def test_llm_decompose_dropping_prohibition_falls_back_to_rules(monkeypatch):
    """'만지지 말고 ~ 부르세요'에서 금지가 사라진 GPT 결과는 버리고 규칙 분해로 간다."""
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {
        "task_title": "x", "steps": [{"sentence": "담당 선생님을 부르세요.", "action_type": "other"}],
    })
    src = "빨간 상자는 만지지 말고 담당 선생님을 부르세요."
    result = dec.decompose(src, {})
    assert any("만지지" in s.sentence for s in result.steps)


def test_llm_decompose_keeps_result_when_prohibition_survives(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {
        "task_title": "x", "steps": [{"sentence": "빨간 상자는 만지지 마세요.", "action_type": "other"},
                                     {"sentence": "담당 선생님을 부르세요.", "action_type": "other"}],
    })
    result = dec.decompose("빨간 상자는 만지지 말고 담당 선생님을 부르세요.", {})
    # 금지 문장은 버리지 않는다(부정 검사 통과). 다만 입력 화면 나누기 검산(_reconcile)이 '만지지 말고 부르다'를
    # 시킬 일 하나(부르기)로 보아 원문 한 단계로 합친다 — 분할 정답셋 dev_cleaning_14도 1단계다.
    assert [s.sentence for s in result.steps] == ["빨간 상자는 만지지 말고 담당 선생님을 부르세요."]


def test_llm_decompose_invented_prohibition_falls_back_to_rules(monkeypatch):
    """원문에 없는 '~지 마세요'를 덧붙인 결과(앞 단계와 반대 지시)는 버린다."""
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "chat_json", lambda system, user, **kw: {
        "task_title": "x", "steps": [{"sentence": "수저를 수저통에 넣으세요.", "action_type": "other"},
                                     {"sentence": "수저통에 넣지 마세요.", "action_type": "other"}],
    })
    result = dec.decompose("수저를 모아서 수저통에 넣으세요.", {})
    assert not any("마세요" in s.sentence for s in result.steps)


def test_check_negation_markers():
    llm.check_negation("넘치지 않게 부으세요.", {"steps": [{"sentence": "넘치지 않게 부으세요."}]})
    llm.check_negation("컵을 놓으세요.", {"steps": [{"sentence": "컵을 놓으세요."}]})
    with pytest.raises(ValueError):
        llm.check_negation("뛰지 마세요.", {"steps": [{"sentence": "걸으세요."}]})


@pytest.mark.parametrize("src, steps", [
    # '~면 안 됩니다'가 사라짐(예전 표지 목록은 '하면 안'만 알아서 놓쳤다)
    ("뜨거운 냄비는 맨손으로 만지면 안 됩니다. 장갑을 끼세요.", ["장갑을 끼세요."]),
    ("넣으면 안 돼요. 옆 칸에 두세요.", ["옆 칸에 두세요."]),
    # 짧은 부정 '안 만져요'
    ("젖은 손으로 콘센트를 안 만져요. 손을 닦으세요.", ["손을 닦으세요."]),
    # 금지가 다른 동작으로 옮겨 감
    ("문을 닫지 말고 열어 두세요. 그리고 바닥을 닦으세요.", ["문을 열어 두세요.", "바닥을 닦지 마세요."]),
    # '~ 금지'가 사라짐
    ("엘리베이터 사용 금지. 계단으로 박스를 옮기세요.", ["계단으로 박스를 옮기세요."]),
    # 원문에 없는 금지
    ("수저를 수저통에 넣으세요.", ["수저를 수저통에 넣으세요.", "수저통에 넣지 마세요."]),
])
def test_check_negation_rejects(src, steps):
    with pytest.raises(ValueError):
        llm.check_negation(src, {"steps": [{"sentence": s} for s in steps]})


@pytest.mark.parametrize("src, steps", [
    # 같은 금지를 다른 말로(예전 검사는 '원문에 없는 금지'로 잘못 버렸다)
    ("뜨거운 냄비는 맨손으로 만지면 안 됩니다.", ["뜨거운 냄비를 만지지 마세요."]),
    ("손대면 안 됩니다. 선생님을 부르세요.", ["손대지 마세요.", "선생님을 부르세요."]),
    ("만져서는 안 됩니다.", ["만지지 마세요."]),
    ("손님 음식에 손가락이 닿으면 안 돼요.", ["손가락이 닿지 않게 하세요."]),
    ("엘리베이터 사용 금지. 계단으로 옮기세요.", ["엘리베이터를 사용하지 마세요.", "계단으로 옮기세요."]),
    # '지마'·'안'이 들어가도 금지가 아닌 말(예전 검사는 '가지마다'를 금지로 셌다)
    ("가지마다 물을 주세요.", ["가지에 물을 주세요."]),
    ("엄지마디를 굽히세요.", ["엄지마디를 굽히세요."]),
    ("마지막으로 불을 끄세요.", ["불을 끄세요."]),
    ("상자 안에 컵을 넣으세요.", ["상자 안에 컵을 넣으세요."]),
    ("상자 안 물건을 꺼내세요.", ["상자 안 물건을 꺼내세요."]),
])
def test_check_negation_accepts(src, steps):
    llm.check_negation(src, {"steps": [{"sentence": s} for s in steps]})


def test_negation_keys_name_the_forbidden_action():
    assert llm.negation_keys("만지지 마세요") == ["만지"]
    assert llm.negation_keys("넣으면 안 됩니다") == ["넣"]
    assert llm.negation_keys("출입금지") == ["출입"]
    assert llm.negation_keys("가지마다 물을 주세요") == []


def test_negation_set_replay_matches_human_verdicts():
    """eval/negation_set.json: 실제 GPT 분해 응답 22건(금지 문장 20 + 대조 2)을 사람 판정과 맞춘다.
    실제 API는 부르지 않는다 — 저장된 응답을 다시 검사할 뿐이다."""
    import json
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval", "negation_set.json")
    with open(path, encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    wrong = []
    for c in cases:
        try:
            llm.check_negation(c["sentence"], {"steps": [{"sentence": s} for s in c["gpt_steps"]]})
            got = "pass"
        except ValueError:
            got = "reject"
        if got != c["expect"]:
            wrong.append(c["id"])
    assert wrong == []
