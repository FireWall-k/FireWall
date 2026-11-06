"""Phase 0.2 개인정보 보호 테스트.

지키는 것:
1. AI 하네스(→ 해외 LLM)로 가는 요청에 근로자 실명이 없다(익명 별칭으로 바꾸고 응답에서 되돌린다).
2. 사업주 자유 메모(worker_note)는 근로자별 "AI에 메모 사용" 허용 + AI 처리 동의가 있을 때만 간다.
3. AI 처리 동의가 없거나 철회된 근로자의 수행 데이터는 LLM 경로로 보내지 않는다(규칙 기반 폴백만).
4. 근로자 삭제 후 DB 행과 디스크(SQLite 파일·WAL 포함)에 그 근로자의 흔적이 없다.
5. purge는 보존기간이 지난 것만 지운다.
6. 근로자 개인 데이터 열람은 접근 감사 로그에 남고, 감사 로그는 앱 코드로 고칠 수 없다.
"""
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

import ai_client
import manage
import retention
from auth import verify_token
from conftest import auth
from database import SessionLocal, engine
from models import AccessAuditLog, Assignment, PerformanceLog, Step, Worker, WorkerConsent


# --- 도우미 ------------------------------------------------------------------

def _new_employer(client) -> str:
    """테스트마다 독립된 사업장을 만든다. 별칭(근로자 A, B…)은 사업장의 근로자 등록 순서로 정해지므로
    공용 데모 사업장을 쓰면 다른 테스트가 만든 근로자 때문에 결과가 흔들린다."""
    login = f"priv-{uuid.uuid4().hex[:8]}"
    manage.create_employer(login, "", "프라이버시 테스트", "correct-horse-1")
    r = client.post("/api/auth/login", json={"login_id": login, "password": "correct-horse-1"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _create_worker(client, token, name: str) -> str:
    r = client.post("/api/workers", json={"display_name": name}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _grant(client, token, worker_id, consent_type="ai_processing", subject="guardian"):
    r = client.post(f"/api/workers/{worker_id}/consents",
                    json={"consent_type": consent_type, "subject": subject}, headers=auth(token))
    assert r.status_code == 201, r.text
    return r.json()


class _Capture:
    """ai_client 경계로 나가는 호출 인자를 그대로 모은다(= AI 하네스로 가는 페이로드 스냅샷)."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def dump(self) -> str:
        return json.dumps(self.calls, ensure_ascii=False)


@pytest.fixture()
def capture(monkeypatch):
    cap = _Capture()

    def fake_decompose(raw_input, context=None):
        cap.calls.append(("decompose", {"raw_input": raw_input, "context": context}))
        # LLM이 원문의 별칭을 문장에 그대로 옮겨 쓴 상황을 흉내낸다 → 백엔드가 실명으로 되돌려야 한다.
        first = raw_input.split(".")[0]
        return {
            "task_title": f"{first} 직무",
            "steps": [
                {"order": 1, "sentence": f"{first}.", "action_type": "move",
                 "symbol_query": ["상자"], "keywords": [{"term": "상자", "pos": "noun"}]},
                {"order": 2, "sentence": "수량을 확인하세요.", "action_type": "observe",
                 "symbol_query": ["수량"], "keywords": [{"term": "수량", "pos": "noun"}]},
            ],
        }

    def fake_map_symbols(keywords, context=None):
        cap.calls.append(("map_symbols", {"keywords": keywords, "context": context}))
        return {"symbols": [{"keyword": k, "image_url": None, "source": "fallback",
                             "confidence": 0.0, "needs_fallback": True,
                             "reason": "no_candidate", "candidates": []} for k in keywords]}

    def fake_coaching(task_title, steps, context=None, allow_llm=True):
        cap.calls.append(("coaching", {"task_title": task_title, "steps": steps,
                                       "context": context, "allow_llm": allow_llm}))
        return {"summary": "근로자 A님이 2단계에서 막혔습니다.",
                "suggestions": [{"order": 2, "issue": "근로자 A님 다시듣기 과다",
                                 "suggestion": "사진으로 교체하세요.", "action": "photo"}]}

    monkeypatch.setattr(ai_client, "decompose", fake_decompose)
    monkeypatch.setattr(ai_client, "map_symbols", fake_map_symbols)
    monkeypatch.setattr(ai_client, "coaching", fake_coaching)
    return cap


def _publish_assign_log(client, token, task_id, worker_id):
    assert client.post(f"/api/tasks/{task_id}/publish", headers=auth(token)).status_code == 200
    r = client.post(f"/api/tasks/{task_id}/assignments", json={"worker_ids": [worker_id]},
                    headers=auth(token))
    assert r.status_code == 200, r.text
    assignment_id = r.json()[0]["id"]
    task = client.get(f"/api/tasks/{task_id}", headers=auth(token)).json()
    # 수행 로그는 근로자 토큰으로만 쓸 수 있다. 테스트에서는 DB에 직접 넣는다.
    with SessionLocal() as db:
        db.add(PerformanceLog(assignment_id=assignment_id, step_id=task["steps"][1]["id"],
                              duration_sec=150, replay_count=4, stuck=True))
        db.commit()
    return assignment_id


def _employer_id(token) -> str:
    return verify_token(token)["sub"]


# --- 1. 실명 → 별칭 ---------------------------------------------------------

def test_decompose_payload_has_alias_not_real_name_and_response_is_restored(client, capture):
    token = _new_employer(client)
    _create_worker(client, token, "홍길동")
    _create_worker(client, token, "김영희")

    r = client.post("/api/tasks", json={
        "raw_input": "김영희 씨는 상자를 옮기세요. 홍길동 씨는 수량을 세세요.",
        "business_type": "물류",
        "worker_note": "소리에 민감함",
    }, headers=auth(token))
    assert r.status_code == 201, r.text

    sent = capture.dump()
    assert "홍길동" not in sent and "김영희" not in sent
    # 메모는 근로자 지정 + 허용 + 동의 없이는 나가지 않는다.
    assert "소리에 민감함" not in sent

    # 스냅샷: AI 하네스로 간 분해 요청 전체. 별칭은 사업장 근로자 등록 순서(홍길동=A, 김영희=B)다.
    assert capture.calls[0] == ("decompose", {
        "raw_input": "근로자 B 씨는 상자를 옮기세요. 근로자 A 씨는 수량을 세세요.",
        "context": {
            "business_type": "물류",
            "work_environment": "",
            "worker_note": "",
            "raw_input": "근로자 B 씨는 상자를 옮기세요. 근로자 A 씨는 수량을 세세요.",
        },
    })

    # 응답(제목·문장)은 실명으로 되돌아와 저장된다 — 근로자 화면·TTS는 원래 문장을 써야 한다.
    task = r.json()
    assert task["title"] == "김영희 씨는 상자를 옮기세요 직무"
    assert task["steps"][0]["sentence"] == "김영희 씨는 상자를 옮기세요."


def test_generic_default_name_is_not_masked(client, capture):
    """기본 이름 '근로자'까지 별칭으로 바꾸면 '근로자'라는 낱말이 들어간 모든 문장이 망가진다."""
    token = _new_employer(client)
    _create_worker(client, token, "근로자")
    r = client.post("/api/tasks", json={"raw_input": "근로자 휴게실을 청소하세요."}, headers=auth(token))
    assert r.status_code == 201
    assert capture.calls[0][1]["raw_input"] == "근로자 휴게실을 청소하세요."


# --- 2. 메모는 허용 + 동의가 있을 때만 ---------------------------------------

def test_worker_note_sent_only_with_permission_and_consent(client, capture):
    token = _new_employer(client)
    wid = _create_worker(client, token, "박민수")
    body = {"raw_input": "상자를 옮기세요.", "worker_id": wid, "worker_note": "그림을 선호함"}

    # 허용 안 함(기본값) → 안 보냄
    assert client.post("/api/tasks", json=body, headers=auth(token)).status_code == 201
    assert capture.calls[0][1]["context"]["worker_note"] == ""

    # 허용했지만 AI 처리 동의 없음 → 안 보냄
    r = client.patch(f"/api/workers/{wid}", json={"ai_note_allowed": True}, headers=auth(token))
    assert r.status_code == 200 and r.json()["ai_note_allowed"] is True
    capture.calls.clear()
    client.post("/api/tasks", json=body, headers=auth(token))
    assert capture.calls[0][1]["context"]["worker_note"] == ""

    # 허용 + 동의 → 보냄. 메모 속 실명도 별칭으로 바뀐다.
    _grant(client, token, wid)
    capture.calls.clear()
    client.post("/api/tasks", json={**body, "worker_note": "박민수는 그림을 선호함"}, headers=auth(token))
    assert capture.calls[0][1]["context"]["worker_note"] == "근로자 A는 그림을 선호함"

    # 근로자를 지정하지 않으면 누구의 허용인지 알 수 없으므로 보내지 않는다.
    capture.calls.clear()
    client.post("/api/tasks", json={"raw_input": "상자를 옮기세요.", "worker_note": "그림을 선호함"},
                headers=auth(token))
    assert capture.calls[0][1]["context"]["worker_note"] == ""


def test_stored_worker_note_is_used_when_allowed(client, capture):
    token = _new_employer(client)
    wid = _create_worker(client, token, "이수진")
    client.patch(f"/api/workers/{wid}", json={"note": "큰 글씨 선호", "ai_note_allowed": True},
                 headers=auth(token))
    _grant(client, token, wid)
    client.post("/api/tasks", json={"raw_input": "상자를 옮기세요.", "worker_id": wid}, headers=auth(token))
    assert capture.calls[0][1]["context"]["worker_note"] == "큰 글씨 선호"


def test_note_and_name_are_not_sent_to_symbol_search(client, capture):
    token = _new_employer(client)
    wid = _create_worker(client, token, "최지훈")
    client.patch(f"/api/workers/{wid}", json={"ai_note_allowed": True}, headers=auth(token))
    _grant(client, token, wid)
    client.post("/api/tasks", json={"raw_input": "최지훈 씨, 상자를 옮기세요.", "worker_id": wid,
                                    "worker_note": "왼손잡이"}, headers=auth(token))
    symbol_calls = [c for name, c in capture.calls if name == "map_symbols"]
    assert symbol_calls
    dumped = json.dumps(symbol_calls, ensure_ascii=False)
    assert "왼손잡이" not in dumped and "최지훈" not in dumped


def test_create_task_with_foreign_worker_id_is_404(client, capture):
    token = _new_employer(client)
    r = client.post("/api/tasks", json={"raw_input": "상자", "worker_id": "wrk-demo"}, headers=auth(token))
    assert r.status_code == 404


# --- 3. 코칭: 동의 없으면 LLM 제외, 실명·메모 없음 -------------------------------

def _coaching_setup(client, token, capture, name="정하늘"):
    wid = _create_worker(client, token, name)
    task = client.post("/api/tasks", json={"raw_input": f"{name} 씨는 상자를 옮기세요."},
                       headers=auth(token)).json()
    _publish_assign_log(client, token, task["id"], wid)
    capture.calls.clear()
    return wid, task


def test_coaching_without_consent_excludes_llm(client, capture):
    token = _new_employer(client)
    wid, task = _coaching_setup(client, token, capture)
    r = client.get(f"/api/dashboard/tasks/{task['id']}/coaching?worker_id={wid}", headers=auth(token))
    assert r.status_code == 200, r.text
    (name, payload), = capture.calls
    assert name == "coaching"
    assert payload["allow_llm"] is False
    assert r.json()["ai_excluded"] is True


def test_coaching_payload_snapshot_with_consent(client, capture):
    token = _new_employer(client)
    wid, task = _coaching_setup(client, token, capture)
    client.patch(f"/api/workers/{wid}", json={"note": "정하늘은 소음에 민감"}, headers=auth(token))
    _grant(client, token, wid)

    r = client.get(f"/api/dashboard/tasks/{task['id']}/coaching?worker_id={wid}", headers=auth(token))
    assert r.status_code == 200
    (_, payload), = capture.calls
    # 메모는 "AI에 메모 사용"을 켜지 않았으므로 빠진다. 직무 제목·문장 속 실명은 별칭이다.
    assert payload == {
        "task_title": "근로자 A 씨는 상자를 옮기세요 직무",
        "steps": [
            {"order": 1, "sentence": "근로자 A 씨는 상자를 옮기세요.", "action_type": "move",
             "completed": False, "stuck": False, "replay_count": 0, "duration_sec": 0.0},
            {"order": 2, "sentence": "수량을 확인하세요.", "action_type": "observe",
             "completed": True, "stuck": True, "replay_count": 4, "duration_sec": 150.0},
        ],
        "context": {"business_type": "", "work_environment": "", "job": ""},
        "allow_llm": True,
    }
    # 응답의 별칭은 실명으로 되돌린다.
    body = r.json()
    assert body["ai_excluded"] is False
    assert body["summary"] == "정하늘님이 2단계에서 막혔습니다."
    assert body["suggestions"][0]["issue"] == "정하늘님 다시듣기 과다"


def test_coaching_includes_note_only_when_allowed(client, capture):
    token = _new_employer(client)
    wid, task = _coaching_setup(client, token, capture)
    client.patch(f"/api/workers/{wid}", json={"note": "정하늘은 소음에 민감", "ai_note_allowed": True},
                 headers=auth(token))
    _grant(client, token, wid)
    client.get(f"/api/dashboard/tasks/{task['id']}/coaching?worker_id={wid}", headers=auth(token))
    (_, payload), = capture.calls
    assert payload["context"]["worker_note"] == "근로자 A은 소음에 민감"
    assert "정하늘" not in json.dumps(payload, ensure_ascii=False)


def test_revoked_consent_excludes_llm_again(client, capture):
    token = _new_employer(client)
    wid, task = _coaching_setup(client, token, capture)
    consent = _grant(client, token, wid)
    r = client.post(f"/api/workers/{wid}/consents/{consent['id']}/revoke", headers=auth(token))
    assert r.status_code == 200 and r.json()["revoked_at"] is not None
    worker = next(w for w in client.get("/api/workers", headers=auth(token)).json() if w["id"] == wid)
    assert worker["ai_consent"] is False
    client.get(f"/api/dashboard/tasks/{task['id']}/coaching?worker_id={wid}", headers=auth(token))
    assert capture.calls[-1][1]["allow_llm"] is False


def test_aggregate_coaching_needs_consent_from_every_included_worker(client, capture):
    """근로자를 고르지 않은 집계 코칭에는 여러 근로자의 기록이 섞인다 — 한 명이라도 동의가 없으면 LLM 제외."""
    token = _new_employer(client)
    wid, task = _coaching_setup(client, token, capture)
    other = _create_worker(client, token, "윤서연")
    client.post(f"/api/tasks/{task['id']}/assignments", json={"worker_ids": [other]}, headers=auth(token))
    _grant(client, token, wid)
    client.get(f"/api/dashboard/tasks/{task['id']}/coaching", headers=auth(token))
    assert capture.calls[-1][1]["allow_llm"] is False
    _grant(client, token, other)
    client.get(f"/api/dashboard/tasks/{task['id']}/coaching", headers=auth(token))
    assert capture.calls[-1][1]["allow_llm"] is True


# --- 동의 API ---------------------------------------------------------------

def test_consent_records_version_and_recorder(client):
    token = _new_employer(client)
    wid = _create_worker(client, token, "강동원")
    c = _grant(client, token, wid, consent_type="personal_info", subject="self")
    assert c["policy_version"] and c["granted_at"] and c["revoked_at"] is None
    assert c["subject"] == "self"
    assert c["recorded_by"] == _employer_id(token)
    listed = client.get(f"/api/workers/{wid}/consents", headers=auth(token)).json()
    assert [x["id"] for x in listed] == [c["id"]]
    worker = next(w for w in client.get("/api/workers", headers=auth(token)).json() if w["id"] == wid)
    # 개인정보 수집·이용 동의만으로는 AI 처리(국외 이전) 동의가 아니다.
    assert worker["ai_consent"] is False


def test_consent_api_is_owner_only(client):
    token = _new_employer(client)
    assert client.get("/api/workers/wrk-demo/consents", headers=auth(token)).status_code == 404
    r = client.post("/api/workers/wrk-demo/consents",
                    json={"consent_type": "ai_processing", "subject": "self"}, headers=auth(token))
    assert r.status_code == 404
    assert client.get("/api/workers/wrk-demo/export", headers=auth(token)).status_code == 404
    assert client.patch("/api/workers/wrk-demo", json={"ai_note_allowed": True},
                        headers=auth(token)).status_code == 404
    assert client.delete("/api/workers/wrk-demo", headers=auth(token)).status_code == 404


def test_unknown_consent_type_is_rejected(client):
    token = _new_employer(client)
    wid = _create_worker(client, token, "임채원")
    r = client.post(f"/api/workers/{wid}/consents", json={"consent_type": "anything", "subject": "self"},
                    headers=auth(token))
    assert r.status_code == 422


# --- 4. 내보내기·삭제 ---------------------------------------------------------

def test_export_contains_profile_consents_assignments_logs(client, capture):
    token = _new_employer(client)
    wid, task = _coaching_setup(client, token, capture, name="서지우")
    _grant(client, token, wid)
    r = client.get(f"/api/workers/{wid}/export", headers=auth(token))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["worker"]["display_name"] == "서지우"
    assert len(data["consents"]) == 1
    assert data["assignments"][0]["task_title"] == task["title"]
    assert data["performance_logs"][0]["replay_count"] == 4
    # 접속 코드 해시는 내보내지 않는다(본인 데이터가 아니라 인증 비밀).
    assert "access_code_hash" not in json.dumps(data)
    assert "attachment" in r.headers.get("content-disposition", "")


def _db_files_bytes() -> bytes:
    db_path = Path(engine.url.database)
    blobs = b""
    for suffix in ("", "-wal", "-journal"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            blobs += p.read_bytes()
    return blobs


def test_delete_worker_leaves_no_trace_in_db_or_disk(client, capture):
    token = _new_employer(client)
    name = "삭제대상황보름달"
    wid, task = _coaching_setup(client, token, capture, name=name)
    client.patch(f"/api/workers/{wid}", json={"note": "삭제대상메모문자열"}, headers=auth(token))
    _grant(client, token, wid)
    # 직무 문장에도 이름이 들어 있다. 직무는 사업주 데이터라 근로자 삭제로 지우지 않으므로
    # 여기서는 직무를 먼저 지워, 남은 흔적이 근로자 삭제 경로 때문인지만 본다.
    client.delete(f"/api/tasks/{task['id']}", headers=auth(token))
    assert name.encode("utf-8") in _db_files_bytes()  # 전제: 지우기 전에는 디스크에 있다

    r = client.delete(f"/api/workers/{wid}", headers=auth(token))
    assert r.status_code == 200, r.text

    with SessionLocal() as db:
        assert db.get(Worker, wid) is None
        assert db.scalars(select(WorkerConsent).where(WorkerConsent.worker_id == wid)).all() == []
        assert db.scalars(select(Assignment).where(Assignment.worker_id == wid)).all() == []
        # 감사 로그는 보존 규정에 따라 남지만, 근로자 id만 있고 이름은 없다.
        audits = db.scalars(select(AccessAuditLog).where(AccessAuditLog.worker_id == wid)).all()
        assert any(a.action == "worker.delete" for a in audits)

    # 디스크: SQLite는 지운 행을 빈 페이지·WAL에 그대로 남긴다(secure_delete + 체크포인트로 지워야 한다).
    raw = _db_files_bytes()
    assert name.encode("utf-8") not in raw
    assert "삭제대상메모문자열".encode("utf-8") not in raw


# --- 5. 보존기간 purge ----------------------------------------------------------

def test_purge_removes_only_expired_rows_and_orphan_tts(client, capture, monkeypatch, tmp_path):
    token = _new_employer(client)
    wid, task = _coaching_setup(client, token, capture, name="보존테스트")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as db:
        assignment = db.scalar(select(Assignment).where(Assignment.worker_id == wid))
        step_ids = [s.id for s in db.scalars(select(Step).where(Step.task_id == task["id"])).all()]
        old_log = db.scalar(select(PerformanceLog).where(PerformanceLog.assignment_id == assignment.id))
        old_log.completed_at = now - timedelta(days=400)
        fresh = PerformanceLog(assignment_id=assignment.id,
                               step_id=next(s for s in step_ids if s != old_log.step_id),
                               completed_at=now - timedelta(days=10))
        db.add(fresh)
        db.add_all([
            AccessAuditLog(actor_id="x", actor_role="employer", action="worker.list",
                           at=now - timedelta(days=800), request_ip="1.1.1.1"),
            AccessAuditLog(actor_id="x", actor_role="employer", action="worker.list",
                           at=now - timedelta(days=100), request_ip="1.1.1.1"),
        ])
        db.commit()
        old_log_id, fresh_id = old_log.id, fresh.id

    tts_dir = tmp_path / "tts"
    tts_dir.mkdir()
    monkeypatch.setenv("TTS_CACHE_DIR", str(tts_dir))
    referenced = "a" * 32 + ".mp3"
    with SessionLocal() as db:
        step = db.get(Step, step_ids[0])
        step.tts_audio_url = f"http://localhost:8000/api/tts/{referenced}"
        db.commit()
    (tts_dir / referenced).write_bytes(b"x")
    old_orphan = tts_dir / ("b" * 32 + ".mp3")
    old_orphan.write_bytes(b"x")
    two_days_ago = time.time() - 2 * 86400
    os.utime(old_orphan, (two_days_ago, two_days_ago))
    os.utime(tts_dir / referenced, (two_days_ago, two_days_ago))
    new_orphan = tts_dir / ("c" * 32 + ".mp3")  # 방금 합성돼 아직 단계에 저장되기 전일 수 있다
    new_orphan.write_bytes(b"x")

    monkeypatch.setenv("PERFORMANCE_LOG_RETENTION_DAYS", "365")
    monkeypatch.setenv("ACCESS_AUDIT_RETENTION_DAYS", "730")
    with SessionLocal() as db:
        report = retention.purge(db)

    assert report["performance_logs"] >= 1
    assert report["access_audit_logs"] >= 1
    assert report["tts_files"] == 1
    with SessionLocal() as db:
        assert db.get(PerformanceLog, old_log_id) is None
        assert db.get(PerformanceLog, fresh_id) is not None
        remaining = db.scalars(select(AccessAuditLog).where(AccessAuditLog.actor_id == "x")).all()
        assert len(remaining) == 1
    assert (tts_dir / referenced).exists()
    assert not old_orphan.exists()
    assert new_orphan.exists()


def test_purge_dry_run_deletes_nothing(client, monkeypatch, tmp_path):
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with SessionLocal() as db:
        db.add(AccessAuditLog(actor_id="dry", actor_role="employer", action="worker.list",
                              at=now - timedelta(days=5000), request_ip=""))
        db.commit()
    with SessionLocal() as db:
        report = retention.purge(db, dry_run=True)
    assert report["access_audit_logs"] >= 1
    with SessionLocal() as db:
        assert db.scalar(select(AccessAuditLog).where(AccessAuditLog.actor_id == "dry")) is not None


def test_manage_purge_command(client, monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    manage.main(["purge"])
    out = capsys.readouterr().out
    assert "수행 로그" in out and "접근 감사" in out


def test_retention_env_must_be_positive(monkeypatch):
    monkeypatch.setenv("PERFORMANCE_LOG_RETENTION_DAYS", "0")
    with pytest.raises(ValueError):
        retention.performance_log_retention_days()


# --- 6. 접근 감사 -------------------------------------------------------------

def _audits(actor_id: str):
    with SessionLocal() as db:
        rows = db.scalars(select(AccessAuditLog).where(AccessAuditLog.actor_id == actor_id)
                          .order_by(AccessAuditLog.at)).all()
        return [(a.action, a.worker_id, a.request_ip) for a in rows]


def test_viewing_worker_data_is_audited(client, capture):
    token = _new_employer(client)
    emp = _employer_id(token)
    wid, task = _coaching_setup(client, token, capture, name="감사대상")

    client.get("/api/workers", headers=auth(token))
    client.get(f"/api/workers/{wid}/tasks", headers=auth(token))
    client.get(f"/api/dashboard/tasks/{task['id']}?worker_id={wid}", headers=auth(token))
    client.get(f"/api/dashboard/tasks/{task['id']}/coaching?worker_id={wid}", headers=auth(token))
    client.get(f"/api/workers/{wid}/export", headers=auth(token))

    rows = _audits(emp)
    actions = {(a, w) for a, w, _ in rows}
    assert ("worker.list", None) in actions
    assert ("worker.history", wid) in actions
    assert ("dashboard.view", wid) in actions
    assert ("coaching.view", wid) in actions
    assert ("worker.export", wid) in actions
    assert all(ip for *_, ip in rows)


def test_repeated_polling_is_deduplicated(client, capture):
    """대시보드는 3초마다 폴링한다. 매번 남기면 하루에 수만 줄이 쌓여 정작 열람 기록을 찾기 어렵다."""
    token = _new_employer(client)
    emp = _employer_id(token)
    wid, task = _coaching_setup(client, token, capture, name="폴링대상")
    for _ in range(5):
        client.get(f"/api/dashboard/tasks/{task['id']}?worker_id={wid}", headers=auth(token))
    assert len([r for r in _audits(emp) if r[0] == "dashboard.view"]) == 1


def test_audit_log_is_append_only_from_app_code():
    with SessionLocal() as db:
        row = AccessAuditLog(actor_id="ro", actor_role="employer", action="worker.list", request_ip="")
        db.add(row)
        db.commit()
        row.action = "tampered"
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
        with pytest.raises(Exception):
            db.delete(row)
            db.commit()
        db.rollback()
    with SessionLocal() as db:
        assert db.scalar(select(AccessAuditLog.action).where(AccessAuditLog.actor_id == "ro")) == "worker.list"


def test_no_app_code_path_deletes_audit_logs():
    """감사 로그를 지우는 코드는 보존기간 purge(retention.py) 하나뿐이어야 한다."""
    backend = Path(__file__).resolve().parent.parent
    offenders = []
    for py in backend.glob("*.py"):
        if py.name == "retention.py":
            continue
        text = py.read_text(encoding="utf-8")
        if "delete(AccessAuditLog" in text or "update(AccessAuditLog" in text:
            offenders.append(py.name)
    assert offenders == []


def test_task_context_is_masked_for_ai_but_stored_as_written(client, capture):
    """업종·환경 칸에도 이름이 들어갈 수 있다. AI로는 별칭을 보내되, DB에는 사업주가 쓴 그대로 저장해야
    나중에 후보 재검색·코칭이 같은 맥락을 쓴다(별칭은 근로자 등록 순서가 바뀌면 다른 사람을 가리킨다)."""
    from models import Task

    token = _new_employer(client)
    _create_worker(client, token, "오세훈")
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요.",
                                        "work_environment": "오세훈 자리 옆 창고"}, headers=auth(token))
    assert r.status_code == 201
    assert capture.calls[0][1]["context"]["work_environment"] == "근로자 A 자리 옆 창고"
    with SessionLocal() as db:
        assert db.get(Task, r.json()["id"]).work_environment == "오세훈 자리 옆 창고"
