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
