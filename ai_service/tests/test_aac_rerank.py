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
    monkeypatch.setenv("AAC_LLM_RERANK_POLICY", " top3q ")
    assert aac_rerank.policy() == "top3q"
    monkeypatch.delenv("AAC_LLM_RERANK_POLICY")
    assert aac_rerank.policy() == "top1"  # 코드 기본(Docker 기본은 docker-compose.yml의 top3q)


# ---------- top3q: 그림 검색어를 함께 보낸 단계만 top3 ----------

def test_top3q_with_query_accepts_confident_pick_within_top3():
    out = aac_rerank.apply_policy(_decision("accepted"), 3, True, "top3q", with_query=True)
    assert out["reason"] == "accepted" and out["match"]["asset_id"] == "A3"
    assert out["llm"]["applied"] == "top3" and out["llm"]["query"] is True
    # 상위 3장 밖은 top3처럼 받지 않는다
    out = aac_rerank.apply_policy(_decision("low_margin"), 4, True, "top3q", with_query=True)
    assert out["match"] is None
    # 확신 없으면 받지 않는다
    out = aac_rerank.apply_policy(_decision("low_margin"), 2, False, "top3q", with_query=True)
    assert out["match"] is None


def test_top3q_without_query_behaves_like_top1():
    for choice, confident in ((2, True), (3, True), (1, True), (1, False), (0, True)):
        for reason in ("accepted", "low_margin"):
            q = aac_rerank.apply_policy(_decision(reason), choice, confident, "top3q", with_query=False)
            t1 = aac_rerank.apply_policy(_decision(reason), choice, confident, "top1")
            assert (q["match"], q["reason"], q["candidates"]) == (t1["match"], t1["reason"], t1["candidates"])
            assert q["llm"]["applied"] == "top1"


@pytest.mark.parametrize("sentence,keywords,expected", [
    ("상자를 여세요.", ["커터칼로 상자를 열다"], "커터칼로 상자를 열다"),
    ("제품의 앞면을 정리하세요.", ["제품의 앞면을 같은 방향으로 정리하다"], "제품의 앞면을 같은 방향으로 정리하다"),
    ("손을 씻으세요.", ["손을 씻다"], "손을 씻다"),  # 어미가 달라 문장 안에 그대로 없다 → 보낸다
    ("볼펜 몸통에 심을 넣으세요.", ["볼펜", "심 넣기"], "볼펜 / 심 넣기"),
    # 백엔드가 문장 낱말을 뽑은 검색어(사업주가 고친 줄)·문장 앞부분 — 새 정보가 없어 보내지 않는다
    ("제품의 앞면을 정리해요.", ["제품의", "앞면을", "정리해요"], ""),
    ("상자를 지정된 위치에 놓으세요.", ["상자를 지정된 위"], ""),
    ("문장", [], ""),
    ("문장", ["  ", ""], ""),
])
def test_search_phrase(sentence, keywords, expected):
    assert aac_rerank.search_phrase(sentence, keywords) == expected


def test_prompt_without_new_query_keeps_old_shape():
    user = aac_rerank.build_user_prompt("상품을 선반에 놓으세요", "마트", [_cand(1)], ["상품을", "선반에"])
    assert user == "지시문: 상품을 선반에 놓으세요\n업종: 마트\n후보:\n1. 카드1"


def test_rerank_sends_search_phrase_and_applies_top3q(gpt, monkeypatch):
    monkeypatch.setenv("AAC_LLM_RERANK_POLICY", "top3q")
    fake = gpt({"choice": 2, "confident": True}, {"choice": 2, "confident": True})
    out = aac_rerank.rerank(_decision("accepted"), keywords=["커터칼로 상자를 열다"],
                            context={"sentence": "상자를 여세요."})
    assert "그림 검색어: 커터칼로 상자를 열다\n" in fake.calls[0]["json"]["messages"][1]["content"]
    assert out["reason"] == "accepted" and out["match"]["asset_id"] == "A2"
    # 검색어가 문장 낱말뿐이면 보내지 않고 top1로 판정한다(2번을 골랐으니 사람에게 넘긴다)
    out = aac_rerank.rerank(_decision("accepted"), keywords=["상자를", "여세요"], context={"sentence": "상자를 여세요."})
    assert "그림 검색어" not in fake.calls[1]["json"]["messages"][1]["content"]
    assert out["match"] is None and out["reason"] == "llm_disagree"
    assert out["candidates"][0]["asset_id"] == "A2"


def test_system_prompt_mentions_search_phrase():
    # 프롬프트가 바뀌면 판정 파일 키도 바뀐다 — 검색어 없이 받은 예전 판정을 다시 쓰지 않는다.
    assert "picture search phrase" in aac_rerank.RERANK_SYSTEM
    key = ("문장", ("k",), "", ("A1",))
    assert aac_rerank._db_key(key) != aac_rerank._db_key(("문장", ("k2",), "", ("A1",)))


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
    assert user.startswith("지시문: 상품을 선반에 놓으세요\n그림 검색어: 상품 놓기\n업종: 마트\n후보:\n1. 카드1\n")
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


# ---------- 동시 호출(백엔드는 직무 하나에 단계 8개를 동시에 준비한다) ----------

def _slow_reply(delay, record=None):
    import threading as _th
    import time as _time
    lock = _th.Lock()

    def post(url, headers=None, json=None, timeout=None):  # noqa: A002
        if record is not None:
            with lock:
                record.append(timeout)
        _time.sleep(delay)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"choice": 1, "confident": true}'}}]},
                              request=httpx.Request("POST", url))
    return post


@pytest.mark.parametrize("parallel", [8, 16])
def test_parallel_steps_below_deadline_all_use_gpt_without_cooldown(gpt, monkeypatch, parallel):
    """한 번 호출이 마감보다 짧으면, 동시에 8·16단계가 와도 모두 GPT로 정하고 쉬는 시간이 걸리지 않는다.
    (예전 작업 스레드 4개 + 제출 시점부터 센 마감에서는 5번째부터 줄에서 기다린 시간 때문에 거짓 시간 초과가 났다.)"""
    from concurrent.futures import ThreadPoolExecutor as _Pool
    monkeypatch.setenv("AAC_LLM_RERANK_TIMEOUT", "1.0")
    calls = []
    monkeypatch.setattr(llm, "_http", types.SimpleNamespace(post=_slow_reply(0.6, calls)))
    with _Pool(max_workers=parallel) as ex:
        outs = list(ex.map(lambda i: aac_rerank.rerank(_decision("accepted"), keywords=["k"],
                                                       context={"sentence": f"문장{i}"}), range(parallel)))
    assert [o["decided_by"] for o in outs] == ["llm"] * parallel
    assert len(calls) == parallel
    assert aac_rerank.available() is True


def test_deadline_counts_from_call_start_not_from_queueing(gpt, monkeypatch):
    """작업 스레드가 하나뿐이라 두 번째 호출이 줄에서 기다려도, 기다린 시간은 마감에 넣지 않는다."""
    from concurrent.futures import ThreadPoolExecutor as _Pool
    monkeypatch.setattr(aac_rerank, "_pool", _Pool(max_workers=1))
    monkeypatch.setenv("AAC_LLM_RERANK_TIMEOUT", "1.0")
    monkeypatch.setattr(llm, "_http", types.SimpleNamespace(post=_slow_reply(0.6)))
    with _Pool(max_workers=2) as ex:
        outs = list(ex.map(lambda i: aac_rerank.rerank(_decision("accepted"), keywords=["k"],
                                                       context={"sentence": f"문장{i}"}), range(2)))
    # 두 번째는 0.6초 기다린 뒤 시작해 0.6초 걸린다 — 제출부터 1.2초지만 호출 자체는 마감(1초) 안이다.
    assert [o["decided_by"] for o in outs] == ["llm", "llm"]
    assert aac_rerank.available() is True


def test_queued_call_that_never_started_does_not_cool_down(gpt, monkeypatch):
    """마감 안에 빈 작업 스레드를 못 얻으면 요청 없이 규칙 판정으로 가고, 쉬는 시간은 걸지 않는다."""
    import threading as _th
    from concurrent.futures import ThreadPoolExecutor as _Pool
    monkeypatch.setattr(aac_rerank, "_pool", _Pool(max_workers=1))
    entered, release = _th.Event(), _th.Event()
    sent = []

    def blocking_post(url, headers=None, json=None, timeout=None):  # noqa: A002
        sent.append(1)
        entered.set()
        release.wait(5)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"choice": 1, "confident": true}'}}]},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(llm, "_http", types.SimpleNamespace(post=blocking_post))
    monkeypatch.setenv("AAC_LLM_RERANK_TIMEOUT", "5")
    first = {}
    t = _th.Thread(target=lambda: first.setdefault("out", aac_rerank.rerank(
        _decision("accepted"), keywords=["k"], context={"sentence": "첫 문장"})))
    t.start()
    assert entered.wait(5)
    monkeypatch.setenv("AAC_LLM_RERANK_TIMEOUT", "0.2")  # 두 번째 단계의 마감(첫 호출은 이미 5초로 읽었다)
    d = _decision("accepted")
    second = aac_rerank.rerank(d, keywords=["k"], context={"sentence": "둘째 문장"})
    assert second["decided_by"] == "rule" and second["match"] == d["match"]
    assert aac_rerank.available() is True  # 쉬는 시간이 걸리지 않았다
    release.set()
    t.join(5)
    assert first["out"]["decided_by"] == "llm"
    assert len(sent) == 1  # 줄에서 취소된 두 번째는 요청을 보내지 않았다


# ---------- 판정 파일(재시작해도 같은 단계는 다시 부르지 않는다) ----------

def test_verdict_file_survives_restart_and_stores_no_sentence(gpt, monkeypatch, tmp_path):
    import sqlite3
    db = tmp_path / "rerank.sqlite3"
    monkeypatch.setenv("AAC_LLM_RERANK_CACHE_DB", str(db))
    fake = gpt({"choice": 2, "confident": True})
    ctx = {"sentence": "비밀스러운 문장", "business_type": "마트"}
    first = aac_rerank.rerank(_decision("accepted"), keywords=["k"], context=ctx)
    aac_rerank.reset_state()  # 프로세스 재시작과 같다(메모리 캐시 비움)
    second = aac_rerank.rerank(_decision("accepted"), keywords=["k"], context=ctx)
    assert first == second and len(fake.calls) == 1
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT k, choice, confident FROM verdict").fetchall()
    conn.close()
    assert len(rows) == 1 and rows[0][1:] == (2, 1)
    assert "비밀" not in db.read_bytes().decode("utf-8", "ignore")


def test_verdict_file_error_falls_back_to_memory(gpt, monkeypatch, tmp_path):
    monkeypatch.setenv("AAC_LLM_RERANK_CACHE_DB", str(tmp_path / "no_such_dir" / "x.sqlite3"))
    fake = gpt({"choice": 1, "confident": True})
    out = aac_rerank.rerank(_decision("accepted"), keywords=["k"], context={"sentence": "문장"})
    assert out["decided_by"] == "llm" and len(fake.calls) == 1


# ---------- available()은 map_symbols에서 한 번만 본다 ----------

def test_rerank_respects_enabled_false_even_if_available(gpt):
    fake = gpt({"choice": 1, "confident": True})
    out = aac_rerank.rerank(_decision("accepted"), keywords=["k"], context={"sentence": "문장"}, enabled=False)
    assert out["decided_by"] == "rule" and fake.calls == []


def test_map_symbols_checks_availability_once(gpt, monkeypatch):
    fake = gpt({"choice": 1, "confident": True})
    seen = []
    real = aac_rerank.available

    def flip():
        seen.append(1)
        return len(seen) > 1 and real()  # 처음엔 쉬는 중, 그다음엔 쉬는 시간이 끝난 것처럼

    monkeypatch.setattr(aac_rerank, "available", flip)
    s = symbols.map_symbols(*_STEP).symbols[0]
    assert s.decided_by == "rule" and fake.calls == []
    assert len(seen) == 1


# ---------- (2b-1) 후보 조회는 유료 모델을 부르지 않는다: context.rerank=false ----------

def _count_chat_json(monkeypatch):
    calls = []
    real = llm.chat_json

    def counting(*a, **kw):
        calls.append(a)
        return real(*a, **kw)

    monkeypatch.setattr(llm, "chat_json", counting)
    return calls


def test_map_symbols_rerank_false_never_calls_gpt(gpt, monkeypatch):
    """키가 있고 재순위가 켜져 있어도(gpt) rerank=false면 chat_json 0번, 규칙 판정 그대로."""
    fake = gpt({"choice": 2, "confident": True})
    calls = _count_chat_json(monkeypatch)
    keywords, context = _STEP
    s = symbols.map_symbols(keywords, {**context, "rerank": False}).symbols[0]
    assert calls == [] and fake.calls == []
    assert s.decided_by == "rule" and s.external_id == "RETAIL_029" and s.reason == "accepted"
    # 같은 입력에서 rerank를 끄지 않으면 GPT를 부른다(위 단언이 우연이 아님).
    symbols.map_symbols(keywords, dict(context))
    assert len(calls) == 1


def test_map_symbols_http_passes_rerank_false(gpt, monkeypatch):
    """/ai/map-symbols가 context.rerank를 버리지 않고 map_symbols까지 넘긴다(SymbolContext)."""
    from fastapi.testclient import TestClient

    import main as ai_main

    fake = gpt({"choice": 2, "confident": True})
    calls = _count_chat_json(monkeypatch)
    keywords, context = _STEP
    r = TestClient(ai_main.app).post("/ai/map-symbols",
                                     json={"keywords": keywords, "context": {**context, "rerank": False}})
    assert r.status_code == 200, r.text
    assert calls == [] and fake.calls == []
    assert r.json()["symbols"][0]["decided_by"] == "rule"
