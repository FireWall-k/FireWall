"""LLM 경로 테스트.

OpenAI 호출(chat_json)만 목으로 대체하고, 프롬프트→JSON 파싱→스키마 검증→
폴백까지 실제 코드를 실행한다. 실 네트워크/실 키 없이 동작을 보장한다.
"""
import os
import sys

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
    monkeypatch.setattr(llm.httpx, "post", fake_post)

    out = llm.chat_json("sys", "usr")
    assert out == {"task_title": "t", "steps": []}
    assert captured["url"].endswith("/chat/completions")
    assert captured["json_mode"] == "json_object"
    assert captured["auth"].startswith("Bearer ")
