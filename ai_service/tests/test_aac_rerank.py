"""GPT 재순위(aac_rerank.py) 테스트. HTTP 층(llm._http.post)만 가짜로 바꾼다 — 실제 API는 부르지 않는다."""
import json
import os
import sys
import types

import httpx
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import aac_rerank  # noqa: E402
import llm  # noqa: E402
import symbols  # noqa: E402
from schemas import Symbol  # noqa: E402

_URL = "https://api.openai.test/v1/chat/completions"


def _cand(i):
    return {"asset_id": f"A{i}", "group_id": f"G{i}", "job": "retail", "asset_type": "action",
            "label": f"카드{i}", "image_url": f"/api/aac/images/a{i}.png", "score": 0.5 - i * 0.01}


def _decision(reason="accepted", n=10):
    cands = [_cand(i) for i in range(1, n + 1)]
    return {"match": cands[0] if reason == "accepted" else None, "reason": reason, "candidates": cands,
            "margin": 0.05, "embedding": False}


class _FakeHTTP:
    """llm._http 대신 쓰는 가짜. 응답(dict) 또는 예외를 차례로 돌려주고 요청을 기록한다."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def post(self, url, headers=None, json=None, timeout=None):  # noqa: A002 - httpx 시그니처
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        reply = self.replies.pop(0) if self.replies else {"choice": 1, "confident": True}
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, int):
            return httpx.Response(reply, request=httpx.Request("POST", url))
        content = reply if isinstance(reply, str) else _json_dumps(reply)
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]},
                              request=httpx.Request("POST", url))


def _json_dumps(d):
    return json.dumps(d, ensure_ascii=False)


@pytest.fixture
def gpt(monkeypatch):
    """키가 있고 재순위가 켜진 상태. 반환한 함수로 가짜 응답을 설치한다."""
    monkeypatch.setenv("AAC_LLM_RERANK", "auto")
    monkeypatch.delenv("AAC_LLM_RERANK_POLICY", raising=False)
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "sk-test")
    aac_rerank.reset_state()

    def install(*replies):
        fake = _FakeHTTP(*replies)
        monkeypatch.setattr(llm, "_http", types.SimpleNamespace(post=fake.post))
        return fake

    yield install
    aac_rerank.reset_state()


# ---------- 정책 ----------

def test_top1_accepts_when_confident_and_same_as_rule_first():
    d = _decision(reason="low_margin")
    out = aac_rerank.apply_policy(d, 1, True)
    assert out["reason"] == "accepted"
    assert out["match"]["asset_id"] == "A1"
    assert out["decided_by"] == "llm"
    assert d["match"] is None  # 원래 판정은 바꾸지 않는다


def test_top1_vetoes_rule_accept_when_gpt_picks_other_card():
    out = aac_rerank.apply_policy(_decision("accepted"), 2, True)
    assert out["match"] is None
    assert out["reason"] == "llm_disagree"
    # GPT가 고른 카드가 보여 줄 후보 맨 앞으로 온다
    assert [c["asset_id"] for c in out["candidates"][:3]] == ["A2", "A1", "A3"]


def test_top1_not_confident_hands_off_and_keeps_rule_reason():
    out = aac_rerank.apply_policy(_decision("frame_mismatch"), 1, False)
    assert out["match"] is None
    assert out["reason"] == "frame_mismatch"
    assert out["candidates"][0]["asset_id"] == "A1"


def test_choice_zero_hands_off_without_reordering():
    out = aac_rerank.apply_policy(_decision("accepted"), 0, True)
    assert out["match"] is None
    assert out["reason"] == "llm_disagree"
    assert [c["asset_id"] for c in out["candidates"]] == [f"A{i}" for i in range(1, 11)]


def test_pick_outside_shortlist_is_not_moved_forward():
    out = aac_rerank.apply_policy(_decision("low_score"), 5, True)
    assert out["match"] is None
    assert out["reason"] == "low_score"
    assert [c["asset_id"] for c in out["candidates"][:3]] == ["A1", "A2", "A3"]


def test_top3_policy_accepts_confident_pick_within_top3():
    out = aac_rerank.apply_policy(_decision("low_margin"), 3, True, "top3")
    assert out["reason"] == "accepted"
    assert out["match"]["asset_id"] == "A3"
    assert out["candidates"][0]["asset_id"] == "A3"
    out = aac_rerank.apply_policy(_decision("low_margin"), 4, True, "top3")
    assert out["match"] is None


@pytest.mark.parametrize("raw,n,expected", [
    ({"choice": 2, "confident": True}, 10, (2, True)),
    ({"choice": "3", "confident": "true"}, 10, (3, True)),
    ({"choice": 0, "confident": True}, 10, (0, True)),
    ({"choice": 1}, 10, (1, False)),
    ({"choice": 1, "confident": "yes"}, 10, (1, False)),
    ({"choice": 2.0, "confident": True}, 10, (2, True)),
])
def test_parse_verdict_accepts_valid_answers(raw, n, expected):
    assert aac_rerank.parse_verdict(raw, n) == expected


@pytest.mark.parametrize("raw", [{"choice": 11, "confident": True}, {"choice": -1}, {"confident": True},
                                 {"choice": True}, {"choice": "two"}, [],
                                 {"choice": 1.7, "confident": True}, {"choice": float("inf")},
                                 {"choice": float("nan")}, {"choice": "1.5"}])
def test_parse_verdict_rejects_bad_answers(raw):
    with pytest.raises(ValueError):
        aac_rerank.parse_verdict(raw, 10)


def test_policy_env_falls_back_to_top1(monkeypatch):
    monkeypatch.setenv("AAC_LLM_RERANK_POLICY", "weird")
    assert aac_rerank.policy() == "top1"
    monkeypatch.setenv("AAC_LLM_RERANK_POLICY", "TOP3")
    assert aac_rerank.policy() == "top3"


# ---------- 호출·폴백 ----------

def test_rerank_sends_numbered_labels_with_short_timeout(gpt):
    fake = gpt({"choice": 1, "confident": True})
    out = aac_rerank.rerank(_decision("low_margin"), keywords=["상품 놓기"],
                            context={"sentence": "상품을 선반에 놓으세요", "business_type": "마트"})
    assert out["decided_by"] == "llm" and out["reason"] == "accepted"
    call = fake.calls[0]
    assert call["timeout"] == 4.0
    assert call["json"]["max_tokens"] == aac_rerank.MAX_TOKENS
    user = call["json"]["messages"][1]["content"]
    assert user.startswith("지시문: 상품을 선반에 놓으세요\n업종: 마트\n후보:\n1. 카드1\n")
    assert "10. 카드10" in user
    assert call["json"]["messages"][0]["content"] == aac_rerank.RERANK_SYSTEM


def test_timeout_falls_back_to_rule_and_cools_down(gpt):
    fake = gpt(httpx.ReadTimeout("slow"))
    d = _decision("accepted")
    out = aac_rerank.rerank(d, keywords=["k"], context={"sentence": "문장"})
    assert out["decided_by"] == "rule"
    assert out["match"] == d["match"] and out["reason"] == "accepted" and out["candidates"] == d["candidates"]
    # 쉬는 동안은 부르지 않는다
    assert aac_rerank.available() is False
    aac_rerank.rerank(_decision("accepted"), keywords=["k2"], context={"sentence": "다른 문장"})
    assert len(fake.calls) == 1


def test_http_error_falls_back_to_rule(gpt):
    gpt(429)
    out = aac_rerank.rerank(_decision("low_margin"), keywords=["k"], context={"sentence": "문장"})
    assert out["decided_by"] == "rule" and out["match"] is None and out["reason"] == "low_margin"


def test_malformed_answer_falls_back_without_cooldown(gpt):
    fake = gpt("not json", {"choice": 42, "confident": True}, {"choice": 1, "confident": True})
    for sentence in ("문장1", "문장2"):
        out = aac_rerank.rerank(_decision("low_margin"), keywords=["k"], context={"sentence": sentence})
        assert out["decided_by"] == "rule"
    assert aac_rerank.available() is True
    out = aac_rerank.rerank(_decision("low_margin"), keywords=["k"], context={"sentence": "문장3"})
    assert out["decided_by"] == "llm"
    assert len(fake.calls) == 3


def test_repeated_malformed_answers_cool_down(gpt):
    """이상한 응답이 연달아 오면 단계마다 돈을 내지 않도록 쉰다."""
    fake = gpt(*(["not json"] * aac_rerank._BAD_STREAK_LIMIT), {"choice": 1, "confident": True})
    for i in range(aac_rerank._BAD_STREAK_LIMIT + 5):
        out = aac_rerank.rerank(_decision("low_margin"), keywords=["k"], context={"sentence": f"문장{i}"})
        assert out["decided_by"] == "rule"
    assert len(fake.calls) == aac_rerank._BAD_STREAK_LIMIT
    assert aac_rerank.available() is False


def test_good_answer_resets_malformed_streak(gpt):
    fake = gpt("not json", "not json", {"choice": 1, "confident": True}, "not json", "not json",
               {"choice": 1, "confident": True})
    for i in range(6):
        aac_rerank.rerank(_decision("low_margin"), keywords=["k"], context={"sentence": f"문장{i}"})
    assert len(fake.calls) == 6 and aac_rerank.available() is True


def test_total_deadline_caps_a_slow_trickling_call(gpt, monkeypatch):
    """httpx timeout은 단계별이라, 전체 마감은 aac_rerank가 따로 지킨다."""
    import time as _time
    monkeypatch.setenv("AAC_LLM_RERANK_TIMEOUT", "0.2")
    calls = []

    def slow_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        calls.append(timeout)
        _time.sleep(1.0)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"choice": 1, "confident": true}'}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(llm, "_http", types.SimpleNamespace(post=slow_post))
    d = _decision("accepted")
    started = _time.monotonic()
    out = aac_rerank.rerank(d, keywords=["k"], context={"sentence": "문장"})
    assert _time.monotonic() - started < 0.8
    assert out["decided_by"] == "rule" and out["match"] == d["match"]
    assert calls == [0.2]
    assert aac_rerank.available() is False


def test_no_key_never_calls(gpt, monkeypatch):
    fake = gpt({"choice": 1, "confident": True})
    monkeypatch.setattr(llm, "OPENAI_API_KEY", "")
    out = aac_rerank.rerank(_decision("accepted"), keywords=["k"], context={"sentence": "문장"})
    assert out["decided_by"] == "rule" and fake.calls == []


def test_off_setting_never_calls(gpt, monkeypatch):
    fake = gpt({"choice": 1, "confident": True})
    monkeypatch.setenv("AAC_LLM_RERANK", "off")
    out = aac_rerank.rerank(_decision("accepted"), keywords=["k"], context={"sentence": "문장"})
    assert out["decided_by"] == "rule" and fake.calls == []


def test_no_candidates_never_calls(gpt):
    fake = gpt({"choice": 1, "confident": True})
    out = aac_rerank.rerank(_decision("no_candidate", n=0), keywords=["k"], context={"sentence": "문장"})
    assert out["decided_by"] == "rule" and fake.calls == []


def test_same_step_is_asked_once(gpt):
    fake = gpt({"choice": 2, "confident": True})
    ctx = {"sentence": "문장", "business_type": "마트"}
    first = aac_rerank.rerank(_decision("accepted"), keywords=["k"], context=ctx)
    second = aac_rerank.rerank(_decision("accepted"), keywords=["k"], context=ctx)
    assert first == second
    assert len(fake.calls) == 1
    # 후보가 달라지면 다시 묻는다
    aac_rerank.rerank(_decision("accepted", n=9), keywords=["k"], context=ctx)
    assert len(fake.calls) == 2


def test_cache_is_bounded(gpt, monkeypatch):
    monkeypatch.setenv("AAC_LLM_RERANK_CACHE", "2")
    fake = gpt()
    for s in ("a", "b", "c", "a"):
        aac_rerank.rerank(_decision("accepted"), keywords=["k"], context={"sentence": s})
    assert len(fake.calls) == 4  # a는 c가 들어오며 밀려났다


# ---------- map_symbols 응답 모양 ----------

_STEP = (["상품", "선반", "놓기"], {"business_type": "대형마트", "sentence": "상품을 선반에 놓으세요",
                                  "action_type": "move"})


def test_map_symbols_rule_only_by_default():
    # conftest가 AAC_LLM_RERANK=off로 둔다 — 규칙만, 예전 응답과 같다.
    s = symbols.map_symbols(*_STEP).symbols[0]
    assert s.external_id == "RETAIL_029" and s.reason == "accepted" and s.decided_by == "rule"


def test_map_symbols_llm_confirms_rule_first(gpt):
    fake = gpt({"choice": 1, "confident": True})
    s = symbols.map_symbols(*_STEP).symbols[0]
    assert s.external_id == "RETAIL_029" and s.reason == "accepted" and s.decided_by == "llm"
    assert s.needs_fallback is False and s.candidates == []
    assert "1. " in fake.calls[0]["json"]["messages"][1]["content"]


def test_map_symbols_llm_disagreement_becomes_low_margin_shortlist(gpt):
    gpt({"choice": 2, "confident": True})
    s = symbols.map_symbols(*_STEP).symbols[0]
    assert s.needs_fallback is True and s.image_url is None
    assert s.reason == "low_margin"  # 바깥 계약의 reason 값은 늘리지 않는다
    assert s.decided_by == "llm"
    assert len(s.candidates) == 3
    assert s.candidates[1].asset_id == "RETAIL_029"  # 규칙 1순위는 GPT가 고른 카드 다음


def test_map_symbols_falls_back_on_error(gpt):
    gpt(httpx.ConnectError("down"))
    s = symbols.map_symbols(*_STEP).symbols[0]
    assert s.external_id == "RETAIL_029" and s.reason == "accepted" and s.decided_by == "rule"


def test_symbol_without_decided_by_is_backward_compatible():
    s = Symbol(keyword="k")
    assert s.decided_by == "rule"
    assert "decided_by" in s.model_dump()
