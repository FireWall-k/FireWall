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
import media
import retention
from auth import verify_token
from conftest import auth, publish, delete_task, delete_worker
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
    assert publish(client, token, task_id).status_code == 200
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
    assert delete_worker(client, 'wrk-demo', auth(token)).status_code == 404


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
    delete_task(client, task['id'], auth(token))
    assert name.encode("utf-8") in _db_files_bytes()  # 전제: 지우기 전에는 디스크에 있다

    r = delete_worker(client, wid, auth(token))
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
    (tts_dir / referenced).write_bytes(b"x")
    with SessionLocal() as db:
        # (Phase 0.3) 참조는 URL이 아니라 소유 레코드(MediaFile) + 단계의 tts_media_id다.
        step = db.get(Step, step_ids[0])
        rec = media.create_record(db, step.task.employer_id, media.KIND_TTS, referenced)
        step.tts_media_id = rec.id
        db.commit()
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
    # 근로자 목록도 누구의 이름·메모가 보였는지 근로자마다 남긴다(3차 검증 지적).
    assert ("worker.list", wid) in actions
    assert ("worker.list", None) not in actions
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


# --- 7. 검증 지적 보완(Phase 0.2 fix) ------------------------------------------

def test_common_word_name_does_not_mask_ordinary_words(client, capture):
    """근로자 이름이 '하나'여도 '하나씩'·'하나하나'·'컵 하나' 같은 낱말은 바뀌면 안 된다.
    예전에는 '컵을 근로자 A씩 꺼내서 근로자 A근로자 A 닦으세요.'가 LLM으로 갔다."""
    token = _new_employer(client)
    wid = _create_worker(client, token, "하나")
    r = client.post("/api/tasks", json={"raw_input": "컵을 하나씩 꺼내서 하나하나 닦으세요. 컵 하나를 두세요."},
                    headers=auth(token))
    assert r.status_code == 201, r.text
    assert capture.calls[0][1]["raw_input"] == "컵을 하나씩 꺼내서 하나하나 닦으세요. 컵 하나를 두세요."

    # 호칭이 붙어 이름이 분명할 때는 가린다.
    capture.calls.clear()
    client.post("/api/tasks", json={"raw_input": "하나 씨는 컵을 닦으세요."}, headers=auth(token))
    assert capture.calls[0][1]["raw_input"] == "근로자 A 씨는 컵을 닦으세요."

    # 사업주 화면 경고용 표시.
    workers = {w["id"]: w for w in client.get("/api/workers", headers=auth(token)).json()}
    assert workers[wid]["name_ambiguous"] is True
    other = _create_worker(client, token, "홍길동")
    workers = {w["id"]: w for w in client.get("/api/workers", headers=auth(token)).json()}
    assert workers[other]["name_ambiguous"] is False


def test_name_is_masked_only_at_word_boundaries():
    from privacy import Pseudonymizer
    p = Pseudonymizer(["홍길동", "김지우"])
    assert p.mask("홍길동 씨는 상자를") == "근로자 A 씨는 상자를"
    assert p.mask("홍길동이가 옮겨요") == "근로자 A이가 옮겨요"
    assert p.mask("홍길동에게서 받으세요.") == "근로자 A에게서 받으세요."
    assert p.mask("(김지우)") == "(근로자 B)"
    # 3음절 이상 이름은 앞뒤에 글자가 붙어도 바꾼다(fail-closed, 3차 검증 지적). 예전에는 이 꼴을 다른 낱말로
    # 보고 그대로 뒀는데, 같은 규칙 때문에 "팀장김민지가"·"김민지와박지수"의 실명이 LLM으로 갔다.
    assert p.mask("홍길동동 상자") == "근로자 A동 상자"
    assert p.mask("대김지우 상자") == "대근로자 B 상자"
    # 경계 규칙은 낱말과 헷갈릴 수 있는 2음절 이름에만 남는다 — 앞뒤에 글자가 붙어 다른 낱말이면 그대로 둔다.
    q = Pseudonymizer(["민지"])
    assert q.mask("민지에게서 받으세요.") == "근로자 A에게서 받으세요."
    assert q.mask("민지동 상자") == "민지동 상자"
    assert q.mask("대민지 상자") == "대민지 상자"


def test_unmask_accepts_spacing_variants_and_drops_unknown_alias(client, monkeypatch):
    """LLM이 '근로자A'처럼 띄어쓰기만 바꿔 돌려줘도 실명으로 되돌린다. 모르는 별칭은 화면·TTS에 나가지 않게
    '근로자'로 바꾼다."""
    token = _new_employer(client)
    _create_worker(client, token, "홍길동")

    def fake_decompose(raw_input, context=None):
        return {"task_title": "근로자A 직무", "steps": [
            {"order": 1, "sentence": "근로자A 님은 상자를 옮기세요.", "action_type": "move",
             "symbol_query": ["상자"], "keywords": [{"term": "상자", "pos": "noun"}]},
            {"order": 2, "sentence": "근로자   A와 근로자 Q는 수량을 세세요.", "action_type": "observe",
             "symbol_query": ["수량"], "keywords": [{"term": "수량", "pos": "noun"}]},
        ]}

    monkeypatch.setattr(ai_client, "decompose", fake_decompose)
    r = client.post("/api/tasks", json={"raw_input": "홍길동 님은 상자를 옮기세요."}, headers=auth(token))
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["title"] == "홍길동 직무"
    assert task["steps"][0]["sentence"] == "홍길동 님은 상자를 옮기세요."
    assert task["steps"][1]["sentence"] == "홍길동와 근로자는 수량을 세세요."


def test_one_off_actions_are_always_audited(client, capture):
    """폴링성 조회만 60초 안에서 묶는다. 내보내기를 두 번 했으면 두 줄이 남아야 한다."""
    token = _new_employer(client)
    emp = _employer_id(token)
    wid, _ = _coaching_setup(client, token, capture, name="내보내기대상")
    for _ in range(2):
        assert client.get(f"/api/workers/{wid}/export", headers=auth(token)).status_code == 200
    _grant(client, token, wid)
    _grant(client, token, wid, consent_type="personal_info")
    rows = _audits(emp)
    assert len([r for r in rows if r[0] == "worker.export"]) == 2
    assert len([r for r in rows if r[0] == "worker.consent.grant"]) == 2


def test_dashboard_and_coaching_reject_foreign_worker_id(client, capture):
    token = _new_employer(client)
    _, task = _coaching_setup(client, token, capture, name="우리근로자")
    other_token = _new_employer(client)
    foreign = _create_worker(client, other_token, "남의근로자")

    for path in (f"/api/dashboard/tasks/{task['id']}?worker_id={foreign}",
                 f"/api/dashboard/tasks/{task['id']}/coaching?worker_id={foreign}"):
        assert client.get(path, headers=auth(token)).status_code == 404
    with SessionLocal() as db:
        # 남의 사업장 근로자 id가 이 사업주의 감사 로그에 섞이지 않는다.
        assert db.scalars(select(AccessAuditLog).where(
            AccessAuditLog.actor_id == _employer_id(token),
            AccessAuditLog.worker_id == foreign)).all() == []
    assert capture.calls == []


def test_delete_reports_tasks_that_still_mention_the_name(client, capture):
    """직무는 사업주 데이터라 근로자 삭제로 지우지 않는다. 이름이 남은 직무를 알려 줘 고치게 한다."""
    token = _new_employer(client)
    wid, task = _coaching_setup(client, token, capture, name="이름남는근로자")
    plain = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요."}, headers=auth(token)).json()
    r = delete_worker(client, wid, auth(token))
    assert r.status_code == 200, r.text
    mentions = [m["task_id"] for m in r.json()["name_mentions"]]
    assert task["id"] in mentions
    assert plain["id"] not in mentions


def test_delete_with_open_reader_retries_and_purge_finishes_checkpoint(client, capture, monkeypatch, tmp_path,
                                                                        caplog):
    """다른 연결(예: 3초 폴링)이 읽기 트랜잭션을 잡고 있으면 삭제 직후 체크포인트가 끝나지 않는다.
    그 사실을 응답·로그로 알리고, purge가 다시 TRUNCATE 체크포인트를 해서 -wal의 옛 프레임을 없앤다."""
    import sqlite3

    import database
    monkeypatch.setattr(database, "_CHECKPOINT_ATTEMPTS", 2)
    monkeypatch.setattr(database, "_CHECKPOINT_RETRY_SLEEP", 0.01)
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))

    token = _new_employer(client)
    name = "열린읽기중삭제대상"
    wid, task = _coaching_setup(client, token, capture, name=name)
    delete_task(client, task['id'], auth(token))

    reader = sqlite3.connect(engine.url.database, isolation_level=None)
    try:
        reader.execute("BEGIN")
        reader.execute("SELECT count(*) FROM workers").fetchone()
        with caplog.at_level("WARNING", logger="jobcard.database"):
            r = delete_worker(client, wid, auth(token))
        assert r.status_code == 200, r.text
        assert r.json()["wal_checkpointed"] is False
        assert "WAL 체크포인트" in caplog.text
        assert name.encode("utf-8") in _db_files_bytes()  # 재현: 아직 -wal에 남아 있다
    finally:
        reader.execute("COMMIT")
        reader.close()

    with SessionLocal() as db:
        report = retention.purge(db)
    assert report["wal_checkpointed"] is True
    assert name.encode("utf-8") not in _db_files_bytes()


# --- 8. 2차 검증 지적 보완(Phase 0.2 fix 2) -----------------------------------

# 한국어 조사·어미는 겹쳐 붙는다. 예전 경계 규칙(접사 하나 + 조사 하나)은 이 꼴의 실명을 그대로 보냈다.
_COMPOUND_FORMS = ["에게는", "한테도", "랑은", "는요", "님께서는", "와는", "에게도", "만은", "네", "도요",
                   "한테서는", "보다는", "께는", "씨였어요", "이가요"]


@pytest.mark.parametrize("tail", _COMPOUND_FORMS)
def test_compound_particles_are_masked(tail):
    from privacy import Pseudonymizer
    p = Pseudonymizer(["김민지", "John"])
    assert p.mask(f"{'김민지'}{tail} 상자를 주세요.") == f"근로자 A{tail} 상자를 주세요."


def test_latin_name_is_masked_case_insensitively_with_compound_particles():
    from privacy import Pseudonymizer
    p = Pseudonymizer(["John"])
    assert p.mask("John에게는 컵을") == "근로자 A에게는 컵을"
    assert p.mask("john은 컵을, JOHN도요") == "근로자 A은 컵을, 근로자 A도요"
    # 다른 낱말의 일부는 그대로 둔다.
    assert p.mask("Johnson 상자") == "Johnson 상자"
    # 대소문자만 다른 이름은 같은 사람으로 보고 별칭을 하나만 만든다.
    assert Pseudonymizer(["John", "john"]).mask("john") == "근로자 A"


def test_unmask_keeps_ordinary_uppercase_words():
    """'근로자 ID'·'근로자 OK'·'근로자 TV'는 별칭이 아니다. 지우면 코칭·분해 문장이 망가진다."""
    from privacy import Pseudonymizer
    p = Pseudonymizer(["홍길동"])
    assert p.unmask("근로자 ID를 확인하고 근로자 OK 사인을 받고 근로자 TV를 끄세요.") == \
        "근로자 ID를 확인하고 근로자 OK 사인을 받고 근로자 TV를 끄세요."
    # 만든 별칭은 되돌리고, 지어낸 한 글자 별칭은 '근로자'로 바꾼다.
    assert p.mask("홍길동") == "근로자 A"
    assert p.unmask("근로자 A와 근로자 C") == "홍길동와 근로자"
    # 두 글자 별칭은 실제로 만든 것만 되돌린다.
    many = Pseudonymizer([f"근로자이름{i:02d}" for i in range(28)])
    assert many.mask("근로자이름27 님") == "근로자 AB 님"
    assert many.unmask("근로자 AB 님") == "근로자이름27 님"
    assert many.unmask("근로자 ZZ 님") == "근로자 ZZ 님"


def test_compound_forms_never_reach_ai_payloads(client, capture):
    """직무 생성(분해)·단계 추가(그림 검색)·코칭 세 경로의 AI 페이로드 어디에도 실명이 없어야 한다."""
    token = _new_employer(client)
    name = "정하늘"
    wid = _create_worker(client, token, name)
    raw = (f"{name}에게는 상자를 주세요. {name}한테도 알려 주세요. {name}와는 같이 옮기세요. "
           f"{name}는요 컵을 닦아요. {name}님께서는 쉬세요. {name}네 자리 옆에 두세요.")
    r = client.post("/api/tasks", json={"raw_input": raw, "work_environment": f"{name}네 창고"},
                    headers=auth(token))
    assert r.status_code == 201, r.text
    task = r.json()
    # 응답은 실명으로 되돌아와 저장된다.
    assert task["steps"][0]["sentence"] == f"{name}에게는 상자를 주세요."

    r = client.post(f"/api/tasks/{task['id']}/steps",
                    json={"sentence": f"{name}에게도 장갑을 주세요.", "action_type": "move"}, headers=auth(token))
    assert r.status_code == 201, r.text

    _publish_assign_log(client, token, task["id"], wid)
    _grant(client, token, wid)
    r = client.get(f"/api/dashboard/tasks/{task['id']}/coaching?worker_id={wid}", headers=auth(token))
    assert r.status_code == 200, r.text

    kinds = {k for k, _ in capture.calls}
    assert {"decompose", "map_symbols", "coaching"} <= kinds
    sent = capture.dump()
    assert name not in sent
    assert "근로자 A에게는" in sent and "근로자 A님께서는" in sent and "근로자 A네 창고" in sent


def test_symbol_search_context_drops_unknown_fields(client, capture):
    """그림 검색 맥락도 백엔드가 아는 필드만 보낸다(이름 필드가 끼어들 자리가 없다)."""
    token = _new_employer(client)
    _create_worker(client, token, "오민수")
    client.post("/api/tasks", json={"raw_input": "오민수에게는 상자를 주세요."}, headers=auth(token))
    contexts = [p["context"] for k, p in capture.calls if k == "map_symbols"]
    assert contexts
    allowed = {"business_type", "work_environment", "job", "job_hint", "sentence", "action_type", "raw_input"}
    for ctx in contexts:
        assert set(ctx) <= allowed
        assert "오민수" not in json.dumps(ctx, ensure_ascii=False)


def test_aggregate_views_audit_each_included_worker(client, capture):
    """근로자를 고르지 않은 집계 화면도 누구의 기록이 보였는지 근로자마다 남긴다."""
    token = _new_employer(client)
    emp = _employer_id(token)
    wid, task = _coaching_setup(client, token, capture, name="집계대상하나")
    other = _create_worker(client, token, "집계대상둘")
    client.post(f"/api/tasks/{task['id']}/assignments", json={"worker_ids": [other]}, headers=auth(token))
    with SessionLocal() as db:
        a = db.scalar(select(Assignment).where(Assignment.worker_id == other))
        steps = db.scalars(select(Step).where(Step.task_id == task["id"]).order_by(Step.order_index)).all()
        db.add(PerformanceLog(assignment_id=a.id, step_id=steps[0].id, duration_sec=10))
        db.commit()

    assert client.get(f"/api/dashboard/tasks/{task['id']}/workers", headers=auth(token)).status_code == 200
    assert client.get(f"/api/dashboard/tasks/{task['id']}", headers=auth(token)).status_code == 200
    assert client.get(f"/api/dashboard/tasks/{task['id']}/coaching", headers=auth(token)).status_code == 200

    actions = {(a, w) for a, w, _ in _audits(emp)}
    for action in ("dashboard.workers", "dashboard.view", "coaching.view"):
        assert (action, wid) in actions, action
        assert (action, other) in actions, action
        assert (action, None) not in actions, action


def test_aggregate_view_without_workers_still_audited(client, capture):
    token = _new_employer(client)
    emp = _employer_id(token)
    task = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요."}, headers=auth(token)).json()
    client.get(f"/api/dashboard/tasks/{task['id']}", headers=auth(token))
    assert ("dashboard.view", None) in {(a, w) for a, w, _ in _audits(emp)}


def test_personal_info_consent_is_listed(client):
    token = _new_employer(client)
    wid = _create_worker(client, token, "수집동의대상")
    w = next(x for x in client.get("/api/workers", headers=auth(token)).json() if x["id"] == wid)
    assert w["personal_info_consent"] is False and w["ai_consent"] is False
    _grant(client, token, wid, consent_type="personal_info")
    w = next(x for x in client.get("/api/workers", headers=auth(token)).json() if x["id"] == wid)
    assert w["personal_info_consent"] is True and w["ai_consent"] is False


def test_tts_cache_hit_refreshes_mtime(monkeypatch, tmp_path):
    import tts
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    path = tmp_path / f"{tts._google_voice_key('상자를 옮기세요.', 'emp-x')}.mp3"
    path.write_bytes(b"x")
    old = time.time() - 3 * 86400
    os.utime(path, (old, old))
    assert tts.synthesize_tts("상자를 옮기세요.", "emp-x")
    assert path.stat().st_mtime > time.time() - 60


def test_purge_does_not_delete_tts_reused_during_purge(client, capture, monkeypatch, tmp_path):
    """purge가 고아 파일을 고른 뒤 지우기 전에, 새 단계가 같은 문장의 캐시를 다시 쓰면 지우지 않는다."""
    import tts
    monkeypatch.setenv("TTS_CACHE_DIR", str(tmp_path))
    token = _new_employer(client)
    task = client.post("/api/tasks", json={"raw_input": "상자를 옮기세요."}, headers=auth(token)).json()
    sentence = "오래된 캐시 문장입니다."
    with SessionLocal() as db:
        employer_id = db.scalars(select(Step).where(Step.task_id == task["id"])).first().task.employer_id
    path = tmp_path / f"{tts._google_voice_key(sentence, employer_id)}.mp3"
    path.write_bytes(b"x")
    old = time.time() - 3 * 86400
    os.utime(path, (old, old))

    real_checkpoint = retention.checkpoint_wal

    def reuse_then_checkpoint(db):
        # 고른 뒤·지우기 전 사이에 직무 수정이 같은 문장을 다시 쓴 상황(캐시 재사용 + 소유 레코드 생성).
        key = tts.synthesize_tts(sentence, employer_id)
        with SessionLocal() as other:
            step = other.scalars(select(Step).where(Step.task_id == task["id"])).first()
            step.tts_media_id = media.create_record(other, employer_id, media.KIND_TTS, key).id
            other.commit()
        return real_checkpoint(db)

    monkeypatch.setattr(retention, "checkpoint_wal", reuse_then_checkpoint)
    with SessionLocal() as db:
        report = retention.purge(db)
    assert path.exists()
    assert report["tts_files"] == 0


# --- 9. 3차 검증 지적 보완(Phase 0.2 fix 3) -----------------------------------

# 허용 목록(_TAIL_PIECES)에 없어 실명이 그대로 나가던 꼴(3차 검증에서 '김민지'로 확인됨).
_LEAKING_FORMS = ["에겐", "한텐", "께선", "에선", "엔", "론", "으론", "이란", "란", "라서", "이라서", "면", "이면",
                  "일", "잖아", "래", "라", "이라", "이니까", "니까", "이므로", "임", "꺼", "거", "것"]


@pytest.mark.parametrize("tail", _LEAKING_FORMS)
def test_three_syllable_name_is_masked_whatever_follows(tail):
    """3음절 이상 이름은 뒤에 무엇이 붙든 가린다(fail-closed). 띄어 쓰지 않은 복합어 속 이름도 가린다."""
    from privacy import Pseudonymizer
    p = Pseudonymizer(["김민지", "박지수"])
    assert p.mask(f"김민지{tail} 상자를 주세요.") == f"근로자 A{tail} 상자를 주세요."
    assert p.mask("팀장김민지가 보세요.") == "팀장근로자 A가 보세요."
    assert p.mask("김민지와박지수는 컵을") == "근로자 A와근로자 B는 컵을"


@pytest.mark.parametrize("tail", _LEAKING_FORMS)
def test_two_syllable_name_is_masked_with_colloquial_tails(tail):
    """2음절 이름은 아직 경계 규칙(허용 목록)에 기대므로, 확인된 줄임꼴·구어체를 목록에 더했다."""
    from privacy import Pseudonymizer
    p = Pseudonymizer(["민지"])
    assert p.mask(f"민지{tail} 상자를 주세요.") == f"근로자 A{tail} 상자를 주세요."


def test_spaced_and_latin_names_are_masked_without_tail_list():
    from privacy import Pseudonymizer
    p = Pseudonymizer(["김 민지", "John"])
    assert p.mask("팀장김 민지라서 천천히") == "팀장근로자 A라서 천천히"
    assert p.mask("John에겐 컵, john이니까 천천히, 팀장John잖아") == "근로자 B에겐 컵, 근로자 B이니까 천천히, 팀장근로자 B잖아"
    assert p.mask("Johnson 상자") == "Johnson 상자"


@pytest.mark.parametrize("tail", _LEAKING_FORMS)
def test_leaking_forms_never_reach_any_ai_payload(client, capture, monkeypatch, tail):
    """분해·그림 검색(단계 추가)·AAC 검색·코칭 네 경로의 AI 페이로드 어디에도 실명이 없어야 한다.
    3차 검증에서 '김민지에겐 …, 김민지라서 …'가 ai_client.decompose까지 그대로 갔다."""
    searched = []
    monkeypatch.setattr(ai_client, "search_aac", lambda query, context=None, limit=5: (
        searched.append({"query": query, "context": context}) or {"query": query, "matches": []}))
    token = _new_employer(client)
    wid = _create_worker(client, token, "김민지")
    _create_worker(client, token, "박지수")

    raw = (f"김민지{tail} 상자를 옮기세요. 팀장김민지가 보세요. 김민지와박지수는 컵을 닦으세요. "
           "김민지에겐 상자를 주고, 김민지한텐 컵을 맡기세요. 김민지라서 천천히.")
    r = client.post("/api/tasks", json={"raw_input": raw, "work_environment": "팀장김민지네 창고"},
                    headers=auth(token))
    assert r.status_code == 201, r.text
    task = r.json()
    # 응답은 실명으로 되돌아와 저장된다.
    assert task["steps"][0]["sentence"] == f"김민지{tail} 상자를 옮기세요."

    r = client.post(f"/api/tasks/{task['id']}/steps",
                    json={"sentence": f"팀장김민지{tail} 장갑을 주세요.", "action_type": "move"}, headers=auth(token))
    assert r.status_code == 201, r.text
    r = client.post("/api/aac/search", json={"query": f"김민지{tail} 컵"}, headers=auth(token))
    assert r.status_code == 200, r.text

    _publish_assign_log(client, token, task["id"], wid)
    _grant(client, token, wid)
    r = client.get(f"/api/dashboard/tasks/{task['id']}/coaching?worker_id={wid}", headers=auth(token))
    assert r.status_code == 200, r.text

    kinds = {k for k, _ in capture.calls}
    assert {"decompose", "map_symbols", "coaching"} <= kinds
    assert searched
    sent = capture.dump() + json.dumps(searched, ensure_ascii=False)
    assert "김민지" not in sent and "박지수" not in sent
    assert f"근로자 A{tail}" in sent


def test_unmask_leaves_alias_like_text_the_employer_wrote(client, capture):
    """근로자가 한 명뿐인데 사업주가 원문에 '근로자 B'라고 쓴 경우, 그 글은 응답에서 그대로 남아야 한다.
    예전에는 이 요청에서 만들지 않은 한 글자 별칭이라며 '근로자'로 바꿔 사업주 글을 몰래 고쳤다."""
    token = _new_employer(client)
    _create_worker(client, token, "홍길동")
    r = client.post("/api/tasks", json={"raw_input": "근로자 B는 상자를 옮기세요. 홍길동 씨는 수량을 세세요."},
                    headers=auth(token))
    assert r.status_code == 201, r.text
    assert capture.calls[0][1]["raw_input"] == "근로자 B는 상자를 옮기세요. 근로자 A 씨는 수량을 세세요."
    task = r.json()
    assert task["title"] == "근로자 B는 상자를 옮기세요 직무"
    assert task["steps"][0]["sentence"] == "근로자 B는 상자를 옮기세요."


def test_unmask_restores_only_aliases_this_request_produced():
    """이번 요청 원문에 나오지 않은 근로자의 별칭을 LLM이 돌려주면 실명으로 되돌리지 않는다(엉뚱한 실명 노출 방지)."""
    from privacy import Pseudonymizer
    p = Pseudonymizer(["홍길동", "김영희"])
    assert p.mask("홍길동 씨는 상자를") == "근로자 A 씨는 상자를"
    assert p.unmask("근로자 A 씨와 근로자 B 씨") == "홍길동 씨와 근로자 씨"


def test_worker_list_audits_each_listed_worker_with_polling_dedupe(client):
    token = _new_employer(client)
    emp = _employer_id(token)
    a = _create_worker(client, token, "목록대상가")
    b = _create_worker(client, token, "목록대상나")
    for _ in range(3):
        assert client.get("/api/workers", headers=auth(token)).status_code == 200
    rows = [(act, w) for act, w, _ in _audits(emp) if act == "worker.list"]
    assert sorted(rows) == sorted([("worker.list", a), ("worker.list", b)])


def _race_delete_assignment_on_flush(assignment_id):
    """create_log가 배정을 읽은 뒤 커밋하기 전에 다른 연결이 그 배정을 지운 상황(근로자 삭제)을 만든다."""
    import sqlite3

    from sqlalchemy import event
    from sqlalchemy.orm import Session as OrmSession

    fired = []

    def _delete(session, flush_context, instances):
        # 리스너 안에서 event.remove를 하면 SQLAlchemy가 순회 중 변경 오류를 낸다. 한 번만 돌게 표시로 막는다.
        if fired:
            return
        fired.append(True)
        other = sqlite3.connect(engine.url.database, isolation_level=None)
        try:
            other.execute("DELETE FROM performance_logs WHERE assignment_id = ?", (assignment_id,))
            other.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
        finally:
            other.close()

    event.listen(OrmSession, "before_flush", _delete)
    return _delete


@pytest.mark.parametrize("last_step", [False, True])
def test_log_upload_racing_worker_deletion_leaves_no_orphan(client, employer_token, worker_token, last_step):
    """배정이 커밋 직전에 사라지면 404로 끝나고 고아 수행 로그가 남지 않는다(500·StaleDataError도 아님)."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session as OrmSession

    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"}, headers=auth(employer_token))
    task = r.json()
    publish(client, employer_token, task["id"])
    assignment = client.post(f"/api/tasks/{task['id']}/assignments", headers=auth(employer_token)).json()[0]
    # (2a-0) 로그는 배정에 고정된 버전 단계 id로 보낸다(근로자 화면이 받는 id). 편집 단계 id와 다르다.
    card = next(c for c in client.get("/api/worker/me/today", headers=auth(worker_token)).json()
                if c["assignment_id"] == assignment["id"])
    steps = [s["id"] for s in card["steps"]]
    body = {"assignment_id": assignment["id"], "duration_sec": 3.0, "replay_count": 0, "stuck": False}
    if last_step:
        # 마지막 단계면 배정 상태도 갱신한다 — 지워진 배정의 UPDATE가 StaleDataError를 내던 경로.
        assert client.post("/api/performance-logs", headers=auth(worker_token),
                           json={**body, "step_id": steps[0]}).status_code == 201

    hook = _race_delete_assignment_on_flush(assignment["id"])
    try:
        r = client.post("/api/performance-logs", headers=auth(worker_token), json={**body, "step_id": steps[-1]})
    finally:
        if event.contains(OrmSession, "before_flush", hook):
            event.remove(OrmSession, "before_flush", hook)
    assert r.status_code == 404, r.text
    with SessionLocal() as db:
        assert db.scalars(select(PerformanceLog).where(
            PerformanceLog.assignment_id == assignment["id"])).all() == []
