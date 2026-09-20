"""백엔드 API 통합 테스트 — 인증/인가/소유권/stuck/업서트/입력검증."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from conftest import auth  # noqa: E402
from auth import make_token, verify_password, hash_password, verify_token  # noqa: E402


# ---------- 인증 단위 ----------
def test_password_hash_roundtrip():
    h = hash_password("secret123")
    assert verify_password("secret123", h)
    assert not verify_password("wrong", h)


def test_token_tamper_rejected():
    tok = make_token("emp-x", "employer")
    assert verify_token(tok) is not None
    assert verify_token(tok[:-2] + ("aa" if not tok.endswith("aa") else "bb")) is None


# ---------- 인증 가드 ----------
def test_endpoints_require_auth(client):
    assert client.post("/api/tasks", json={"raw_input": "x"}).status_code == 401
    assert client.get("/api/worker/me/today").status_code == 401


def test_wrong_password(client):
    r = client.post("/api/auth/login", json={"login_id": "demo", "password": "nope"})
    assert r.status_code == 401


def test_role_separation(client, worker_token):
    # 근로자 토큰으로 사업주 전용 엔드포인트 호출 → 403
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"}, headers=auth(worker_token))
    assert r.status_code == 403


# ---------- 입력 검증 ----------
def test_empty_input_rejected(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "   "}, headers=auth(employer_token))
    assert r.status_code == 422  # 공백만 → min_length 위반


def test_oversized_input_rejected(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "가" * 3000}, headers=auth(employer_token))
    assert r.status_code == 422


# ---------- 전체 흐름 ----------
def _make_published_task(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"},
                    headers=auth(employer_token))
    assert r.status_code == 201, r.text
    task = r.json()
    assert len(task["steps"]) == 2
    client.post(f"/api/tasks/{task['id']}/publish", headers=auth(employer_token))
    a = client.post(f"/api/tasks/{task['id']}/assignments", headers=auth(employer_token))
    assert a.status_code == 200, a.text
    return task, a.json()


def test_end_to_end_with_stuck(client, employer_token, worker_token):
    task, assignment = _make_published_task(client, employer_token)

    today = client.get("/api/worker/me/today", headers=auth(worker_token))
    assert today.status_code == 200
    cards = today.json()
    assert len(cards) == 1
    steps = cards[0]["steps"]

    # 1단계: 정상 완료 / 2단계: 막힘(stuck=True) 보고
    client.post("/api/performance-logs", headers=auth(worker_token), json={
        "assignment_id": assignment["id"], "step_id": steps[0]["id"],
        "duration_sec": 12.0, "replay_count": 1, "stuck": False})
    client.post("/api/performance-logs", headers=auth(worker_token), json={
        "assignment_id": assignment["id"], "step_id": steps[1]["id"],
        "duration_sec": 90.0, "replay_count": 4, "stuck": True})

    dash = client.get(f"/api/dashboard/tasks/{task['id']}", headers=auth(employer_token)).json()
    assert dash["completion_rate"] == 100.0
    assert dash["completed_steps"] == 2
    # stuck 신호가 실제로 대시보드까지 전달된다(평가에서 죽어있던 핵심 지표).
    assert dash["stuck_steps"] == [2], dash["stuck_steps"]


def test_performance_log_is_upserted(client, employer_token, worker_token):
    task, assignment = _make_published_task(client, employer_token)
    steps = client.get("/api/worker/me/today", headers=auth(worker_token)).json()[0]["steps"]
    sid = steps[0]["id"]
    for dur in (10.0, 25.0, 40.0):  # 같은 단계 3번 보고
        client.post("/api/performance-logs", headers=auth(worker_token), json={
            "assignment_id": assignment["id"], "step_id": sid,
            "duration_sec": dur, "replay_count": 0, "stuck": False})
    dash = client.get(f"/api/dashboard/tasks/{task['id']}", headers=auth(employer_token)).json()
    # 중복 로그가 쌓이지 않고 마지막 값으로 갱신된다.
    step1 = next(s for s in dash["steps"] if s["order"] == 1)
    assert step1["duration_sec"] == 40.0


# ---------- 소유권 격리 ----------
def test_cross_employer_isolation(client, employer_token):
    import main
    from database import SessionLocal
    from models import Employer, Worker

    # 두 번째 사업주 + 토큰 생성
    db = SessionLocal()
    other = Employer(id="emp-2", name="다른 사업주", org_name="타 작업장",
                     login_id="other", password_hash=hash_password("pw"))
    db.add(other)
    db.add(Worker(id="wrk-2", employer_id="emp-2", display_name="이근로", access_code="9999"))
    db.commit()
    db.close()
    other_token = make_token("emp-2", "employer")

    # 1번 사업주가 직무 생성
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"}, headers=auth(employer_token))
    task_id = r.json()["id"]

    # 2번 사업주는 1번의 직무를 보거나 대시보드 조회 불가 → 404
    assert client.get(f"/api/tasks/{task_id}", headers=auth(other_token)).status_code == 404
    assert client.get(f"/api/dashboard/tasks/{task_id}", headers=auth(other_token)).status_code == 404


def test_log_rejects_step_from_other_assignment(client, employer_token, worker_token):
    _, assignment = _make_published_task(client, employer_token)
    r = client.post("/api/performance-logs", headers=auth(worker_token), json={
        "assignment_id": assignment["id"], "step_id": "nonexistent-step",
        "duration_sec": 1.0, "replay_count": 0, "stuck": False})
    assert r.status_code == 400


# ---------- 직무 목록 ----------
def test_list_tasks_employer_only(client, employer_token, worker_token):
    client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"}, headers=auth(employer_token))
    r = client.get("/api/tasks", headers=auth(employer_token))
    assert r.status_code == 200
    assert len(r.json()) >= 1
    # 근로자는 사업주용 목록 접근 불가
    assert client.get("/api/tasks", headers=auth(worker_token)).status_code == 403


# ---------- AI 코칭(기능 2) ----------
def test_coaching_employer_only_and_returns_suggestions(client, employer_token, worker_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요",
                                         "business_type": "물류", "worker_note": "글자보다 그림 선호"},
                    headers=auth(employer_token))
    task_id = r.json()["id"]

    # 근로자는 코칭 접근 불가
    assert client.get(f"/api/dashboard/tasks/{task_id}/coaching",
                      headers=auth(worker_token)).status_code == 403

    c = client.get(f"/api/dashboard/tasks/{task_id}/coaching", headers=auth(employer_token))
    assert c.status_code == 200, c.text
    body = c.json()
    assert "summary" in body
    assert body["suggestions"][0]["action"] == "photo"


def test_create_task_accepts_context(client, employer_token):
    # 맥락 필드가 있어도 정상 생성(LLM 컨텍스트로 전달)
    r = client.post("/api/tasks", json={
        "raw_input": "상자를 옮기세요", "business_type": "카페",
        "work_environment": "주방, 미끄러운 바닥", "worker_note": "큰 글씨 필요"},
        headers=auth(employer_token))
    assert r.status_code == 201, r.text


# ---------- 단계 추가 / 순서 변경 (검토 화면) ----------
def test_add_step_appends_at_end(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"},
                    headers=auth(employer_token))
    task = r.json()
    assert len(task["steps"]) == 2

    add = client.post(f"/api/tasks/{task['id']}/steps",
                      json={"sentence": "바닥을 쓸어주세요."}, headers=auth(employer_token))
    assert add.status_code == 201, add.text
    steps = add.json()["steps"]
    assert len(steps) == 3
    # 맨 끝에 order=3으로 추가
    assert steps[2]["sentence"] == "바닥을 쓸어주세요."
    assert [s["order"] for s in steps] == [1, 2, 3]


# ---------- 맥락 저장/재사용 ----------
def test_task_stores_context_for_later_searches(client, employer_token):
    """생성 시 맥락을 저장해야 나중에 같은 조건으로 재검색할 수 있다."""
    from database import SessionLocal
    from models import Task

    r = client.post("/api/tasks", json={
        "raw_input": "상자를 옮기세요", "business_type": "카페",
        "work_environment": "홀"}, headers=auth(employer_token))
    assert r.status_code == 201, r.text

    with SessionLocal() as db:
        task = db.get(Task, r.json()["id"])
        assert task.business_type == "카페"
        assert task.work_environment == "홀"


def test_candidate_lookup_uses_the_same_context_as_creation(client, employer_token,
                                                            monkeypatch):
    """후보 조회가 생성 때와 같은 맥락으로 검색해야 한다.

    맥락이 빠지면 업종 가중치가 달라져, 생성 때 채택된 단계가 후보 조회에서는
    경합으로 보이는 식으로 어긋난다.
    """
    import ai_client

    seen: list[dict] = []
    real = ai_client.map_symbols

    def spy(keywords, context=None):
        seen.append(dict(context or {}))
        return real(keywords, context)

    monkeypatch.setattr(ai_client, "map_symbols", spy)

    r = client.post("/api/tasks", json={
        "raw_input": "상자를 옮기세요", "business_type": "카페",
        "work_environment": "홀"}, headers=auth(employer_token))
    task = r.json()
    creation_ctx = seen[0]

    seen.clear()
    client.get(f"/api/tasks/{task['id']}/steps/{task['steps'][0]['id']}/symbol-candidates",
               headers=auth(employer_token))
    lookup_ctx = seen[0]

    assert lookup_ctx["business_type"] == creation_ctx["business_type"] == "카페"
    assert lookup_ctx["work_environment"] == creation_ctx["work_environment"] == "홀"


def test_step_stores_symbol_query_from_decompose(client, employer_token):
    """생성 시 쓴 검색어를 저장해야 후보 조회가 같은 질의를 재현한다."""
    from database import SessionLocal
    from models import Step, Task

    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                    headers=auth(employer_token))
    with SessionLocal() as db:
        task = db.get(Task, r.json()["id"])
        steps = sorted(task.steps, key=lambda s: s.order_index)
        assert steps[0].symbol_query == "상자,box"
        assert steps[1].symbol_query == "수량,quantity"


def test_candidate_lookup_reuses_stored_symbol_query(client, employer_token, monkeypatch):
    """후보 조회는 문장이 아니라 저장된 symbol_query로 검색해야 한다.

    안 그러면 생성('상자','box')과 조회('상자를','옮기세요')가 다른 질의라 판정이 어긋난다.
    """
    import ai_client

    seen: list[list[str]] = []
    real = ai_client.map_symbols
    monkeypatch.setattr(ai_client, "map_symbols",
                        lambda kw, context=None: (seen.append(list(kw)), real(kw, context))[1])

    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                    headers=auth(employer_token))
    task = r.json()
    seen.clear()
    client.get(f"/api/tasks/{task['id']}/steps/{task['steps'][0]['id']}/symbol-candidates",
               headers=auth(employer_token))
    assert seen[0] == ["상자", "box"]


def test_editing_sentence_clears_stale_symbol_query(client, employer_token):
    """문장을 고치면 옛 symbol_query는 무의미하다 — 비워서 새 문장에서 다시 뽑게 한다."""
    from database import SessionLocal
    from models import Step

    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                    headers=auth(employer_token))
    task = r.json()
    step_id = task["steps"][0]["id"]

    client.patch(f"/api/tasks/{task['id']}/steps/{step_id}",
                 json={"sentence": "바닥을 쓸어주세요."}, headers=auth(employer_token))
    with SessionLocal() as db:
        assert db.get(Step, step_id).symbol_query == ""


def test_accepted_rematch_is_offered_as_a_single_candidate(client, employer_token, monkeypatch):
    """생성 땐 폴백이었는데 재조회 시 매칭이 있으면 그 그림을 후보로 돌려준다."""
    import ai_client

    def accepted_now(keywords, context=None):
        return {"symbols": [{
            "keyword": "바닥", "image_url": "/api/aac/images/cafe/CAFE_080.webp",
            "source": "LOCAL_AAC", "confidence": 0.33, "needs_fallback": False,
            "reason": "accepted", "external_id": "CAFE_080",
            "resolved_keyword": "바닥을 빗자루로 쓸어낸다", "candidates": [],
        }]}

    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                    headers=auth(employer_token))
    task = r.json()
    monkeypatch.setattr(ai_client, "map_symbols", accepted_now)

    got = client.get(
        f"/api/tasks/{task['id']}/steps/{task['steps'][0]['id']}/symbol-candidates",
        headers=auth(employer_token))
    body = got.json()
    assert body["reason"] == "accepted"
    assert len(body["candidates"]) == 1
    assert body["candidates"][0]["asset_id"] == "CAFE_080"
    assert body["candidates"][0]["image_url"].startswith("http")


def test_added_step_uses_the_tasks_context(client, employer_token, monkeypatch):
    """검토 화면에서 추가한 단계도 같은 업종 맥락으로 그림을 찾아야 한다."""
    import ai_client

    seen: list[dict] = []
    real = ai_client.map_symbols
    monkeypatch.setattr(ai_client, "map_symbols",
                        lambda k, context=None: (seen.append(dict(context or {})),
                                                 real(k, context))[1])

    r = client.post("/api/tasks", json={
        "raw_input": "상자를 옮기세요", "business_type": "포장",
        "work_environment": "작업장"}, headers=auth(employer_token))
    task = r.json()

    seen.clear()
    add = client.post(f"/api/tasks/{task['id']}/steps",
                      json={"sentence": "박스 뚜껑을 덮으세요."}, headers=auth(employer_token))
    assert add.status_code == 201, add.text
    assert seen[0]["business_type"] == "포장"
    assert seen[0]["work_environment"] == "작업장"


# ---------- AAC 후보 선택 (검토 화면) ----------
def test_symbol_candidates_returns_shortlist(client, employer_token, monkeypatch):
    """자동 채택을 못 한 단계는 후보와 사유를 돌려줘야 한다."""
    import ai_client
    from conftest import fake_map_symbols_with_candidates

    r = client.post("/api/tasks", json={"raw_input": "원두를 갈아주세요"},
                    headers=auth(employer_token))
    task = r.json()
    step_id = task["steps"][0]["id"]

    monkeypatch.setattr(ai_client, "map_symbols", fake_map_symbols_with_candidates)
    got = client.get(f"/api/tasks/{task['id']}/steps/{step_id}/symbol-candidates",
                     headers=auth(employer_token))
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["step_id"] == step_id
    assert body["reason"] == "low_margin"
    assert [c["asset_id"] for c in body["candidates"]] == ["CAFE_007", "CAFE_013"]
    # 상대 경로가 브라우저가 볼 수 있는 절대 URL로 바뀌어야 한다.
    assert body["candidates"][0]["image_url"].startswith("http")


def test_symbol_candidates_empty_when_nothing_fits(client, employer_token):
    """쓸 만한 후보가 없으면 빈 목록 — 프론트는 현장 사진을 권한다."""
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                    headers=auth(employer_token))
    task = r.json()
    step_id = task["steps"][0]["id"]

    got = client.get(f"/api/tasks/{task['id']}/steps/{step_id}/symbol-candidates",
                     headers=auth(employer_token))
    assert got.status_code == 200, got.text
    assert got.json()["candidates"] == []
    assert got.json()["reason"] == "no_candidate"


def test_symbol_candidates_rejects_other_employers_task(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                    headers=auth(employer_token))
    task = r.json()
    step_id = task["steps"][0]["id"]

    other = make_token("other-employer", "employer")
    got = client.get(f"/api/tasks/{task['id']}/steps/{step_id}/symbol-candidates",
                     headers=auth(other))
    assert got.status_code == 404, got.text


def test_symbol_candidates_404_for_unknown_step(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                    headers=auth(employer_token))
    task = r.json()
    got = client.get(f"/api/tasks/{task['id']}/steps/no-such-step/symbol-candidates",
                     headers=auth(employer_token))
    assert got.status_code == 404, got.text


def test_picking_an_aac_candidate_records_local_aac_source(client, employer_token):
    """후보를 고르면 출처가 LOCAL_AAC로 남아야 한다(사진/폴백과 구분)."""
    r = client.post("/api/tasks", json={"raw_input": "원두를 갈아주세요"},
                    headers=auth(employer_token))
    task = r.json()
    step_id = task["steps"][0]["id"]

    patched = client.patch(
        f"/api/tasks/{task['id']}/steps/{step_id}",
        json={"symbol_url": "http://localhost:8000/api/aac/images/cafe/CAFE_013.webp",
              "symbol_source": "LOCAL_AAC"},
        headers=auth(employer_token))
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["symbol_source"] == "LOCAL_AAC"
    assert body["needs_fallback"] is False


def test_symbol_source_defaults_to_fallback(client, employer_token):
    """symbol_source를 안 주면 기존 동작(fallback)을 유지한다."""
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                    headers=auth(employer_token))
    task = r.json()
    step_id = task["steps"][0]["id"]

    patched = client.patch(f"/api/tasks/{task['id']}/steps/{step_id}",
                           json={"symbol_url": "http://example.test/x.webp"},
                           headers=auth(employer_token))
    assert patched.status_code == 200, patched.text
    assert patched.json()["symbol_source"] == "fallback"


def test_symbol_source_rejects_unknown_value(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"},
                    headers=auth(employer_token))
    task = r.json()
    step_id = task["steps"][0]["id"]

    patched = client.patch(f"/api/tasks/{task['id']}/steps/{step_id}",
                           json={"symbol_url": "http://example.test/x.webp",
                                 "symbol_source": "photo"},
                           headers=auth(employer_token))
    assert patched.status_code == 422, patched.text


def test_add_step_rejects_blank(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"}, headers=auth(employer_token))
    task = r.json()
    add = client.post(f"/api/tasks/{task['id']}/steps",
                      json={"sentence": "   "}, headers=auth(employer_token))
    assert add.status_code == 422, add.text


def test_reorder_steps(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"},
                    headers=auth(employer_token))
    task = r.json()
    ids = [s["id"] for s in task["steps"]]
    # 순서 뒤집기
    rr = client.patch(f"/api/tasks/{task['id']}/steps/reorder",
                      json={"step_ids": [ids[1], ids[0]]}, headers=auth(employer_token))
    assert rr.status_code == 200, rr.text
    steps = rr.json()["steps"]
    assert [s["id"] for s in steps] == [ids[1], ids[0]]
    assert [s["order"] for s in steps] == [1, 2]


def test_reorder_rejects_mismatched_ids(client, employer_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"},
                    headers=auth(employer_token))
    task = r.json()
    ids = [s["id"] for s in task["steps"]]
    # 일부만 보내면 400 (전체 단계를 정확히 포함해야 함)
    bad = client.patch(f"/api/tasks/{task['id']}/steps/reorder",
                       json={"step_ids": [ids[0]]}, headers=auth(employer_token))
    assert bad.status_code == 400, bad.text


def test_add_and_reorder_require_ownership(client, employer_token, worker_token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요"}, headers=auth(employer_token))
    task = r.json()
    # 근로자 토큰으로는 추가/정렬 불가(역할)
    assert client.post(f"/api/tasks/{task['id']}/steps",
                       json={"sentence": "x"}, headers=auth(worker_token)).status_code == 403
    assert client.patch(f"/api/tasks/{task['id']}/steps/reorder",
                        json={"step_ids": [task["steps"][0]["id"]]},
                        headers=auth(worker_token)).status_code == 403


# ---------- 날짜 기준(현지 시간) ----------
def test_local_day_start_follows_local_midnight():
    """"오늘" 경계는 UTC 0시가 아니라 현지 0시다(한국이면 UTC 15시)."""
    from datetime import datetime, timezone

    import main

    just_after_midnight_kst = datetime(2026, 9, 20, 15, 33, tzinfo=timezone.utc)  # KST 9/21 00:33
    assert main.local_day_start_utc(just_after_midnight_kst) == datetime(
        2026, 9, 20, 15, 0, tzinfo=timezone.utc)

    just_before_midnight_kst = datetime(2026, 9, 20, 14, 59, tzinfo=timezone.utc)  # KST 9/20 23:59
    assert main.local_day_start_utc(just_before_midnight_kst) == datetime(
        2026, 9, 19, 15, 0, tzinfo=timezone.utc)


def test_worker_tasks_and_active_dates_use_local_date(client, employer_token):
    """한국 시간 0~9시에 배정한 직무가 UTC 날짜가 아니라 한국 날짜로 조회돼야 한다.

    UTC 1/10 15:32는 한국 시간 1/11 00:32다. 예전에는 1/10으로 저장·필터돼서
    브라우저의 "오늘"에 안 보였다. DB를 다른 테스트와 공유하므로 내 직무만 검사하고,
    다른 테스트의 배정(오늘 날짜)과 겹치지 않게 과거 날짜를 쓴다.
    """
    from datetime import datetime

    from database import SessionLocal
    from models import Assignment

    task, assignment = _make_published_task(client, employer_token)
    with SessionLocal() as db:
        a = db.get(Assignment, assignment["id"])
        a.assigned_date = datetime(2026, 1, 10, 15, 32)  # naive = UTC 저장 형식
        worker_id = a.worker_id
        db.commit()

    def task_ids_on(day: str) -> list[str]:
        r = client.get(f"/api/workers/{worker_id}/tasks?date={day}",
                       headers=auth(employer_token))
        assert r.status_code == 200, r.text
        return [t["id"] for t in r.json()]

    assert task["id"] in task_ids_on("2026-01-11")       # 한국 날짜
    assert task["id"] not in task_ids_on("2026-01-10")   # UTC 날짜로는 안 잡힌다

    dates = client.get(f"/api/workers/{worker_id}/active-dates",
                       headers=auth(employer_token)).json()
    assert "2026-01-11" in dates
    assert "2026-01-10" not in dates
