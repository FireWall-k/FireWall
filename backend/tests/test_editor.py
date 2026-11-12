"""2b-1 만들고 보내기 서버 시험 (scratchpad/p2/contract.md §3, tasks.md §4.4).

지키는 것:
- 편집기 단계 응답(StepOut 확장): picture·candidates·split·lint·safety·group_break. 확신 점수 숫자는 없다.
- 후보 조회(모든 단계 한 번에, symbol-candidates)는 유료 모델을 부르지 않는다: ai_client에 context.rerank=false.
- 문장 점검 3종(too_long·hard_word·command_tone), '동작이 2개'는 만들지 않는다.
- 조심 표시: 낱말 규칙으로 '✦ 자동 제안'(source=auto) → 사업주 스위치는 manual, 근로자 응답에는 flag만, 같은 내용 비교에 들어감,
  보내기 시트 auto_caution 경고(막지 않음).
- 일괄 확인은 하나라도 확인할 수 없으면 422이고 아무것도 바꾸지 않는다.
- 자동 저장(defer_media)은 음성 합성·나누기 검사를 부르지 않는다. expected_updated_at이 다르면 409.
- POST /api/tasks는 needs_review를 늘 false로 저장한다. 편집기에서 나눠도 보내기 검사를 통과한다.
- 보내기 전 음성 합성은 트랜잭션 밖이다(합성 중 다른 연결이 쓸 수 있다). 미리보기는 기록을 남기지 않는다.
- 고정 문장(규칙 엔진 기록)이 6단계 모두 auto_high로 서버 끝까지 간다.
"""
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

import ai_client  # noqa: E402
from aac_assets import asset_label  # noqa: E402
import main  # noqa: E402
import safety_rules  # noqa: E402
import sentence_lint  # noqa: E402
import step_audio  # noqa: E402
from conftest import TEST_AAC_IMAGE, auth, delete_worker, give_pictures  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import (  # noqa: E402
    AccessAuditLog,
    Assignment,
    HelpRequest,
    PerformanceLog,
    Step,
    TaskVersion,
    TaskVersionStep,
)

ACCEPTED_URL = "/api/aac/images/retail/RETAIL_029.webp"
FIXTURES = Path(__file__).parent / "fixtures"


def _accepted(keywords, context=None):
    """규칙 매칭이 자동 채택한 모양(ai_service accepted)."""
    return {"symbols": [{
        "keyword": " / ".join(keywords), "image_url": ACCEPTED_URL, "source": "LOCAL_AAC",
        "confidence": 0.51, "needs_fallback": False, "external_id": "RETAIL_029",
        "resolved_keyword": "상품을 선반에 놓는다", "reason": "accepted", "candidates": []}]}


@pytest.fixture()
def worker(client, employer_token):
    r = client.post("/api/workers", json={"display_name": "편집기시험"}, headers=auth(employer_token))
    assert r.status_code == 201, r.text
    w = r.json()
    login = client.post("/api/auth/worker-login",
                        json={"workplace_code": "DEMO01", "access_code": w["access_code"]})
    w["token"] = login.json()["token"]
    yield w
    delete_worker(client, w["id"], auth(employer_token))


def _create(client, token, sentences, **extra):
    steps = [s if isinstance(s, dict) else {"sentence": s} for s in sentences]
    r = client.post("/api/tasks", headers=auth(token),
                    json={"raw_input": " ".join(s["sentence"] for s in steps), "steps": steps, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _get(client, token, task_id):
    r = client.get(f"/api/tasks/{task_id}", headers=auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def _patch(client, token, task_id, step_id, **body):
    return client.patch(f"/api/tasks/{task_id}/steps/{step_id}", headers=auth(token), json=body)


def _confirm_all(client, token, task_id):
    task = _get(client, token, task_id)
    ids = [s["id"] for s in task["steps"] if s["picture_state"] == "auto_high"]
    if ids:
        r = client.post(f"/api/tasks/{task_id}/pictures/confirm", headers=auth(token), json={"step_ids": ids})
        assert r.status_code == 200, r.text


def _send(client, token, task_id, worker_ids):
    return client.post(f"/api/tasks/{task_id}/send", headers=auth(token),
                       json={"worker_ids": worker_ids, "day": "today"})


def _set_choose(step_id):
    """그림은 있으나 자동 채택 못 한 단계(choose)를 만든다."""
    with SessionLocal() as db:
        s = db.get(Step, step_id)
        s.symbol_url = "http://localhost:8000" + TEST_AAC_IMAGE
        s.needs_fallback = True
        s.picture_confirmed = False
        db.commit()


# --- StepOut 확장 ---------------------------------------------------------------------------

def test_step_out_has_editor_fields(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "map_symbols", _accepted)
    task = _create(client, employer_token, [
        {"sentence": "상품을 선반에 놓아요", "split": {"source": "rule", "original_span": "상품을 선반에 놓고 모아요"}},
        "칼로 상자를 뜯으세요"])
    s1, s2 = task["steps"]
    assert s1["picture"] == {"card_id": "RETAIL_029", "url": "http://localhost:8000" + ACCEPTED_URL,
                             "label": "상품을 선반에 놓는다", "source": "auto"}
    assert s1["picture_state"] == "auto_high"
    assert s1["candidates"] == []  # 후보는 GET …/candidates가 모든 단계를 한 번에 준다
    assert s1["split"] == {"source": "rule", "needs_review": False, "original_span": "상품을 선반에 놓고 모아요"}
    assert s1["lint"] == [] and s1["safety"] == {"flag": False, "source": "", "note": ""}
    assert s1["group_break"] is False and s1["task_updated_at"]
    assert s2["lint"] == [{"code": "command_tone", "from": None, "to": None}]
    assert s2["safety"] == {"flag": True, "source": "auto", "note": ""} and s2["safety_flag"] is True
    # 확신 점수 숫자는 보내지 않는다.
    assert "confidence" not in json.dumps(task) and "score" not in json.dumps(task)


def test_picture_source_photo_and_none(client, employer_token):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    assert task["steps"][0]["picture"] is None and task["steps"][0]["picture_state"] == "none"


# --- 후보(유료 모델 없음) ---------------------------------------------------------------------

def test_candidates_no_paid_model(client, employer_token, monkeypatch):
    """모든 단계(확인한 단계 포함) 후보를 한 번에 주고, ai_client 호출마다 context.rerank=false다."""
    calls, searches = [], []

    def record_map(keywords, context=None):
        calls.append(context)
        if "바닥" in (context or {}).get("sentence", ""):
            return {"symbols": [{"keyword": "", "image_url": None, "source": "fallback", "confidence": 0.0,
                                 "needs_fallback": True, "reason": "low_margin", "candidates": [
                                     {"asset_id": f"CAFE_00{i}", "group_id": f"CAFE_00{i}", "job": "cafe",
                                      "asset_type": "action", "label": f"후보{i}",
                                      "image_url": f"/api/aac/images/cafe/CAFE_00{i}.webp", "score": 0.2}
                                     for i in range(1, 6)]}]}
        return _accepted(keywords, context)

    def record_search(query, context=None, limit=5):
        searches.append((query, context, limit))
        return {"query": query, "matches": [
            {"asset_id": "RETAIL_029", "group_id": "RETAIL_029", "job": "retail", "asset_type": "action",
             "label": "상품을 선반에 놓는다", "image_url": ACCEPTED_URL, "score": 0.5},
            {"asset_id": "RETAIL_017", "group_id": "RETAIL_017", "job": "retail", "asset_type": "action",
             "label": "같은 상품끼리 모은다", "image_url": "/api/aac/images/retail/RETAIL_017.webp", "score": 0.4}]}

    monkeypatch.setattr(ai_client, "map_symbols", record_map)
    monkeypatch.setattr(ai_client, "search_aac", record_search)
    task = _create(client, employer_token, ["상품을 놓아요", "같은 상품끼리 모아요", "바닥을 쓸어요"])
    _confirm_all(client, employer_token, task["id"])  # 확인한 단계도 후보를 준다
    calls.clear()
    r = client.get(f"/api/tasks/{task['id']}/candidates", headers=auth(employer_token))
    assert r.status_code == 200, r.text
    out = {s["step_id"]: s["candidates"] for s in r.json()["steps"]}
    assert list(out) == [s["id"] for s in task["steps"]]
    # 생성 때 후보가 3장 남은 단계(바닥)는 다시 찾지 않는다(그림 정확도 ②).
    assert len(calls) == 2 and all(c["rerank"] is False for c in calls)
    # 그림 검색(규칙)에는 rerank 칸을 넘기지 않는다.
    assert len(searches) == 2 and all("rerank" not in c for _, c, _ in searches)
    first = out[task["steps"][0]["id"]]
    assert [c["card_id"] for c in first] == ["RETAIL_029", "RETAIL_017"]  # 채택 그림이 맨 앞, 겹침 없음
    third = out[task["steps"][2]["id"]]
    assert len(third) == 3 and third[0] == {"card_id": "CAFE_001",
                                            "url": "http://localhost:8000/api/aac/images/cafe/CAFE_001.webp",
                                            # 생성 때 후보에서 오므로 이름은 자산 목록에서 찾는다.
                                            "label": asset_label("CAFE_001")}


def test_symbol_candidates_also_rerank_off(client, employer_token, monkeypatch):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    calls = []
    monkeypatch.setattr(ai_client, "map_symbols", lambda k, context=None: calls.append(context) or {"symbols": []})
    r = client.get(f"/api/tasks/{task['id']}/steps/{task['steps'][0]['id']}/symbol-candidates",
                   headers=auth(employer_token))
    assert r.status_code == 200, r.text
    assert calls and calls[0]["rerank"] is False


def test_candidates_other_employer_404(client, employer_token):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    from auth import make_token
    other = make_token("emp-someone-else", "employer")
    assert client.get(f"/api/tasks/{task['id']}/candidates", headers=auth(other)).status_code == 404


# --- 문장 점검 ---------------------------------------------------------------------------------

def test_lint_rules():
    assert sentence_lint.lint("손을 씻어요") == []
    assert sentence_lint.lint("상품을 선반 위에 가지런히 하나씩 차례대로 놓아요") == [{"code": "too_long"}]
    assert sentence_lint.char_count("상품을 선반에 놓아요") == 9
    assert sentence_lint.lint("상자를 적재해요") == [{"code": "hard_word", "from": "적재", "to": "쌓기"}]
    assert sentence_lint.lint("상품을 진열하세요.") == [{"code": "hard_word", "from": "진열", "to": "놓기"},
                                                         {"code": "command_tone"}]
    assert sentence_lint.is_command_tone("문을 닫으십시오")
    assert not sentence_lint.is_command_tone("문을 닫아요")
    # 20자 경계: 공백을 뺀 20자는 괜찮고 21자부터 too_long.
    assert not sentence_lint.is_too_long("가" * 20) and sentence_lint.is_too_long("가 " * 21)


def test_lint_codes_only_three(client, employer_token):
    """lint code는 세 가지뿐이다('동작이 2개' 같은 code는 만들지 않는다)."""
    task = _create(client, employer_token, ["상자를 들고 옮기고 쌓고 닦고 정리하세요 그리고 적재해요"])
    codes = [item["code"] for item in task["steps"][0]["lint"]]
    assert codes == ["too_long", "hard_word"]


def test_send_check_lint_and_caution_warnings(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "map_symbols", _accepted)
    task = _create(client, employer_token, ["상품을 선반 위에 가지런히 하나씩 차례대로 놓아요",
                                            "세제를 뿌리세요", "손을 씻어요"])
    r = client.get(f"/api/tasks/{task['id']}/send-check", headers=auth(employer_token))
    warn = {w["code"]: w for w in r.json()["warnings"]}
    ids = [s["id"] for s in task["steps"]]
    assert warn["too_long"] == {"code": "too_long", "count": 1, "step_ids": [ids[0]]}
    assert warn["command_tone"] == {"code": "command_tone", "count": 1, "step_ids": [ids[1]]}
    assert warn["auto_caution"] == {"code": "auto_caution", "count": 1, "step_ids": [ids[1]]}
    assert "label" not in r.text


# --- 조심 표시 ---------------------------------------------------------------------------------

def test_safety_keywords():
    assert safety_rules.KEYWORDS == ("칼", "가위", "뜨거운", "불", "세제", "락스", "기계", "칼날", "사다리", "전기")
    for sentence, hit in (("커터칼로 상자를 열어요", "칼"), ("가위로 잘라요", "가위"), ("뜨거운 물을 부어요", "뜨거운"),
                          ("불을 꺼요", "불"), ("세제를 넣어요", "세제"), ("락스를 풀어요", "락스"),
                          ("기계를 멈춰요", "기계"), ("칼날을 닦아요", "칼날"), ("사다리에 올라가요", "사다리"),
                          ("전기 코드를 뽑아요", "전기"), ("물이 뜨거워요", "뜨거운")):
        assert safety_rules.matched_keyword(sentence) == hit, sentence
    for sentence in ("불량품을 골라요", "칼로리를 봐요", "상품을 놓아요"):
        assert safety_rules.matched_keyword(sentence) is None, sentence
    assert safety_rules.auto_flag("상품을 놓아요", ["유리 조각 주의"]) is True
    assert safety_rules.auto_flag("상품을 놓아요", []) is False


def test_safety_keywords_inflections_and_compounds():
    """1회차 검증: '뜨겁-' 활용형과 불 합성어를 놓치지 않는다."""
    for sentence in ("냄비가 뜨겁습니다 조심해요", "물을 뜨겁게 데워요", "팬이 뜨겁다", "가스불을 켜요",
                     "가스불이 꺼졌는지 봐요", "숯불에 고기를 올려요", "촛불을 꺼요"):
        assert safety_rules.matched_keyword(sentence) in ("뜨거운", "불"), sentence
    # 2회차 검증: 조사 '에는·에도·엔·보다·이에요'와 불조심·불씨·불붙-, 조사 '만'이 붙은 불 낱말('불만' 회귀).
    for sentence in ("불조심해요", "불조심하세요", "불에는 손을 대지 않아요", "불에도 조심해요", "불엔 가까이 가지 않아요",
                     "불보다 멀리 서요", "불이에요", "불씨를 확인해요", "불붙은 종이를 버려요", "가스불만 꺼요",
                     "촛불만 켜 두어요", "숯불만 남겨요", "불만 끄고 나가요"):
        assert safety_rules.matched_keyword(sentence) == "불", sentence
    assert safety_rules.matched_keyword("전기세탁기를 돌려요") == "전기"
    for sentence in ("노래를 불러요", "바람이 불어요", "불편해요", "불안해요", "이불을 개요", "불량품을 빼요",
                     "전기세를 내요", "출입 불가", "불가능해요", "고칼슘우유를 진열해요"):
        assert safety_rules.matched_keyword(sentence) is None, sentence


def test_safety_keywords_false_positives():
    """1회차 검증: 조심 낱말이 들어 있지만 다른 뜻인 흔한 말에는 켜지 않는다(거짓 양성 문장 표 고정)."""
    for sentence in ("칼슘 우유를 진열해요", "칼라 상자를 접어요", "칼집 낸 소시지를 담아요", "불만 접수를 받아요",
                     "불만을 적어요", "사다리꼴 상자를 접어요", "가위표를 쳐요", "이불을 개요", "불량품을 빼요"):
        assert safety_rules.matched_keyword(sentence) is None, sentence
    # 진짜 위험 낱말은 그대로 걸린다.
    assert safety_rules.matched_keyword("칼로 양파를 썰어요") == "칼"
    assert safety_rules.matched_keyword("사다리를 펴요") == "사다리"


def test_split_preview_has_auto_safety_flag(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "decompose", lambda raw, context=None, **kw: {
        "task_title": "t", "steps": [
            {"order": 1, "sentence": "칼로 상자를 열어요", "action_type": "other", "symbol_query": ["상자"]},
            {"order": 2, "sentence": "상품을 놓아요", "action_type": "move", "symbol_query": ["상품"],
             "safety_flags": ["무거움"]},
            {"order": 3, "sentence": "손을 씻어요", "action_type": "clean", "symbol_query": ["손"]}]})
    r = client.post("/api/tasks/split-preview", headers=auth(employer_token), json={"raw_input": "x"})
    assert r.status_code == 200, r.text
    assert [s["safety_flag"] for s in r.json()["steps"]] == [True, True, False]


def test_create_keeps_preview_safety_flag(client, employer_token):
    task = _create(client, employer_token, [{"sentence": "상품을 놓아요", "safety_flag": True}, "손을 씻어요"])
    assert [s["safety"]["source"] for s in task["steps"]] == ["auto", ""]
    assert [s["safety_flag"] for s in task["steps"]] == [True, False]


def test_safety_manual_switch_sticks_and_reaches_worker(client, employer_token, worker):
    task = _create(client, employer_token, ["칼로 상자를 열어요", "상품을 놓아요"])
    give_pictures(client, employer_token, task["id"])
    s1, s2 = task["steps"]
    # 자동으로 켠 1단계를 사업주가 끄고, 2단계를 켠다 → 둘 다 manual.
    r = _patch(client, employer_token, task["id"], s1["id"], safety_flag=False)
    assert r.status_code == 200 and r.json()["safety"] == {"flag": False, "source": "manual", "note": ""}
    r = _patch(client, employer_token, task["id"], s2["id"], safety_flag=True, safety_note="무거워요")
    assert r.json()["safety"] == {"flag": True, "source": "manual", "note": "무거워요"}
    # manual이면 문장을 고쳐도 자동으로 다시 정하지 않는다(칼이 들어가도 꺼진 그대로).
    r = _patch(client, employer_token, task["id"], s1["id"], sentence="칼로 테이프를 잘라요")
    assert r.json()["safety"]["flag"] is False and r.json()["safety"]["source"] == "manual"
    check = client.get(f"/api/tasks/{task['id']}/send-check", headers=auth(employer_token)).json()
    assert {w["code"]: w["count"] for w in check["warnings"]}["auto_caution"] == 0
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200
    cards = client.get("/api/worker/me/today", headers=auth(worker["token"])).json()
    card = next(c for c in cards if c["task_id"] == task["id"])
    assert [s["safety_flag"] for s in card["steps"]] == [False, True]
    # 근로자 응답에는 flag만(사업주 칸 없음).
    assert all("safety" not in s and "lint" not in s and "safety_note" not in s for s in card["steps"])
    hist = client.get("/api/worker/me/history", headers=auth(worker["token"])).json()
    h = next(c for c in hist if c["assignment_id"] == card["assignment_id"])
    assert [s["safety_flag"] for s in h["steps"]] == [False, True]


def test_auto_caution_is_sent_without_confirmation(client, employer_token, worker):
    """창업자 결정: 자동 조심 표시는 확인 없이 근로자에게 간다(보내기를 막지 않는다)."""
    task = _create(client, employer_token, ["뜨거운 물을 부어요"])
    give_pictures(client, employer_token, task["id"])
    check = client.get(f"/api/tasks/{task['id']}/send-check", headers=auth(employer_token)).json()
    assert check["ok"] is True
    assert {w["code"]: w["count"] for w in check["warnings"]}["auto_caution"] == 1
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200
    card = next(c for c in client.get("/api/worker/me/today", headers=auth(worker["token"])).json()
                if c["task_id"] == task["id"])
    assert card["steps"][0]["safety_flag"] is True


def test_safety_and_group_break_count_in_same_content(client, employer_token, worker):
    task = _create(client, employer_token, ["상품을 놓아요", "손을 씻어요"])
    give_pictures(client, employer_token, task["id"])
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200
    sid = task["steps"][1]["id"]
    assert _patch(client, employer_token, task["id"], sid, safety_flag=True).status_code == 200
    assert _get(client, employer_token, task["id"])["version"]["has_unsent_changes"] is True
    assert _patch(client, employer_token, task["id"], sid, safety_flag=False).status_code == 200
    assert _get(client, employer_token, task["id"])["version"]["has_unsent_changes"] is False
    r = _patch(client, employer_token, task["id"], sid, group_break=True)
    assert r.status_code == 200 and r.json()["group_break"] is True
    assert _get(client, employer_token, task["id"])["version"]["has_unsent_changes"] is True
    r = _send(client, employer_token, task["id"], [worker["id"]])
    assert r.json()["version_created"] is True
    with SessionLocal() as db:
        v = db.scalars(select(TaskVersion).where(TaskVersion.task_id == task["id"])
                       .order_by(TaskVersion.version_no.desc())).first()
        assert [vs.group_break for vs in v.steps] == [False, True]
    # 근로자 응답에는 group_break를 보내지 않는다(쉼 화면은 3차).
    cards = client.get("/api/worker/me/today?include_done=true", headers=auth(worker["token"])).json()
    assert all("group_break" not in s for c in cards for s in c["steps"])


# --- 일괄 확인 ---------------------------------------------------------------------------------

def test_bulk_confirm(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "map_symbols", _accepted)
    task = _create(client, employer_token, ["상품을 놓아요", "상품을 모아요", "손을 씻어요"])
    ids = [s["id"] for s in task["steps"]]
    r = client.post(f"/api/tasks/{task['id']}/pictures/confirm", headers=auth(employer_token),
                    json={"step_ids": ids[:2]})
    assert r.status_code == 200, r.text
    assert [s["picture_state"] for s in r.json()] == ["confirmed", "confirmed"]
    # 이미 확인한 단계가 섞여도(다시 눌러도) 같은 결과다.
    r = client.post(f"/api/tasks/{task['id']}/pictures/confirm", headers=auth(employer_token),
                    json={"step_ids": ids})
    assert r.status_code == 200 and all(s["picture_state"] == "confirmed" for s in r.json())


def test_bulk_confirm_422_is_atomic(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "map_symbols", _accepted)
    task = _create(client, employer_token, ["상품을 놓아요", "상품을 모아요", "바닥을 쓸어요", "손을 씻어요"])
    ids = [s["id"] for s in task["steps"]]
    _set_choose(ids[2])
    with SessionLocal() as db:  # 4단계는 그림 없음
        s = db.get(Step, ids[3])
        s.symbol_url = None
        db.commit()
    r = client.post(f"/api/tasks/{task['id']}/pictures/confirm", headers=auth(employer_token),
                    json={"step_ids": ids})
    assert r.status_code == 422
    body = r.json()
    assert body["detail"] == "확인할 수 없는 단계가 있어요: 3단계(골라 주세요), 4단계(그림 없음)"
    assert body["code"] == "not_confirmable" and body["step_ids"] == [ids[2], ids[3]]
    # 하나도 바꾸지 않았다.
    states = [s["picture_state"] for s in _get(client, employer_token, task["id"])["steps"]]
    assert states == ["auto_high", "auto_high", "choose", "none"]
    r = client.post(f"/api/tasks/{task['id']}/pictures/confirm", headers=auth(employer_token),
                    json={"step_ids": [ids[0], "no-such-step"]})
    assert r.status_code == 404
    assert _get(client, employer_token, task["id"])["steps"][0]["picture_state"] == "auto_high"


# --- 그림 적용 ---------------------------------------------------------------------------------

def test_apply_picture_confirms(client, employer_token):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    sid = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/picture", headers=auth(employer_token),
                    json={"card_id": "CAFE_007", "url": "http://localhost:8000" + TEST_AAC_IMAGE, "label": "아무거나"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["picture_state"] == "confirmed"
    assert out["picture"]["source"] == "manual" and out["picture"]["card_id"] == "CAFE_007"
    assert out["picture"]["label"] and out["picture"]["label"] != "아무거나"  # 이름은 자산 목록에서
    assert out["symbol_url"] == "http://localhost:8000" + TEST_AAC_IMAGE
    # 상대 주소도 받는다.
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/picture", headers=auth(employer_token),
                    json={"card_id": "RETAIL_029", "url": ACCEPTED_URL, "label": ""})
    assert r.status_code == 200 and r.json()["picture"]["card_id"] == "RETAIL_029"


@pytest.mark.parametrize("card_id,url", [
    ("X", "https://evil.example/x.png"),
    ("CAFE_007", "/api/aac/images/../secret/CAFE_007.webp"),
    ("CAFE_013", TEST_AAC_IMAGE),  # 그림 주소와 id가 다름
    ("NOPE_999", "/api/aac/images/cafe/NOPE_999.webp"),  # 자산 목록에 없음
])
def test_apply_picture_rejects(client, employer_token, card_id, url):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    sid = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/picture", headers=auth(employer_token),
                    json={"card_id": card_id, "url": url})
    assert r.status_code == 400
    assert _get(client, employer_token, task["id"])["steps"][0]["picture_state"] == "none"


# --- 자동 저장(defer_media)·충돌(409) ------------------------------------------------------------

def test_defer_media_skips_tts_and_split_check(client, employer_token, monkeypatch):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    sid = task["steps"][0]["id"]
    tts_calls, split_calls, classify_calls = [], [], []
    monkeypatch.setattr(main, "synthesize_tts", lambda text, scope: tts_calls.append(text))
    monkeypatch.setattr(step_audio, "synthesize_tts", lambda text, scope: tts_calls.append(text))
    monkeypatch.setattr(ai_client, "split_hint", lambda s: split_calls.append(s) or True)
    monkeypatch.setattr(ai_client, "decompose", lambda *a, **kw: split_calls.append(a) or {"steps": []})
    monkeypatch.setattr(ai_client, "classify_action", lambda s: classify_calls.append(s) or "move")
    for text in ("상자를 옮기고", "상자를 옮기고 수량을 확인해요"):
        r = _patch(client, employer_token, task["id"], sid, sentence=text, defer_media=True)
        assert r.status_code == 200, r.text
    assert tts_calls == [] and split_calls == [] and classify_calls == []
    out = r.json()
    assert out["sentence"] == "상자를 옮기고 수량을 확인해요" and out["tts_audio_url"] is None
    with SessionLocal() as db:
        assert db.get(Step, sid).tts_stale is True
    # 칸을 벗어날 때(rewrite, 같은 문장): 그때 나누기 검사·음성·동작 종류를 한다.
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "상자를 옮기고 수량을 확인해요"})
    assert r.status_code == 200, r.text
    assert split_calls and tts_calls == ["상자를 옮기고 수량을 확인해요"] and classify_calls
    with SessionLocal() as db:
        assert db.get(Step, sid).tts_stale is False


def test_expected_updated_at_conflict(client, employer_token):
    task = _create(client, employer_token, ["상자를 옮겨요", "손을 씻어요"])
    s1, s2 = (s["id"] for s in task["steps"])
    seen = task["updated_at"]
    r = _patch(client, employer_token, task["id"], s1, sentence="상자를 들어요", defer_media=True,
               expected_updated_at=seen)
    assert r.status_code == 200, r.text
    nxt = r.json()["task_updated_at"]
    assert nxt != seen
    # 같은 창은 응답의 task_updated_at으로 이어서 저장한다.
    r = _patch(client, employer_token, task["id"], s2, sentence="손을 닦아요", defer_media=True,
               expected_updated_at=nxt)
    assert r.status_code == 200, r.text
    # 다른 창(옛 updated_at)은 409, 바꾸지 않는다.
    r = _patch(client, employer_token, task["id"], s1, sentence="상자를 내려요", defer_media=True,
               expected_updated_at=seen)
    assert r.status_code == 409
    assert r.json()["detail"] == "다른 창에서 먼저 고쳤어요. 새로 불러온 뒤 다시 고쳐 주세요."
    assert _get(client, employer_token, task["id"])["steps"][0]["sentence"] == "상자를 들어요"
    # 값을 안 보내면 검사하지 않는다(옛 화면).
    assert _patch(client, employer_token, task["id"], s1, sentence="상자를 내려요").status_code == 200


def test_defer_then_send_reclassifies_action(client, employer_token, worker, monkeypatch):
    """1회차 검증: 자동 저장 뒤 칸을 벗어나지 않고 보내도 동작 종류가 새 문장으로 다시 매겨진다(옛 값 고정 금지)."""
    task = _create(client, employer_token, ["상자를 옮겨요"])
    give_pictures(client, employer_token, task["id"])
    _confirm_all(client, employer_token, task["id"])
    sid = task["steps"][0]["id"]
    monkeypatch.setattr(ai_client, "classify_action", lambda s: "clean" if "닦" in s else "move")
    r = _patch(client, employer_token, task["id"], sid, sentence="바닥을 걸레로 닦아요", defer_media=True)
    assert r.status_code == 200, r.text
    seen = r.json()["task_updated_at"]
    r = _send(client, employer_token, task["id"], [worker["id"]])
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(Step, sid).action_type == "clean"
        vs = db.scalars(select(TaskVersionStep).join(TaskVersion)
                        .where(TaskVersion.task_id == task["id"])).all()
        assert [(v.sentence, v.action_type) for v in vs] == [("바닥을 걸레로 닦아요", "clean")]
    # 다시 매긴 것은 사업주가 고친 것이 아니다 — 같은 창의 다음 자동 저장이 409가 되지 않는다.
    assert _get(client, employer_token, task["id"])["updated_at"] == seen


def test_defer_then_tts_reclassifies_action(client, employer_token, monkeypatch):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    sid = task["steps"][0]["id"]
    monkeypatch.setattr(ai_client, "classify_action", lambda s: "clean")
    monkeypatch.setattr(step_audio, "synthesize_tts", _fake_tts_file([]))
    _patch(client, employer_token, task["id"], sid, sentence="바닥을 걸레로 닦아요", defer_media=True)
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/tts", headers=auth(employer_token))
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert db.get(Step, sid).action_type == "clean"


def test_stale_window_rewrite_409(client, employer_token):
    """1회차 검증: 옛 창이 칸을 벗어나며 저장(rewrite)해도 다른 창이 먼저 고친 문장을 덮지 않는다."""
    task = _create(client, employer_token, ["상자를 옮겨요"])
    tid, sid, seen = task["id"], task["steps"][0]["id"], task["updated_at"]
    r = _patch(client, employer_token, tid, sid, sentence="창A가 고친 문장이에요", defer_media=True,
               expected_updated_at=seen)
    assert r.status_code == 200, r.text
    r = client.post(f"/api/tasks/{tid}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "창B가 고친 문장이에요", "expected_updated_at": seen})
    assert r.status_code == 409
    assert r.json()["detail"] == "다른 창에서 먼저 고쳤어요. 새로 불러온 뒤 다시 고쳐 주세요."
    assert _get(client, employer_token, tid)["steps"][0]["sentence"] == "창A가 고친 문장이에요"
    # 같은 창(최신 값)은 저장된다.
    nxt = _get(client, employer_token, tid)["updated_at"]
    r = client.post(f"/api/tasks/{tid}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "창A가 또 고친 문장이에요", "expected_updated_at": nxt})
    assert r.status_code == 200, r.text


def test_patch_race_same_expected_one_wins(client, employer_token, monkeypatch):
    """1회차 검증: 같은 expected로 거의 동시에 온 두 저장 중 하나만 통과한다(음성 합성 동안 다른 창이 먼저 커밋)."""
    import threading
    import time
    task = _create(client, employer_token, ["상자를 옮겨요"])
    tid, sid, seen = task["id"], task["steps"][0]["id"], task["updated_at"]

    def slow(text, scope):
        time.sleep(1.0)
        return None
    monkeypatch.setattr(main, "synthesize_tts", slow)
    out = {}

    def a():
        out["a"] = _patch(client, employer_token, tid, sid, sentence="창A 문장이에요",
                          expected_updated_at=seen).status_code

    def b():
        time.sleep(0.3)
        out["b"] = _patch(client, employer_token, tid, sid, sentence="창B 문장이에요", defer_media=True,
                          expected_updated_at=seen).status_code
    ta, tb = threading.Thread(target=a), threading.Thread(target=b)
    ta.start(); tb.start(); ta.join(); tb.join()
    assert out == {"a": 409, "b": 200}
    assert _get(client, employer_token, tid)["steps"][0]["sentence"] == "창B 문장이에요"


def test_blank_sentence_422(client, employer_token):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    r = _patch(client, employer_token, task["id"], task["steps"][0]["id"], sentence="   ", defer_media=True)
    assert r.status_code == 422


def test_audio_only_change_keeps_task_updated_at(client, employer_token, tmp_path, monkeypatch):
    """[목소리 듣기]로 음성만 만든 것은 고친 것이 아니다(다른 창 자동 저장이 이유 없이 409가 되지 않게)."""
    task = _create(client, employer_token, ["상자를 옮겨요"])
    sid = task["steps"][0]["id"]
    r = _patch(client, employer_token, task["id"], sid, sentence="상자를 들어요", defer_media=True)
    before = r.json()["task_updated_at"]
    monkeypatch.setattr(step_audio, "synthesize_tts", _fake_tts_file([]))
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/tts", headers=auth(employer_token))
    assert r.status_code == 200 and r.json()["tts_url"]
    assert _get(client, employer_token, task["id"])["updated_at"] == before
    assert _patch(client, employer_token, task["id"], sid, sentence="상자를 내려요", defer_media=True,
                  expected_updated_at=before).status_code == 200


# --- 나누기 확인(needs_review) ------------------------------------------------------------------

def test_create_forces_needs_review_false(client, employer_token):
    task = _create(client, employer_token, [
        {"sentence": "상자를 옮겨요", "split": {"source": "model", "needs_review": True, "original_span": "상자를"}}])
    assert task["steps"][0]["split"]["needs_review"] is False
    with SessionLocal() as db:
        assert db.get(Step, task["steps"][0]["id"]).split_needs_review is False
    check = client.get(f"/api/tasks/{task['id']}/send-check", headers=auth(employer_token)).json()
    row = next(b for b in check["blocking"] if b["code"] == "unreviewed_split")
    assert row["total"] == 0


def test_editor_rewrite_split_send_ok(client, employer_token, worker):
    """편집기에서 저장하며 나눠도(자동 분할) 나눈 문장 확인 없이 보낼 수 있다."""
    task = _create(client, employer_token, ["상자를 옮겨요"])
    sid = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "상자를 옮기고 수량을 확인하세요"})
    assert r.status_code == 200, r.text
    assert len(r.json()["split_step_ids"]) == 2
    steps = r.json()["task"]["steps"]
    assert all(s["split"] == {"source": "model", "needs_review": False,
                              "original_span": "상자를 옮기고 수량을 확인하세요"} for s in steps)
    give_pictures(client, employer_token, task["id"])
    check = client.get(f"/api/tasks/{task['id']}/send-check", headers=auth(employer_token)).json()
    assert check["ok"] is True
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200


def test_old_unreviewed_split_blocks_until_saved(client, employer_token, worker):
    """옛 데이터 방어: needs_review가 남은 단계는 막고, 문장을 저장하면 풀린다."""
    task = _create(client, employer_token, ["상자를 옮겨요", "손을 씻어요"])
    give_pictures(client, employer_token, task["id"])
    sid = task["steps"][1]["id"]
    with SessionLocal() as db:
        db.get(Step, sid).split_needs_review = True
        db.commit()
    check = client.get(f"/api/tasks/{task['id']}/send-check", headers=auth(employer_token)).json()
    row = next(b for b in check["blocking"] if b["code"] == "unreviewed_split")
    assert row == {"code": "unreviewed_split", "done": 0, "total": 1, "step_ids": [sid]} and check["ok"] is False
    r = _send(client, employer_token, task["id"], [worker["id"]])
    assert r.status_code == 422 and r.json()["step_ids"] == [sid]
    assert _patch(client, employer_token, task["id"], sid, sentence="손을 닦아요").status_code == 200
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200


# --- 음성: 보낼 때 미리 합성(트랜잭션 밖) ----------------------------------------------------------

def _fake_tts_file(calls, during=None):
    tts_dir = Path(os.environ["TTS_CACHE_DIR"])

    def fake(text, scope):
        calls.append(text)
        if during is not None:
            during()
        tts_dir.mkdir(parents=True, exist_ok=True)
        key = uuid.uuid4().hex + ".mp3"
        (tts_dir / key).write_bytes(b"ID3fake")
        return key
    return fake


def _db_file() -> str:
    return os.environ["DATABASE_URL"].removeprefix("sqlite:///")


def test_send_tts_outside_transaction(client, employer_token, worker, monkeypatch):
    task = _create(client, employer_token, ["상자를 옮겨요", "손을 씻어요"])
    give_pictures(client, employer_token, task["id"])
    sid = task["steps"][0]["id"]
    assert _patch(client, employer_token, task["id"], sid, sentence="상자를 들어요", defer_media=True).status_code == 200
    wrote = []

    def other_connection_writes():
        # 합성하는 동안 다른 연결(근로자 기기의 기록 저장 같은)이 바로 쓸 수 있어야 한다(잠금 대기 0.2초 안에).
        conn = sqlite3.connect(_db_file(), timeout=0.2)
        try:
            conn.execute("UPDATE workers SET note = note WHERE id = ?", (worker["id"],))
            conn.commit()
            wrote.append(True)
        finally:
            conn.close()

    calls = []
    monkeypatch.setattr(step_audio, "synthesize_tts", _fake_tts_file(calls, other_connection_writes))
    r = _send(client, employer_token, task["id"], [worker["id"]])
    assert r.status_code == 200, r.text
    assert calls == ["상자를 들어요"] and wrote == [True]  # 바뀐 단계만 합성
    with SessionLocal() as db:
        step = db.get(Step, sid)
        assert step.tts_stale is False and step.tts_media_id
        v = db.scalars(select(TaskVersion).where(TaskVersion.task_id == task["id"])).one()
        assert v.steps[0].tts_media_id == step.tts_media_id
    card = next(c for c in client.get("/api/worker/me/today", headers=auth(worker["token"])).json()
                if c["task_id"] == task["id"])
    assert card["steps"][0]["tts_audio_url"]


def test_send_tts_failure_still_sends(client, employer_token, worker, monkeypatch):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    give_pictures(client, employer_token, task["id"])
    sid = task["steps"][0]["id"]
    _patch(client, employer_token, task["id"], sid, sentence="상자를 들어요", defer_media=True)

    def boom(text, scope):
        raise RuntimeError("합성 실패")
    monkeypatch.setattr(step_audio, "synthesize_tts", boom)
    r = _send(client, employer_token, task["id"], [worker["id"]])
    assert r.status_code == 200, r.text
    card = next(c for c in client.get("/api/worker/me/today", headers=auth(worker["token"])).json()
                if c["task_id"] == task["id"])
    assert card["steps"][0]["sentence"] == "상자를 들어요" and card["steps"][0]["tts_audio_url"] is None


def test_blocked_send_does_not_synthesize(client, employer_token, worker, monkeypatch):
    task = _create(client, employer_token, ["상자를 옮겨요"])  # 그림 없음 → 422
    sid = task["steps"][0]["id"]
    _patch(client, employer_token, task["id"], sid, sentence="상자를 들어요", defer_media=True)
    calls = []
    monkeypatch.setattr(step_audio, "synthesize_tts", _fake_tts_file(calls))
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 422
    assert calls == []


def test_tts_endpoint(client, employer_token, monkeypatch):
    task = _create(client, employer_token, ["상자를 옮겨요"])
    sid = task["steps"][0]["id"]
    calls = []
    monkeypatch.setattr(step_audio, "synthesize_tts", _fake_tts_file(calls))
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/tts", headers=auth(employer_token))
    assert r.status_code == 200 and r.json()["tts_url"].startswith("http")
    # 이미 있으면 다시 만들지 않는다.
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/tts", headers=auth(employer_token))
    assert r.status_code == 200 and r.json()["tts_url"] and calls == ["상자를 옮겨요"]
    # 합성 실패면 null(기기 음성이 대신).
    monkeypatch.setattr(step_audio, "synthesize_tts", lambda t, s: None)
    _patch(client, employer_token, task["id"], sid, sentence="상자를 들어요", defer_media=True)
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/tts", headers=auth(employer_token))
    assert r.status_code == 200 and r.json() == {"tts_url": None}


# --- 미리보기 -----------------------------------------------------------------------------------

def test_preview_leaves_no_records(client, employer_token, worker):
    task = _create(client, employer_token, ["칼로 상자를 열어요", "손을 씻어요"])
    give_pictures(client, employer_token, task["id"])
    _patch(client, employer_token, task["id"], task["steps"][1]["id"], group_break=True)

    def counts():
        with SessionLocal() as db:
            return tuple(db.scalar(select(func.count()).select_from(m))
                         for m in (Assignment, PerformanceLog, HelpRequest, AccessAuditLog, TaskVersion))
    before = counts()
    r = client.get(f"/api/tasks/{task['id']}/preview", headers=auth(employer_token))
    assert r.status_code == 200, r.text
    assert counts() == before
    body = r.json()
    assert body["title"] == task["title"]
    assert [s["safety_flag"] for s in body["steps"]] == [True, False]
    assert [s["group_break"] for s in body["steps"]] == [False, True]
    assert all("lint" not in s and "safety" not in s for s in body["steps"])
    # 근로자 토큰으로는 볼 수 없다(사업주 토큰).
    assert client.get(f"/api/tasks/{task['id']}/preview", headers=auth(worker["token"])).status_code in (401, 403)


# --- 고정 문장(규칙 엔진 기록) ----------------------------------------------------------------------

def test_fixed_sentence_six_auto_high(client, employer_token, worker, monkeypatch):
    """ai_service 규칙 엔진(GPT·임베딩 없음)의 실제 응답 기록으로: 나누기 → 초안 → 6단계 모두 auto_high → 일괄 확인
    → 보내기. 1단계는 자동 조심 표시(보내기 시트 경고 1개, 막지 않음). 기록은 ai_service/tests/test_fixed_sentence.py."""
    rec = json.loads((FIXTURES / "fixed_sentence_rule_recorded.json").read_text(encoding="utf-8"))
    fixed = (Path(__file__).resolve().parents[2] / "ai_service" / "tests" / "test_fixed_sentence.py")
    if fixed.exists():
        assert rec["raw_input"] in fixed.read_text(encoding="utf-8")
    map_calls = []
    monkeypatch.setattr(ai_client, "decompose", lambda raw, context=None, **kw: rec["decompose"])

    def recorded_map(keywords, context=None):
        map_calls.append((keywords, context))
        entry = rec["map_symbols"][context["sentence"]]
        assert keywords == entry["keywords"]
        return entry["result"]
    monkeypatch.setattr(ai_client, "map_symbols", recorded_map)

    preview = client.post("/api/tasks/split-preview", headers=auth(employer_token),
                          json={"raw_input": rec["raw_input"]})
    assert preview.status_code == 200, preview.text
    rows = preview.json()["steps"]
    assert len(rows) == 6 and [r["safety_flag"] for r in rows] == [True] + [False] * 5
    r = client.post("/api/tasks", headers=auth(employer_token), json={
        "raw_input": rec["raw_input"], "title": preview.json()["task_title"], "job": preview.json()["job"],
        "steps": [{"sentence": row["sentence"], "action_type": row["action_type"],
                   "symbol_query": row["symbol_query"], "safety_flag": row["safety_flag"],
                   "split": {"source": "rule", "original_span": row["source_text"]}} for row in rows]})
    assert r.status_code == 201, r.text
    task = r.json()
    assert len(map_calls) == 6
    assert [s["picture_state"] for s in task["steps"]] == ["auto_high"] * 6
    assert all(s["lint"] == [] for s in task["steps"])
    check = client.get(f"/api/tasks/{task['id']}/send-check", headers=auth(employer_token)).json()
    blocking = {b["code"]: b for b in check["blocking"]}
    assert blocking["unconfirmed_auto"]["done"] == 0 and blocking["unconfirmed_auto"]["total"] == 6
    _confirm_all(client, employer_token, task["id"])
    check = client.get(f"/api/tasks/{task['id']}/send-check", headers=auth(employer_token)).json()
    assert check["ok"] is True
    assert {w["code"]: w["count"] for w in check["warnings"]} == {"too_long": 0, "command_tone": 0,
                                                                  "auto_caution": 1}
    r = _send(client, employer_token, task["id"], [worker["id"]])
    assert r.status_code == 200 and r.json()["results"][0]["outcome"] == "created"
    card = next(c for c in client.get("/api/worker/me/today", headers=auth(worker["token"])).json()
                if c["task_id"] == task["id"])
    assert [s["safety_flag"] for s in card["steps"]] == [True] + [False] * 5


def _review_state(client, token, task_id):
    return [(s["sentence"], s["safety"]["flag"], s["safety"]["source"], s["safety"]["note"], s["group_break"])
            for s in _get(client, token, task_id)["steps"]]


def _fake_split(monkeypatch, parts):
    monkeypatch.setattr(ai_client, "split_hint", lambda s: True)
    monkeypatch.setattr(ai_client, "decompose", lambda raw, ctx=None, **k: {"steps": [
        {"sentence": p, "action_type": "move", "symbol_query": ["상자"]} for p in parts]})


def test_split_and_undo_keep_manual_safety_note_and_group_break(client, employer_token, monkeypatch):
    """2회차 검증: 저장하며 나누기와 [되돌리기]가 사업주가 정한 조심 스위치(켬)·메모·묶음 경계를 지우지 않는다."""
    task = _create(client, employer_token, ["상자를 옮겨요", "선반을 정리해요"])
    tid = task["id"]
    s1 = task["steps"][0]["id"]
    assert _patch(client, employer_token, tid, s1, safety_flag=True, safety_note="허리를 펴요",
                  group_break=True).status_code == 200
    _fake_split(monkeypatch, ["상자를 들어요", "상자를 선반에 놓아요"])
    r = client.post(f"/api/tasks/{tid}/steps/{s1}/rewrite", headers=auth(employer_token),
                    json={"sentence": "상자를 들고 선반에 놓아요"})
    assert r.status_code == 200, r.text
    ids = r.json()["split_step_ids"]
    assert len(ids) == 2
    assert _review_state(client, employer_token, tid)[:2] == [
        ("상자를 들어요", True, "manual", "허리를 펴요", True),
        ("상자를 선반에 놓아요", True, "manual", "허리를 펴요", False)]
    r = client.post(f"/api/tasks/{tid}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": ids, "sentence": "상자를 들고 선반에 놓아요", "action_type": "move"})
    assert r.status_code == 200, r.text
    assert _review_state(client, employer_token, tid)[0] == (
        "상자를 들고 선반에 놓아요", True, "manual", "허리를 펴요", True)


def test_split_and_undo_keep_manual_off(client, employer_token, monkeypatch):
    """2회차 검증: 사업주가 끈 조심 스위치는 나눈 뒤에도, 되돌린 뒤에도 자동으로 다시 켜지지 않는다."""
    task = _create(client, employer_token, ["칼을 씻어요"])
    tid, s1 = task["id"], task["steps"][0]["id"]
    assert _patch(client, employer_token, tid, s1, safety_flag=False).status_code == 200
    _fake_split(monkeypatch, ["칼을 씻어요", "칼을 말려요"])
    r = client.post(f"/api/tasks/{tid}/steps/{s1}/rewrite", headers=auth(employer_token),
                    json={"sentence": "칼을 씻고 말려요"})
    ids = r.json()["split_step_ids"]
    assert [(f, src) for _, f, src, _, _ in _review_state(client, employer_token, tid)] == [
        (False, "manual"), (False, "manual")]
    r = client.post(f"/api/tasks/{tid}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": ids, "sentence": "칼을 씻고 말려요", "action_type": "clean"})
    assert r.status_code == 200, r.text
    assert [(f, src) for _, f, src, _, _ in _review_state(client, employer_token, tid)] == [(False, "manual")]


def test_split_without_manual_choice_stays_auto(client, employer_token, monkeypatch):
    """사업주가 손대지 않은 단계는 나눈 뒤 새 문장마다 자동 제안을 다시 매긴다."""
    task = _create(client, employer_token, ["상자를 옮겨요"])
    tid, s1 = task["id"], task["steps"][0]["id"]
    _fake_split(monkeypatch, ["칼을 들어요", "상자를 놓아요"])
    r = client.post(f"/api/tasks/{tid}/steps/{s1}/rewrite", headers=auth(employer_token),
                    json={"sentence": "칼을 들고 상자를 놓아요"})
    assert r.status_code == 200, r.text
    assert [(f, src) for _, f, src, _, _ in _review_state(client, employer_token, tid)] == [(True, "auto"), (False, "")]


def test_safety_keywords_round3_fire_false_positives_and_compounds():
    """3회차 검증: '때문에'·'불과 N분'을 불로 보지 않고, 불 합성어 + '가'(모닥불가)는 놓치지 않는다."""
    for sentence in ("불만 때문에 전화해요", "출입 불가 때문에 돌아가요", "불과 5분만 기다려요", "불과 3개만 남았어요",
                     "출입 불가", "불가능해요", "불가피해요", "불만족해요"):
        assert safety_rules.matched_keyword(sentence) is None, sentence
    for sentence in ("불만 때면 돼요", "불을 때요", "모닥불가에 앉지 않아요", "숯불가에서 기다려요", "장작불가로 가지 않아요",
                     "화롯불가에 앉아요", "난롯불을 꺼요", "불끄고 나가요", "불만 끄고 나가요", "가스불만 꺼요"):
        assert safety_rules.matched_keyword(sentence) == "불", sentence


def test_rewrite_split_uses_ai_safety_flags(client, employer_token, monkeypatch):
    """3회차 검증: 저장하며 나눌 때 AI 분해가 준 safety_flags를 직무 만들기처럼 자동 조심 제안에 쓴다."""
    task = _create(client, employer_token, ["선반 위 상자를 내려요"])
    tid, s1 = task["id"], task["steps"][0]["id"]
    monkeypatch.setattr(ai_client, "split_hint", lambda s: True)
    monkeypatch.setattr(ai_client, "decompose", lambda raw, ctx=None, **k: {"steps": [
        {"sentence": "발판에 올라가요", "action_type": "move", "symbol_query": ["발판"], "safety_flags": ["높은 곳"]},
        {"sentence": "상자를 내려요", "action_type": "move", "symbol_query": ["상자"], "safety_flags": ["높은 곳"]}]})
    r = client.post(f"/api/tasks/{tid}/steps/{s1}/rewrite", headers=auth(employer_token),
                    json={"sentence": "발판에 올라가서 상자를 내려요"})
    assert r.status_code == 200, r.text
    assert len(r.json()["split_step_ids"]) == 2
    assert [(s[1], s[2]) for s in _review_state(client, employer_token, tid)] == [(True, "auto"), (True, "auto")]
    check = client.get(f"/api/tasks/{tid}/send-check", headers=auth(employer_token)).json()
    assert {w["code"]: w["count"] for w in check["warnings"]}["auto_caution"] == 2
    # 단계 추가로 나눌 때도 같다.
    r = client.post(f"/api/tasks/{tid}/steps", headers=auth(employer_token),
                    json={"sentence": "발판에 올라가서 상자를 내려요"})
    assert r.status_code == 201, r.text
    assert [(s[1], s[2]) for s in _review_state(client, employer_token, tid)][2:] == [(True, "auto"), (True, "auto")]
