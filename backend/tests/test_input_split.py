"""입력 화면에서 나누기(미리보기 → 확인한 단계로 초안 만들기)와 편집기 저장 시 나누기·되돌리기.

AI 하네스(ai_client)는 conftest가 목으로 바꾼다. 네트워크는 부르지 않는다.
"""
import ai_client
from conftest import auth, publish, delete_worker


def _preview_response(raw_input, context=None, **kw):
    return {
        "task_title": "컵 정리",
        "job": "cafe",
        "steps": [
            {"order": 1, "sentence": "앞치마를 입어요.", "action_type": "wear",
             "symbol_query": ["앞치마"]},
            {"order": 2, "sentence": "컵을 씻어요.", "action_type": "clean",
             "symbol_query": ["컵", "씻다"], "split_group": 1, "split_check": True,
             "source_text": "컵 씻어서 건조대에 올려 놔"},
            {"order": 3, "sentence": "컵을 건조대에 올려요.", "action_type": "move",
             "keywords": [{"term": "건조대", "pos": "noun"}], "split_group": 1, "split_check": True,
             "source_text": "컵 씻어서 건조대에 올려 놔"},
        ],
    }


def test_split_preview_returns_steps_without_creating_task(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "decompose", _preview_response)
    before = client.get("/api/tasks", headers=auth(employer_token)).json()
    r = client.post("/api/tasks/split-preview", headers=auth(employer_token),
                    json={"raw_input": "앞치마 입고 컵 씻어서 건조대에 올려 놔"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_title"] == "컵 정리"
    assert body["job"] == "cafe"
    steps = body["steps"]
    assert [s["sentence"] for s in steps] == ["앞치마를 입어요.", "컵을 씻어요.", "컵을 건조대에 올려요."]
    assert [s["order"] for s in steps] == [1, 2, 3]
    assert steps[0]["split_group"] is None and steps[0]["split_check"] is False
    assert steps[0]["source_text"] is None
    assert steps[1]["split_group"] == 1 and steps[1]["split_check"] is True
    assert steps[2]["source_text"] == "컵 씻어서 건조대에 올려 놔"
    # symbol_query가 없으면 keywords의 term을 쓴다
    assert steps[2]["symbol_query"] == ["건조대"]
    # 직무는 만들지 않는다
    assert client.get("/api/tasks", headers=auth(employer_token)).json() == before


def test_split_preview_tolerates_missing_or_bad_split_fields(client, employer_token, monkeypatch):
    def bad(raw_input, context=None, **kw):
        return {"task_title": "t", "steps": [
            {"order": 1, "sentence": "상자를 옮기세요.", "split_group": True, "split_check": "yes",
             "source_text": 3},
            {"order": 2, "sentence": "   "},
        ]}
    monkeypatch.setattr(ai_client, "decompose", bad)
    r = client.post("/api/tasks/split-preview", headers=auth(employer_token), json={"raw_input": "상자"})
    assert r.status_code == 200, r.text
    steps = r.json()["steps"]
    assert len(steps) == 1  # 빈 문장 줄은 버린다
    assert steps[0]["split_group"] is None
    assert steps[0]["split_check"] is False
    assert steps[0]["source_text"] is None


def test_split_preview_requires_employer(client, worker_token):
    assert client.post("/api/tasks/split-preview", json={"raw_input": "x"}).status_code == 401
    r = client.post("/api/tasks/split-preview", headers=auth(worker_token), json={"raw_input": "x"})
    assert r.status_code == 403


def test_split_preview_ai_failure_is_502_without_internal_detail(client, employer_token, monkeypatch):
    def boom(raw_input, context=None, **kw):
        raise RuntimeError("connect to http://ai-internal:8001 refused")
    monkeypatch.setattr(ai_client, "decompose", boom)
    r = client.post("/api/tasks/split-preview", headers=auth(employer_token), json={"raw_input": "상자"})
    assert r.status_code == 502
    assert "ai-internal" not in r.text


def test_split_preview_masks_worker_names(client, employer_token, monkeypatch):
    seen = {}

    def spy(raw_input, context=None, **kw):
        seen["raw"] = raw_input
        return {"task_title": "t", "steps": [
            {"order": 1, "sentence": raw_input.removesuffix(" 상자 주기") + "에게 상자를 주세요.",
             "source_text": raw_input}]}
    monkeypatch.setattr(ai_client, "decompose", spy)
    w = client.post("/api/workers", headers=auth(employer_token),
                    json={"display_name": "홍길순", "access_code": "908172"})
    assert w.status_code == 201, w.text
    r = client.post("/api/tasks/split-preview", headers=auth(employer_token),
                    json={"raw_input": "홍길순 상자 주기"})
    assert r.status_code == 200, r.text
    assert "홍길순" not in seen["raw"]
    # 화면에는 실명으로 되돌려 보여 준다
    assert r.json()["steps"][0]["sentence"].startswith("홍길순")
    assert r.json()["steps"][0]["source_text"] == "홍길순 상자 주기"
    delete_worker(client, w.json()['id'], auth(employer_token))


def test_create_task_with_confirmed_steps_skips_decompose(client, employer_token, monkeypatch):
    def must_not_call(raw_input, context=None, **kw):
        raise AssertionError("확인한 단계가 있으면 다시 나누지 않는다")
    monkeypatch.setattr(ai_client, "decompose", must_not_call)
    searched = []

    def spy_map(keywords, context=None):
        searched.append((list(keywords), (context or {}).get("sentence")))
        return {"symbols": [{"keyword": k, "image_url": None, "source": "fallback", "confidence": 0.0,
                             "needs_fallback": True, "reason": "no_candidate", "candidates": []}
                            for k in keywords]}
    monkeypatch.setattr(ai_client, "map_symbols", spy_map)
    r = client.post("/api/tasks", headers=auth(employer_token), json={
        "raw_input": "앞치마 입고 컵 씻어서 건조대에 올려 놔",
        "title": "컵 정리", "job": "cafe",
        "steps": [
            {"sentence": "앞치마를 입어요.", "action_type": "wear", "symbol_query": ["앞치마"]},
            {"sentence": "  컵을 씻고 건조대에 올려요.  "},
        ],
    })
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["title"] == "컵 정리"
    assert [s["sentence"] for s in task["steps"]] == ["앞치마를 입어요.", "컵을 씻고 건조대에 올려요."]
    assert [s["order"] for s in task["steps"]] == [1, 2]
    assert task["steps"][0]["action_type"] == "wear"
    assert task["steps"][1]["action_type"] == "other"
    # 확인한 문장으로 그림을 찾는다: 받은 검색어 그대로, 없으면 문장에서 뽑은 낱말
    assert (["앞치마"], "앞치마를 입어요.") in searched
    assert (["컵을", "씻고", "건조대에", "올려요"], "컵을 씻고 건조대에 올려요.") in searched


def test_create_task_without_steps_still_decomposes(client, employer_token):
    r = client.post("/api/tasks", headers=auth(employer_token), json={"raw_input": "상자 옮기고 수량 확인"})
    assert r.status_code == 201, r.text
    assert [s["sentence"] for s in r.json()["steps"]] == ["상자를 옮기세요.", "수량을 확인하세요."]


def test_create_task_rejects_blank_confirmed_step(client, employer_token):
    r = client.post("/api/tasks", headers=auth(employer_token), json={
        "raw_input": "x", "steps": [{"sentence": "   "}]})
    assert r.status_code == 422
    r = client.post("/api/tasks", headers=auth(employer_token), json={"raw_input": "x", "steps": []})
    assert r.status_code == 422


def _make_task(client, token, sentences):
    r = client.post("/api/tasks", headers=auth(token), json={
        "raw_input": " ".join(sentences), "steps": [{"sentence": s} for s in sentences]})
    assert r.status_code == 201, r.text
    return r.json()


def _two_actions(raw_input, context=None, **kw):
    return {"task_title": "t", "steps": [
        {"order": 1, "sentence": "컵을 씻어요.", "action_type": "clean", "symbol_query": ["컵"],
         "split_group": 1, "split_check": False, "source_text": raw_input},
        {"order": 2, "sentence": "컵을 건조대에 올려요.", "action_type": "move", "symbol_query": ["건조대"],
         "split_group": 1, "split_check": False, "source_text": raw_input},
    ]}


def test_rewrite_splits_two_action_sentence_and_merge_undoes(client, employer_token, monkeypatch):
    task = _make_task(client, employer_token, ["앞치마를 입어요.", "컵을 씻어요.", "손을 씻어요."])
    monkeypatch.setattr(ai_client, "decompose", _two_actions)
    target = task["steps"][1]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{target}/rewrite", headers=auth(employer_token),
                    json={"sentence": "컵 씻어서 건조대에 올려요"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sentence"] == "컵 씻어서 건조대에 올려요"
    steps = body["task"]["steps"]
    assert [s["sentence"] for s in steps] == ["앞치마를 입어요.", "컵을 씻어요.", "컵을 건조대에 올려요.", "손을 씻어요."]
    assert [s["order"] for s in steps] == [1, 2, 3, 4]
    assert body["split_step_ids"] == [steps[1]["id"], steps[2]["id"]]
    assert target not in {s["id"] for s in steps}

    # 되돌리기: 사업주가 적은 문장 한 단계로 합친다
    r = client.post(f"/api/tasks/{task['id']}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": body["split_step_ids"], "sentence": body["sentence"]})
    assert r.status_code == 200, r.text
    steps = r.json()["steps"]
    assert [s["sentence"] for s in steps] == ["앞치마를 입어요.", "컵 씻어서 건조대에 올려요", "손을 씻어요."]
    assert [s["order"] for s in steps] == [1, 2, 3]


def test_rewrite_keeps_one_step_when_ai_says_one_action(client, employer_token, monkeypatch):
    task = _make_task(client, employer_token, ["앞치마를 입어요.", "컵을 씻어요."])

    def one(raw_input, context=None, **kw):
        return {"task_title": "t", "steps": [{"order": 1, "sentence": "컵을 깨끗이 씻어요."}]}
    monkeypatch.setattr(ai_client, "decompose", one)
    sid = task["steps"][1]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "컵을 깨끗하게 씻어요"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["split_step_ids"] == []
    # 한 동작이면 AI가 다듬은 문장이 아니라 사업주가 적은 문장을 그대로 저장한다
    assert body["task"]["steps"][1] == {**body["task"]["steps"][1], "id": sid, "sentence": "컵을 깨끗하게 씻어요"}


def test_rewrite_does_not_split_uncertain_or_on_ai_failure(client, employer_token, monkeypatch):
    task = _make_task(client, employer_token, ["컵을 씻어요.", "손을 씻어요."])
    sid = task["steps"][0]["id"]

    def uncertain(raw_input, context=None, **kw):
        out = _two_actions(raw_input)
        out["steps"][1]["split_check"] = True
        return out
    monkeypatch.setattr(ai_client, "decompose", uncertain)
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "컵을 헹궈서 엎어 두세요"})
    assert r.status_code == 200 and r.json()["split_step_ids"] == []
    assert len(r.json()["task"]["steps"]) == 2

    def boom(raw_input, context=None, **kw):
        raise RuntimeError("down")
    monkeypatch.setattr(ai_client, "decompose", boom)
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "컵 씻고 말려요"})
    assert r.status_code == 200, r.text
    assert r.json()["split_step_ids"] == []
    assert r.json()["task"]["steps"][0]["sentence"] == "컵 씻고 말려요"


def test_rewrite_splits_published_task_too(client, employer_token, monkeypatch):
    """(2a-0) 보낸 직무도 저장하며 나눈다(예전에는 단계 id가 바뀌면 받은 근로자의 기록이 끊겨서 막았다).
    근로자는 보낸 버전 단계를 보고 로그·도움은 버전 단계를 가리키므로, 편집 단계가 바뀌어도 진행 기록은 그대로다."""
    task = _make_task(client, employer_token, ["컵을 씻어요."])
    # 그림 없는 단계는 보낼 수 없다(0차) — 그림을 붙이고 보낸다.
    assert publish(client, employer_token, task["id"]).status_code == 200
    monkeypatch.setattr(ai_client, "decompose", _two_actions)
    sid = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "컵 씻어서 건조대에 올려요"})
    assert r.status_code == 200
    assert len(r.json()["split_step_ids"]) == 2
    assert [s["id"] for s in r.json()["task"]["steps"]] == r.json()["split_step_ids"]


def test_rewrite_and_merge_reject_other_employers_and_bad_input(client, employer_token, monkeypatch):
    task = _make_task(client, employer_token, ["a 하세요.", "b 하세요.", "c 하세요."])
    ids = [s["id"] for s in task["steps"]]
    # 붙어 있지 않은 단계는 합치지 않는다
    r = client.post(f"/api/tasks/{task['id']}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": [ids[0], ids[2]], "sentence": "합친 문장"})
    assert r.status_code == 409
    r = client.post(f"/api/tasks/{task['id']}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": [ids[0], "nope"], "sentence": "합친 문장"})
    assert r.status_code == 404
    r = client.post(f"/api/tasks/{task['id']}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": [ids[0], ids[0]], "sentence": "합친 문장"})
    assert r.status_code == 400
    r = client.post(f"/api/tasks/{task['id']}/steps/{ids[0]}/rewrite", headers=auth(employer_token),
                    json={"sentence": "   "})
    assert r.status_code == 422
    r = client.post(f"/api/tasks/{task['id']}/steps/missing/rewrite", headers=auth(employer_token),
                    json={"sentence": "x"})
    assert r.status_code == 404
    # 내 직무가 아니면(없는 직무 포함) 찾을 수 없다고 답한다
    r = client.post(f"/api/tasks/no-such-task/steps/{ids[0]}/rewrite", headers=auth(employer_token),
                    json={"sentence": "x"})
    assert r.status_code == 404


# ---- 1차 검증 반영 -----------------------------------------------------------------------------
import io  # noqa: E402

from PIL import Image  # noqa: E402

import main  # noqa: E402
import ratelimit  # noqa: E402


def _jpeg() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(b, "JPEG")
    return b.getvalue()


def test_merge_is_allowed_after_publish(client, employer_token, monkeypatch):
    """(2a-0) 보낸 뒤에도 [되돌리기](합치기)가 된다(예전 409 해제). 진행 기록은 버전 단계에 있어 지워지지 않고,
    합친 단계의 그림은 새로 붙어 확인 전 상태라 다음 보내기 검사가 다시 확인을 요구한다."""
    task = _make_task(client, employer_token, ["컵을 씻어요."])
    monkeypatch.setattr(ai_client, "decompose", _two_actions)
    sid = task["steps"][0]["id"]
    split = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                        json={"sentence": "컵 씻어서 건조대에 올려요"}).json()
    assert len(split["split_step_ids"]) == 2
    assert publish(client, employer_token, task["id"]).status_code == 200
    r = client.post(f"/api/tasks/{task['id']}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": split["split_step_ids"], "sentence": split["sentence"]})
    assert r.status_code == 200
    steps = r.json()["steps"]
    assert len(steps) == 1 and steps[0]["sentence"] == split["sentence"]
    assert steps[0]["picture_state"] != "confirmed"


def test_split_on_save_keeps_uploaded_photo_and_undo_brings_it_back(client, employer_token, monkeypatch):
    task = _make_task(client, employer_token, ["컵을 씻어요.", "손을 씻어요."])
    sid = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/photo",
                    files={"file": ("p.jpg", _jpeg(), "image/jpeg")}, headers=auth(employer_token))
    assert r.status_code == 200, r.text
    monkeypatch.setattr(ai_client, "decompose", _two_actions)
    body = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                       json={"sentence": "컵 씻어서 건조대에 올려요"}).json()
    steps = body["task"]["steps"]
    assert [s["symbol_source"] for s in steps[:2]] == ["photo", "fallback"]
    photo_url = steps[0]["symbol_url"]
    assert photo_url
    # 사진 파일은 놓아주지 않았다(음성만)
    kept = client.get(photo_url)
    assert kept.status_code == 200
    # 되돌리기: 사진과 나누기 전 동작 종류가 돌아온다
    r = client.post(f"/api/tasks/{task['id']}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": body["split_step_ids"], "sentence": body["sentence"], "action_type": "clean"})
    assert r.status_code == 200, r.text
    merged = r.json()["steps"][0]
    assert merged["symbol_source"] == "photo" and merged["action_type"] == "clean"
    assert client.get(merged["symbol_url"]).status_code == 200


def test_add_step_with_two_actions_is_split_with_undo_ids(client, employer_token, monkeypatch):
    task = _make_task(client, employer_token, ["앞치마를 입어요."])
    monkeypatch.setattr(ai_client, "decompose", _two_actions)
    r = client.post(f"/api/tasks/{task['id']}/steps", headers=auth(employer_token),
                    json={"sentence": "컵을 씻고 건조대에 올려요"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert [s["sentence"] for s in body["steps"]] == ["앞치마를 입어요.", "컵을 씻어요.", "컵을 건조대에 올려요."]
    assert [s["order"] for s in body["steps"]] == [1, 2, 3]
    assert body["split_step_ids"] == [body["steps"][1]["id"], body["steps"][2]["id"]]
    assert body["sentence"] == "컵을 씻고 건조대에 올려요"
    # 되돌리기는 편집기 저장 나누기와 같은 길
    r = client.post(f"/api/tasks/{task['id']}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": body["split_step_ids"], "sentence": body["sentence"]})
    assert [s["sentence"] for s in r.json()["steps"]] == ["앞치마를 입어요.", "컵을 씻고 건조대에 올려요"]


def test_one_action_edits_do_not_call_ai(client, employer_token, monkeypatch):
    # 겉모양으로 동작이 하나뿐인 문장(연결 꼴 없음)은 GPT 분해를 부르지 않는다 — 오타 고치기마다 기다리지 않게.
    task = _make_task(client, employer_token, ["컵을 씻어요."])
    calls = []

    def spy(raw_input, context=None, **kw):
        calls.append(kw)
        return _two_actions(raw_input)
    monkeypatch.setattr(ai_client, "decompose", spy)
    sid = task["steps"][0]["id"]
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "컵을 깨끗이 씻어요"})
    assert r.status_code == 200 and r.json()["split_step_ids"] == []
    r = client.post(f"/api/tasks/{task['id']}/steps", headers=auth(employer_token), json={"sentence": "손을 닦아요."})
    assert r.status_code == 201 and r.json()["split_step_ids"] == []
    assert calls == []
    # 연결 꼴이 있으면 부르고, 짧은 시간 제한을 준다
    client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                json={"sentence": "컵을 씻고 말려요"})
    assert calls and calls[0].get("timeout") == main._SPLIT_CHECK_TIMEOUT


def test_may_have_two_actions_surface_filter():
    for s in ("컵을 씻고 말려요", "컵을 씻어서 올려요", "빵을 집어 봉투에 담아요", "컵을 헹군 다음 엎어 두세요",
              "상자를 접어요, 테이프를 붙여요", "물을 꺼내 컵에 따라요"):
        assert main._may_have_two_actions(s), s
    for s in ("컵을 깨끗이 닦으세요", "손을 닦아요.", "바닥을 쓸어주세요."):
        assert not main._may_have_two_actions(s), s


def test_split_preview_is_rate_limited_per_employer(client, employer_token, monkeypatch):
    monkeypatch.setattr(ai_client, "decompose", _preview_response)
    monkeypatch.setattr(ratelimit.ai_split_throttle, "max_failures", 2)
    for _ in range(2):
        assert client.post("/api/tasks/split-preview", headers=auth(employer_token),
                           json={"raw_input": "컵 씻어"}).status_code == 200
    r = client.post("/api/tasks/split-preview", headers=auth(employer_token), json={"raw_input": "컵 씻어"})
    assert r.status_code == 429
    # 한도를 넘으면 편집기 저장은 나누기 확인 없이 그대로 저장한다(막지 않는다)
    task = _make_task(client, employer_token, ["컵을 씻어요."])
    sid = task["steps"][0]["id"]
    monkeypatch.setattr(ai_client, "decompose", _two_actions)
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "컵 씻어서 건조대에 올려요"})
    assert r.status_code == 200 and r.json()["split_step_ids"] == []


def test_confirmed_steps_total_length_is_capped(client, employer_token):
    from schemas import MAX_CONFIRMED_TOTAL
    n = MAX_CONFIRMED_TOTAL // 400 + 1
    r = client.post("/api/tasks", headers=auth(employer_token), json={
        "raw_input": "긴 직무", "steps": [{"sentence": "가" * 400} for _ in range(n)]})
    assert r.status_code == 422


# ---- 2차 검증 회귀 ------------------------------------------------------------------------------

def test_edited_confirmed_row_is_classified_not_saved_as_other(client, employer_token, monkeypatch):
    # 고친 줄은 {sentence}만 온다 → 규칙 분류기로 매긴다. 미리보기 값을 보낸 줄은 그대로 쓴다.
    seen = []

    def classify(sentence):
        seen.append(sentence)
        return "clean" if "쓸" in sentence or "닦" in sentence else "other"
    monkeypatch.setattr(ai_client, "classify_action", classify)
    r = client.post("/api/tasks", headers=auth(employer_token), json={
        "raw_input": "바닥을 쓸고 컵을 옮겨요", "steps": [
            {"sentence": "바닥을 쓸어 주세요"},
            {"sentence": "컵을 옮겨요", "action_type": "move", "symbol_query": ["컵"]}]})
    assert r.status_code == 201, r.text
    assert [s["action_type"] for s in r.json()["steps"]] == ["clean", "move"]
    assert seen == ["바닥을 쓸어 주세요"]


def test_validation_errors_are_korean_sentences(client, employer_token):
    r = client.post("/api/tasks", headers=auth(employer_token), json={
        "raw_input": "많은 줄", "steps": [{"sentence": f"컵 {i}번을 씻어요"} for i in range(31)]})
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str) and "30줄" in r.json()["detail"]
    r = client.post("/api/tasks", headers=auth(employer_token), json={
        "raw_input": "긴 줄", "steps": [{"sentence": "가" * 501}]})
    assert r.status_code == 422 and "500자" in r.json()["detail"]
    r = client.post("/api/tasks", headers=auth(employer_token), json={"raw_input": "   "})
    assert r.status_code == 422 and r.json()["detail"] == "직무 내용을 입력해 주세요."


def test_split_preview_over_step_cap_is_refused_in_korean(client, employer_token, monkeypatch):
    def many(raw_input, context=None, **kw):
        return {"task_title": "t", "steps": [{"order": i, "sentence": f"컵 {i}번을 씻으세요."} for i in range(40)]}
    monkeypatch.setattr(ai_client, "decompose", many)
    r = client.post("/api/tasks/split-preview", headers=auth(employer_token), json={"raw_input": "컵 씻기 " * 40})
    assert r.status_code == 422
    assert "30단계" in r.json()["detail"]


def test_editor_save_asks_rule_hint_before_gpt(client, employer_token, monkeypatch):
    # 규칙 동작 세기가 '하나'라 하면 겉모양('냉장고'의 '고')과 상관없이 GPT를 부르지 않는다.
    task = _make_task(client, employer_token, ["문을 닫아요."])
    sid = task["steps"][0]["id"]
    calls, hints = [], []

    def spy(raw_input, context=None, **kw):
        calls.append(raw_input)
        return _two_actions(raw_input)
    monkeypatch.setattr(ai_client, "decompose", spy)
    monkeypatch.setattr(ai_client, "split_hint", lambda s: hints.append(s) or False)
    for sentence in ("냉장고 문을 닫으세요", "계산대 위를 닦으세요", "덮개 안쪽을 닦으세요"):
        r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                        json={"sentence": sentence})
        assert r.status_code == 200 and r.json()["split_step_ids"] == []
    assert calls == [] and len(hints) == 3
    # 규칙이 '둘일 수 있다'고 하면 부른다.
    monkeypatch.setattr(ai_client, "split_hint", lambda s: True)
    r = client.post(f"/api/tasks/{task['id']}/steps/{sid}/rewrite", headers=auth(employer_token),
                    json={"sentence": "컵을 씻어서 건조대에 올려요"})
    assert calls and len(r.json()["split_step_ids"]) == 2
