"""그림 정확도 ②·③ (2026-11-13 조사 picacc/report.md 원인 4·5).

② 직무를 만들 때 그림 검색이 준 후보 순서(GPT 재순위가 앞으로 올린 그림이 맨 앞)를 단계에 남기고, 편집기 후보
   (GET …/candidates, …/symbol-candidates)는 그 순서를 먼저 둔다. 편집기 검색은 규칙만이라(유료 모델 없음) 예전에는
   GPT 순서가 사라져 '그림 없음' 단계 1순위가 틀린 그림으로 보였다.
③ 문장을 고쳐도 생성 때 AI 그림 검색어(symbol_query)를 지우지 않는다. 예전에는 비워서 고친 문장 낱말로만 찾았고
   '제품의 앞면을 정리해요'로 고치자 후보가 옷·책 정리 그림으로 바뀌었다. 사업주가 직접 쓴 줄은 예전처럼 문장 낱말로 찾는다.
유료 호출 없음: ai_client는 모두 가짜다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import ai_client  # noqa: E402
import main  # noqa: E402
import step_context  # noqa: E402
from conftest import auth  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import Step  # noqa: E402

BASE = "http://localhost:8000"


def _match(card_id: str, label: str = "") -> dict:
    job = card_id.split("_", 1)[0].lower()
    return {"asset_id": card_id, "group_id": card_id, "job": job, "asset_type": "action", "label": label or card_id,
            "image_url": f"/api/aac/images/{job}/{card_id}.webp", "score": 0.3}


def _low_margin(ids: list[str]):
    """자동 채택하지 못한 판정(그림 없음) + 후보 순서(ids). 생성 때는 GPT가 맨 앞을 바꾼 순서라고 본다."""
    def fake(keywords, context=None):
        return {"symbols": [{"keyword": " / ".join(keywords), "image_url": None, "source": "fallback",
                             "confidence": 0.0, "needs_fallback": True, "reason": "low_margin",
                             "candidates": [_match(i) for i in ids]}]}
    return fake


def _accepted(card_id: str):
    def fake(keywords, context=None):
        m = _match(card_id)
        return {"symbols": [{"keyword": " / ".join(keywords), "image_url": m["image_url"], "source": "LOCAL_AAC",
                             "confidence": 0.5, "needs_fallback": False, "external_id": card_id,
                             "resolved_keyword": card_id, "reason": "accepted", "candidates": []}]}
    return fake


GPT_ORDER = ["PACKAGING_015", "PACKAGING_028", "PACKAGING_030"]   # 생성 때(GPT가 015를 맨 앞으로)
RULE_ORDER = ["PACKAGING_028", "PACKAGING_030", "PACKAGING_015"]  # 편집기 조회 때(규칙만)
QUERY = ["제품", "앞면", "같은 방향"]


def _create(client, token, steps):
    r = client.post("/api/tasks", headers=auth(token),
                    json={"raw_input": " ".join(s["sentence"] for s in steps), "steps": steps})
    assert r.status_code == 201, r.text
    return r.json()


def _candidates(client, token, task_id):
    r = client.get(f"/api/tasks/{task_id}/candidates", headers=auth(token))
    assert r.status_code == 200, r.text
    return {s["step_id"]: [c["card_id"] for c in s["candidates"]] for s in r.json()["steps"]}


def _row(sentence, query=tuple(QUERY)):
    return {"sentence": sentence, "action_type": "sort", "symbol_query": list(query)}


# --- ② 생성 때 순서 저장·편집기에서 그대로 -------------------------------------------------------

def test_create_stores_gpt_order_and_editor_keeps_it(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(GPT_ORDER))
    task = _create(client, employer_token, [_row("제품의 앞면이 같은 방향을 보도록 맞춰요.")])
    sid = task["steps"][0]["id"]
    assert task["steps"][0]["picture_state"] == "none"
    with SessionLocal() as db:
        stored = json.loads(db.get(Step, sid).symbol_candidates)
    assert stored == [f"/api/aac/images/packaging/{i}.webp" for i in GPT_ORDER]  # 상대 경로, 최대 3장

    calls = []
    monkeypatch.setattr(ai_client, "map_symbols",
                        lambda k, context=None: calls.append(k) or _low_margin(RULE_ORDER)(k))
    out = _candidates(client, employer_token, task["id"])
    assert out[sid] == GPT_ORDER
    assert calls == []  # 생성 때 후보가 3장이면 다시 찾지 않는다

    # 한 단계 후보(문장을 고친 뒤 화면이 부르는 길)도 같은 순서다.
    r = client.get(f"/api/tasks/{task['id']}/steps/{sid}/symbol-candidates", headers=auth(employer_token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert [c["asset_id"] for c in body["candidates"]][:3] == GPT_ORDER
    assert body["candidates"][0]["image_url"] == f"{BASE}/api/aac/images/packaging/PACKAGING_015.webp"
    assert body["candidates"][0]["label"]  # 이름은 자산 목록에서
    assert len({c["asset_id"] for c in body["candidates"]}) == len(body["candidates"])  # 겹침 없음


def test_accepted_pick_first_then_rule_fill(client, employer_token, monkeypatch):
    """자동 채택한 단계는 채택 그림 하나만 남고, 나머지는 지금 규칙 검색으로 채운다(겹침 없음)."""
    monkeypatch.setattr(ai_client, "map_symbols", _accepted("PACKAGING_030"))
    task = _create(client, employer_token, [_row("포장 봉투에 넣어요.", ("제품을 포장 봉투에 넣다",))])
    sid = task["steps"][0]["id"]
    assert task["steps"][0]["picture_state"] == "auto_high"
    with SessionLocal() as db:
        assert json.loads(db.get(Step, sid).symbol_candidates) == ["/api/aac/images/packaging/PACKAGING_030.webp"]
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(RULE_ORDER))
    assert _candidates(client, employer_token, task["id"])[sid] == ["PACKAGING_030", "PACKAGING_028", "PACKAGING_015"]


def test_old_steps_without_stored_order_use_rule_order(client, employer_token, monkeypatch):
    """0011 전에 만든 단계(빈 값)·깨진 값·자산 목록에 없는 그림·남의 주소는 무시하고 예전처럼 규칙 순서다."""
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(GPT_ORDER))
    task = _create(client, employer_token, [_row("가요."), _row("나요."), _row("다요.")])
    ids = [s["id"] for s in task["steps"]]
    with SessionLocal() as db:
        db.get(Step, ids[0]).symbol_candidates = ""
        db.get(Step, ids[1]).symbol_candidates = "{broken"
        db.get(Step, ids[2]).symbol_candidates = json.dumps(
            ["/api/aac/images/packaging/NOPE_999.webp", "https://evil.example/x.webp",
             "/api/aac/images/%2e%2e/secret.webp", "/api/aac/images/packaging/PACKAGING_030.webp"])
        db.commit()
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(RULE_ORDER))
    out = _candidates(client, employer_token, task["id"])
    assert out[ids[0]] == RULE_ORDER and out[ids[1]] == RULE_ORDER
    assert out[ids[2]] == ["PACKAGING_030", "PACKAGING_028", "PACKAGING_015"]


def test_added_step_stores_order(client, employer_token, monkeypatch):
    """편집기에서 더한 단계도 생성 때 순서를 남긴다."""
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(["PACKAGING_028"]))
    task = _create(client, employer_token, [_row("가요.")])
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(GPT_ORDER))
    r = client.post(f"/api/tasks/{task['id']}/steps", headers=auth(employer_token), json={"sentence": "상자를 닫아요"})
    assert r.status_code == 201, r.text
    new = r.json()["steps"][-1]
    with SessionLocal() as db:
        assert len(json.loads(db.get(Step, new["id"]).symbol_candidates)) == 3


def test_creation_candidates_helper():
    sym = {"image_url": None, "needs_fallback": True,
           "candidates": [_match("PACKAGING_015"), _match("PACKAGING_015"), {"image_url": "https://x/y.webp"},
                          _match("PACKAGING_028"), _match("PACKAGING_030"), _match("PACKAGING_034")]}
    assert json.loads(step_context.creation_candidates(sym)) == [
        f"/api/aac/images/packaging/{i}.webp" for i in GPT_ORDER]
    assert step_context.creation_candidates({"photo_media_id": "m", "source": "photo"}) == ""
    accepted = {"image_url": f"{BASE}/api/aac/images/packaging/PACKAGING_030.webp", "needs_fallback": False}
    assert json.loads(step_context.creation_candidates(accepted)) == ["/api/aac/images/packaging/PACKAGING_030.webp"]
    assert main.creation_candidates is step_context.creation_candidates


# --- ③ 문장을 고쳐도 검색어 유지 -------------------------------------------------------------

@pytest.mark.parametrize("defer", [True, False])
def test_edit_sentence_keeps_ai_query_and_order(client, employer_token, monkeypatch, defer):
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(GPT_ORDER[:1]))
    task = _create(client, employer_token, [_row("제품의 앞면을 맞춰요.")])
    sid = task["steps"][0]["id"]
    r = client.patch(f"/api/tasks/{task['id']}/steps/{sid}", headers=auth(employer_token),
                     json={"sentence": "제품의 앞면을 정리해요.", "defer_media": defer})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        step = db.get(Step, sid)
        assert step.symbol_query == "제품,앞면,같은 방향"
        assert json.loads(step.symbol_candidates) == ["/api/aac/images/packaging/PACKAGING_015.webp"]
    seen = []
    monkeypatch.setattr(ai_client, "map_symbols",
                        lambda k, context=None: seen.append((list(k), context["sentence"]))
                        or _low_margin(RULE_ORDER)(k))
    out = _candidates(client, employer_token, task["id"])
    # 검색어는 생성 때 AI 검색어, 문장 맥락은 고친 문장. 생성 때 1순위가 맨 앞.
    assert seen == [(QUERY, "제품의 앞면을 정리해요.")]
    assert out[sid] == ["PACKAGING_015", "PACKAGING_028", "PACKAGING_030"]


def test_rewrite_keeps_ai_query(client, employer_token, monkeypatch):
    """칸을 벗어날 때 저장(rewrite, 나누기 없음)도 검색어를 지우지 않는다."""
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(GPT_ORDER))
    monkeypatch.setattr(ai_client, "split_hint", lambda s: False)
    task = _create(client, employer_token, [_row("제품의 앞면을 맞춰요.")])
    sid = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "제품의 앞면을 정리해요."})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        step = db.get(Step, sid)
        assert step.sentence == "제품의 앞면을 정리해요."
        assert step.symbol_query == "제품,앞면,같은 방향" and step.symbol_candidates


def test_manual_rows_search_current_sentence(client, employer_token, monkeypatch):
    """AI 검색어가 없는 줄(사업주가 쓴 줄)은 검색어를 남기지 않는다 → 고치면 새 문장 낱말로 찾는다."""
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(GPT_ORDER))
    task = _create(client, employer_token, [{"sentence": "상자를 옮겨요"}])
    sid = task["steps"][0]["id"]
    with SessionLocal() as db:
        assert db.get(Step, sid).symbol_query == ""
    r = client.patch(f"/api/tasks/{task['id']}/steps/{sid}", headers=auth(employer_token),
                     json={"sentence": "바닥을 쓸어요", "defer_media": True})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert step_context._step_search_terms(db.get(Step, sid)) == ["바닥을", "쓸어요"]


def test_input_screen_edited_row_keeps_ai_query(client, employer_token, monkeypatch):
    """입력 화면에서 고친 줄도 AI 검색어가 오면 그것으로 찾고 남긴다(화면 splitRows.toConfirmed가 보낸다)."""
    seen = []
    monkeypatch.setattr(ai_client, "map_symbols",
                        lambda k, context=None: seen.append(list(k)) or _low_margin(GPT_ORDER)(k))
    task = _create(client, employer_token, [{"sentence": "제품의 앞면을 정리해요.", "symbol_query": QUERY}])
    assert seen == [QUERY]
    with SessionLocal() as db:
        assert db.get(Step, task["steps"][0]["id"]).symbol_query == "제품,앞면,같은 방향"


# --- ③ 2차: 문장 뜻이 바뀌면 옛 검색어·후보를 비운다 ----------------------------------------------

TAPE_QUERY = ["상자를 테이프로 붙이다"]


@pytest.mark.parametrize("defer", [True, False])
def test_edit_to_other_meaning_drops_old_query_and_cards(client, employer_token, monkeypatch, defer):
    """검증 재현: 검색어 '상자를 테이프로 붙이다' 단계를 '바닥을 빗자루로 쓸어요.'로 고치면 옛 포장 그림 3장이 남아
    그림 없음 단계에서 한 번 누르면 틀린 그림이 붙었다. 이제 검색어·후보를 비우고 새 문장 낱말로 다시 찾는다."""
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(GPT_ORDER))
    task = _create(client, employer_token, [_row("상자를 테이프로 붙여요.", TAPE_QUERY)])
    sid = task["steps"][0]["id"]
    r = client.patch(f"/api/tasks/{task['id']}/steps/{sid}", headers=auth(employer_token),
                     json={"sentence": "바닥을 빗자루로 쓸어요.", "defer_media": defer})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        step = db.get(Step, sid)
        assert step.symbol_query == "" and step.symbol_candidates == ""
        assert step_context._step_search_terms(step) == ["바닥을", "빗자루로", "쓸어요"]
    seen = []
    monkeypatch.setattr(ai_client, "map_symbols",
                        lambda k, context=None: seen.append(list(k)) or _low_margin(["CLEANING_001"])(k))
    out = _candidates(client, employer_token, task["id"])
    assert seen == [["바닥을", "빗자루로", "쓸어요"]]
    assert out[sid] == ["CLEANING_001"]
    seen.clear()
    r = client.get(f"/api/tasks/{task['id']}/steps/{sid}/symbol-candidates", headers=auth(employer_token))
    assert r.status_code == 200, r.text
    assert [c["asset_id"] for c in r.json()["candidates"]] == ["CLEANING_001"]
    assert seen == [["바닥을", "빗자루로", "쓸어요"]]


def test_edit_same_topic_keeps_query_and_cards(client, employer_token, monkeypatch):
    """대상·동작 낱말을 하나라도 같이 쓰면('테이프를 꼼꼼히 붙여요') 검색어와 생성 때 후보를 그대로 둔다."""
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin(GPT_ORDER))
    task = _create(client, employer_token, [_row("상자를 테이프로 붙여요.", TAPE_QUERY)])
    sid = task["steps"][0]["id"]
    client.patch(f"/api/tasks/{task['id']}/steps/{sid}", headers=auth(employer_token),
                 json={"sentence": "테이프를 꼼꼼히 붙여요.", "defer_media": True})
    with SessionLocal() as db:
        step = db.get(Step, sid)
        assert step.symbol_query == "상자를 테이프로 붙이다"
        assert len(json.loads(step.symbol_candidates)) == 3


@pytest.mark.parametrize("new, terms", [("바닥을 쓸어요", ["바닥을", "쓸어요"]),
                                        ("상자를 들어서 옮겨요", ["상자를", "들어서", "옮겨요"])])
def test_old_sentence_word_query_cleared_on_edit(client, employer_token, monkeypatch, new, terms):
    """0011 이전 직접 쓴 줄은 문장 낱말을 검색어로 남겼다(re.findall). 검색어가 모두 옛 문장 낱말이면 예전처럼 문장을
    고칠 때 비워 새 문장 낱말로 찾는다(검증 재현: '상자를,옮겨요' → '바닥을 쓸어요'인데 옛 낱말로 찾았다)."""
    monkeypatch.setattr(ai_client, "map_symbols", _low_margin([]))
    task = _create(client, employer_token, [{"sentence": "상자를 옮겨요"}])
    sid = task["steps"][0]["id"]
    with SessionLocal() as db:
        step = db.get(Step, sid)
        step.symbol_query, step.symbol_candidates = "상자를,옮겨요", ""
        db.commit()
    r = client.patch(f"/api/tasks/{task['id']}/steps/{sid}", headers=auth(employer_token),
                     json={"sentence": new, "defer_media": True})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        step = db.get(Step, sid)
        assert step.symbol_query == ""
        assert step_context._step_search_terms(step) == terms


def test_shares_topic_rules():
    f = step_context.shares_topic
    assert not f("바닥을 빗자루로 쓸어요.", TAPE_QUERY)
    assert f("상자를 들어서 옮겨요.", ["상자", "box"])          # 토씨를 뗀다
    assert f("제품의 앞면을 정리해요.", QUERY)
    assert f("붙여요.", TAPE_QUERY)                              # 풀이씨는 첫 음절('붙이다'='붙여요')
    assert not f("바닥을 쓸어요", ["상자를", "옮겨요"])
    assert not f("같은 곳에 놓아요", ["같은 방향"])               # 뜻 없는 낱말('같은')만 겹치면 아니다
