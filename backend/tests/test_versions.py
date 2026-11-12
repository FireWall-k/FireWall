"""2a-0 버전 고정 시험 (scratchpad/p2/contract.md §1).

지키는 것:
- 하는 중에 사업주가 보낸 직무를 고쳐도(단계 삭제·추가·순서·문장·그림) 근로자 화면·진행·완료 판정·로그 수는 그대로다
  (결정 5: 고친 내용은 다음 배정부터).
- 편집(rewrite 나누기·merge·delete)이 로그·도움을 지우거나 끊지 않는다(백필 직무: 버전 1 단계 id = step id).
- 버전 단계가 쓰는 사진은 편집기에서 바꿔도 남고, 직무를 지우면 함께 지워진다(media GC가 버전 참조를 셈).
- /api/worker/me/today·/me/history 응답 모양은 cfa5396과 같다(task_version_no만 더함) — 스키마 스냅샷.
읽기 경로 시험은 0007 뒤 send로 만든 버전 2(새 uuid)로 돌린다(백필 id가 step id와 같아 옛 경로가 우연히 맞는 것을 막음).
네트워크·GPT·TTS를 부르지 않는다(conftest 목).
"""
import json
import os
import sys
from datetime import timedelta
from io import BytesIO
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402
from PIL import Image  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

import clock  # noqa: E402
import media  # noqa: E402
import schemas  # noqa: E402
from conftest import auth, give_pictures, delete_task  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import (  # noqa: E402
    Assignment,
    HelpRequest,
    MediaFile,
    PerformanceLog,
    Step,
    Task,
    TaskVersion,
    TaskVersionStep,
)

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
OTHER_AAC_IMAGE = "/api/aac/images/cafe/CAFE_013.webp"


# --- 준비 ---------------------------------------------------------------------------------

@pytest.fixture()
def worker(client, employer_token):
    r = client.post("/api/workers", json={"display_name": "버전시험"}, headers=auth(employer_token))
    assert r.status_code == 201, r.text
    w = r.json()
    login = client.post("/api/auth/worker-login",
                        json={"workplace_code": "DEMO01", "access_code": w["access_code"]})
    assert login.status_code == 200, login.text
    w["token"] = login.json()["token"]
    yield w
    client.delete(f"/api/workers/{w['id']}", headers=auth(employer_token))


def _task(client, token):
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"}, headers=auth(token))
    assert r.status_code == 201, r.text
    give_pictures(client, token, r.json()["id"])
    return client.get(f"/api/tasks/{r.json()['id']}", headers=auth(token)).json()


def _send(client, token, task_id, worker_ids, day="today"):
    return client.post(f"/api/tasks/{task_id}/send", headers=auth(token),
                       json={"worker_ids": worker_ids, "day": day})


def _cards(client, wtoken, include_done=True):
    r = client.get(f"/api/worker/me/today?include_done={str(include_done).lower()}", headers=auth(wtoken))
    assert r.status_code == 200, r.text
    return r.json()


def _card(client, wtoken, assignment_id):
    return next(c for c in _cards(client, wtoken) if c["assignment_id"] == assignment_id)


def _log(client, wtoken, aid, sid, **extra):
    body = {"assignment_id": aid, "step_id": sid, "duration_sec": 4.0, "replay_count": 0, "stuck": False}
    body.update(extra)
    return client.post("/api/performance-logs", headers=auth(wtoken), json=body)


def _edit_steps(client, token, task_id):
    return client.get(f"/api/tasks/{task_id}", headers=auth(token)).json()["steps"]


def _sent_v2(client, token, worker):
    """보내서 버전 1, 문장을 고쳐 다시 보내 버전 2(새 uuid)에 묶인 배정. 근로자가 아직 받기 전이라 repinned."""
    task = _task(client, token)
    first = _send(client, token, task["id"], [worker["id"]])
    assert first.status_code == 200, first.text
    assert first.json()["version_no"] == 1 and first.json()["results"][0]["outcome"] == "created"
    sid = task["steps"][0]["id"]
    assert client.patch(f"/api/tasks/{task['id']}/steps/{sid}", headers=auth(token),
                        json={"sentence": "상자를 천천히 옮기세요."}).status_code == 200
    second = _send(client, token, task["id"], [worker["id"]])
    assert second.status_code == 200, second.text
    assert second.json()["version_no"] == 2 and second.json()["version_created"] is True
    assert second.json()["results"][0]["outcome"] == "repinned"
    card = next(c for c in _cards(client, worker["token"]) if c["task_id"] == task["id"])
    assert card["task_version_no"] == 2
    return task, card


def _log_count(aid):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(PerformanceLog)
                         .where(PerformanceLog.assignment_id == aid))


def _view(card):
    return {"steps": [(s["id"], s["order"], s["sentence"], s["symbol_url"], s["picture_state"])
                      for s in card["steps"]],
            "done": card["done_step_ids"], "resume": card["resume_step_index"], "status": card["status"],
            "title": card["task_title"], "version": card["task_version_no"]}


# --- 완료 기준 1: 하는 중에 고쳐도 그대로 --------------------------------------------------

def test_edit_during_work_keeps_progress(client, employer_token, worker):
    task, card = _sent_v2(client, employer_token, worker)
    aid = card["assignment_id"]
    vids = [s["id"] for s in card["steps"]]
    edit_ids = {s["id"] for s in _edit_steps(client, employer_token, task["id"])}
    assert not set(vids) & edit_ids  # 버전 단계는 새 uuid(편집 단계 id와 다르다)
    assert card["steps"][0]["sentence"] == "상자를 천천히 옮기세요."

    assert _log(client, worker["token"], aid, vids[0]).status_code == 201
    before = _view(_card(client, worker["token"], aid))
    assert before["done"] == [vids[0]] and before["resume"] == 1 and before["status"] == "in_progress"
    emp = auth(employer_token)
    tid = task["id"]

    def delete_step():
        steps = _edit_steps(client, employer_token, tid)
        return client.delete(f"/api/tasks/{tid}/steps/{steps[0]['id']}", headers=emp)

    def add_step():
        return client.post(f"/api/tasks/{tid}/steps", headers=emp, json={"sentence": "바닥을 닦아요."})

    def reorder():
        ids = [s["id"] for s in _edit_steps(client, employer_token, tid)]
        return client.patch(f"/api/tasks/{tid}/steps/reorder", headers=emp, json={"step_ids": ids[::-1]})

    def change_sentence():
        steps = _edit_steps(client, employer_token, tid)
        return client.patch(f"/api/tasks/{tid}/steps/{steps[0]['id']}", headers=emp,
                            json={"sentence": "수량을 두 번 세요."})

    def change_picture():
        steps = _edit_steps(client, employer_token, tid)
        return client.patch(f"/api/tasks/{tid}/steps/{steps[-1]['id']}", headers=emp,
                            json={"symbol_url": OTHER_AAC_IMAGE, "symbol_source": "LOCAL_AAC"})

    for edit in (delete_step, add_step, reorder, change_sentence, change_picture):
        r = edit()
        assert r.status_code in (200, 201), (edit.__name__, r.text)
        assert _view(_card(client, worker["token"], aid)) == before, edit.__name__
        assert _log_count(aid) == 1, edit.__name__

    # 사업주 쪽에서는 '고친 내용 안 보냄'이 보인다.
    got = client.get(f"/api/tasks/{tid}", headers=emp).json()
    assert got["version"] == {"current_no": 2, "has_unsent_changes": True}
    assert got["in_progress_count"] == 1 and got["recipients_count"] == 1

    done = _log(client, worker["token"], aid, vids[1])
    assert done.status_code == 201 and done.json()["assignment_status"] == "done"
    assert _log_count(aid) == 2
    final = _card(client, worker["token"], aid)
    assert final["status"] == "done" and final["done_step_ids"] == vids


# --- 완료 기준 2: 편집이 로그·도움을 지우지 않는다(백필 직무) --------------------------------

def _backfilled(client, token, worker):
    """0007 백필과 같은 상태: 보낸 직무의 버전 1(단계 id = step id, source = id), 배정은 버전 1·받음으로."""
    task = _task(client, token)
    assert client.post(f"/api/tasks/{task['id']}/publish", headers=auth(token)).status_code == 200
    now = clock.utcnow()
    with SessionLocal() as db:
        t = db.get(Task, task["id"])
        v = TaskVersion(task_id=t.id, version_no=1, title=t.title, created_by=t.employer_id)
        for s in t.steps:
            v.steps.append(TaskVersionStep(
                id=s.id, source_step_id=s.id, order_index=s.order_index, sentence=s.sentence,
                action_type=s.action_type, symbol_query=s.symbol_query, symbol_url=s.symbol_url,
                symbol_source=s.symbol_source, symbol_media_id=s.symbol_media_id, tts_media_id=s.tts_media_id))
        db.add(v)
        db.flush()
        t.current_version_id = v.id
        a = Assignment(task_id=t.id, worker_id=worker["id"], assigned_date=now, scheduled_day=clock.local_today(),
                       task_version_id=v.id, pinned_at=now, first_seen_at=now)
        db.add(a)
        db.commit()
        return task, a.id


def test_backfilled_rewrite_merge_delete_keep_logs_and_help(client, employer_token, worker):
    task, aid = _backfilled(client, employer_token, worker)
    s1, s2 = (s["id"] for s in task["steps"])
    emp = auth(employer_token)
    assert _log(client, worker["token"], aid, s1).status_code == 201  # 옛 기기: 단계 id = step id
    help_row = client.post("/api/worker/help", headers=auth(worker["token"]),
                           json={"assignment_id": aid, "step_id": s2})
    assert help_row.status_code == 201, help_row.text

    def counts():
        with SessionLocal() as db:
            logs = db.scalar(select(func.count()).select_from(PerformanceLog)
                             .where(PerformanceLog.assignment_id == aid))
            helps = db.scalars(select(HelpRequest.step_id).where(HelpRequest.assignment_id == aid)).all()
        return logs, helps

    assert counts() == (1, [s2])
    # 1) 보낸 직무에서 문장을 고쳐 두 단계로 나눈다(예전에는 보낸 직무를 나누지 않았다).
    split = client.post(f"/api/tasks/{task['id']}/steps/{s1}/rewrite", headers=emp,
                        json={"sentence": "컵 씻어서 건조대에 올려요"})
    assert split.status_code == 200 and len(split.json()["split_step_ids"]) == 2
    assert counts() == (1, [s2])
    # 2) [되돌리기] 합치기(예전에는 보낸 직무에서 409)
    merged = client.post(f"/api/tasks/{task['id']}/steps/merge", headers=emp,
                         json={"step_ids": split.json()["split_step_ids"], "sentence": "컵 씻어서 건조대에 올려요"})
    assert merged.status_code == 200, merged.text
    assert counts() == (1, [s2])
    # 3) 도움을 부른 단계를 편집기에서 지운다(예전에는 로그를 지우고 도움을 끊었다).
    assert client.delete(f"/api/tasks/{task['id']}/steps/{s2}", headers=emp).status_code == 200
    assert counts() == (1, [s2])
    with SessionLocal() as db:
        assert db.get(Step, s2) is None and db.get(TaskVersionStep, s2) is not None

    card = _card(client, worker["token"], aid)
    assert [s["id"] for s in card["steps"]] == [s1, s2] and card["done_step_ids"] == [s1]
    row = next(x for x in client.get("/api/employer/help", headers=emp).json() if x["id"] == help_row.json()["id"])
    assert row["step_id"] == s2 and row["step_order"] == 2 and row["step_sentence"] == task["steps"][1]["sentence"]
    # 옛 기기 대기열의 2단계 기록도 들어가고 배정이 끝난다(지운 편집 단계와 상관없다).
    last = _log(client, worker["token"], aid, s2)
    assert last.status_code == 201 and last.json()["assignment_status"] == "done"
    dash = client.get(f"/api/dashboard/tasks/{task['id']}?worker_id={worker['id']}", headers=emp).json()
    assert dash["total_steps"] == 2 and dash["completed_steps"] == 2 and dash["stuck_steps"] == [2]


def test_dashboard_aggregate_groups_versions_by_source_step(client, employer_token, worker):
    """근로자를 고르지 않은 대시보드는 마지막 버전 단계에 source_step_id가 같은 옛 버전 기록을 모아 보인다(§1.6)."""
    task, card = _sent_v2(client, employer_token, worker)
    aid = card["assignment_id"]
    for s in card["steps"]:
        assert _log(client, worker["token"], aid, s["id"]).status_code == 201
    dash = client.get(f"/api/dashboard/tasks/{task['id']}", headers=auth(employer_token)).json()
    assert dash["completed_steps"] == 2 and dash["total_steps"] == 2
    assert [s["sentence"] for s in dash["steps"]] == [s["sentence"] for s in card["steps"]]


def test_worker_dashboard_keeps_today_when_edited_job_sent_for_tomorrow(client, employer_token, worker):
    """근로자를 고른 대시보드는 오늘 하는 중인 배정 하나만 센다(§1.6, 1회차 검증). 사업주가 단계를 지우고 내일로
    다시 보내도(created) 아직 시작 전인 내일 배정 대신 오늘 배정의 고정 버전 단계·기록을 그대로 보인다."""
    task = _task(client, employer_token)
    r = client.post(f"/api/tasks/{task['id']}/steps", headers=auth(employer_token), json={"sentence": "바닥을 쓸어요."})
    assert r.status_code == 201, r.text
    give_pictures(client, employer_token, task["id"])
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200
    card = next(c for c in _cards(client, worker["token"]) if c["task_id"] == task["id"])
    vids = [s["id"] for s in card["steps"]]
    assert len(vids) == 3
    for sid in vids[:2]:
        assert _log(client, worker["token"], card["assignment_id"], sid).status_code == 201
    url = f"/api/dashboard/tasks/{task['id']}?worker_id={worker['id']}"
    before = client.get(url, headers=auth(employer_token)).json()
    assert before["total_steps"] == 3 and before["completed_steps"] == 2

    steps = _edit_steps(client, employer_token, task["id"])
    assert client.delete(f"/api/tasks/{task['id']}/steps/{steps[1]['id']}",
                         headers=auth(employer_token)).status_code == 200
    res = _send(client, employer_token, task["id"], [worker["id"]], day="tomorrow")
    assert res.status_code == 200 and res.json()["results"][0]["outcome"] == "created"
    after = client.get(url, headers=auth(employer_token)).json()
    assert after["total_steps"] == 3 and after["completed_steps"] == 2
    assert [s["sentence"] for s in after["steps"]] == [s["sentence"] for s in card["steps"]]
    coach = client.get(f"/api/dashboard/tasks/{task['id']}/coaching?worker_id={worker['id']}",
                       headers=auth(employer_token))
    assert coach.status_code == 200, coach.text


def test_worker_dashboard_does_not_count_yesterday_logs_on_new_assignment(client, employer_token, worker):
    """어제 1단계만 하고 못 끝낸 일을 오늘 다시 보내면 새 배정이다. 근로자 화면처럼 대시보드도 0단계 완료다
    (어제 기록이 단계 키로 합쳐져 오늘 배정에 새던 것, 1회차 검증)."""
    task = _task(client, employer_token)
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200
    c0 = next(c for c in _cards(client, worker["token"]) if c["task_id"] == task["id"])
    assert _log(client, worker["token"], c0["assignment_id"], c0["steps"][0]["id"]).status_code == 201
    with SessionLocal() as db:
        a = db.get(Assignment, c0["assignment_id"])
        a.scheduled_day -= timedelta(days=1)
        a.assigned_date -= timedelta(days=1)
        db.commit()
    res = _send(client, employer_token, task["id"], [worker["id"]])
    assert res.status_code == 200 and res.json()["results"][0]["outcome"] == "created"
    new = next(c for c in _cards(client, worker["token"]) if c["task_id"] == task["id"])
    assert new["done_step_ids"] == [] and new["status"] == "new"
    dash = client.get(f"/api/dashboard/tasks/{task['id']}?worker_id={worker['id']}",
                      headers=auth(employer_token)).json()
    assert dash["completed_steps"] == 0 and dash["stuck_steps"] == []


def test_worker_dashboard_with_only_future_assignment_shows_it(client, employer_token, worker):
    """내일로 보낸 배정만 있으면 그 배정의 단계를 0단계 완료로 보인다."""
    task = _task(client, employer_token)
    assert _send(client, employer_token, task["id"], [worker["id"]], day="tomorrow").status_code == 200
    dash = client.get(f"/api/dashboard/tasks/{task['id']}?worker_id={worker['id']}",
                      headers=auth(employer_token)).json()
    assert dash["total_steps"] == 2 and dash["completed_steps"] == 0


def test_log_for_step_of_other_version_is_rejected(client, employer_token, worker):
    """버전 단계 소속 검사: 같은 직무라도 배정이 묶이지 않은 버전의 단계 id는 400."""
    task, card = _sent_v2(client, employer_token, worker)
    with SessionLocal() as db:
        v1 = db.scalar(select(TaskVersion).where(TaskVersion.task_id == task["id"], TaskVersion.version_no == 1))
        old_ids = [vs.id for vs in v1.steps]
    r = _log(client, worker["token"], card["assignment_id"], old_ids[0])
    assert r.status_code == 400
    r = client.post("/api/worker/help", headers=auth(worker["token"]),
                    json={"assignment_id": card["assignment_id"], "step_id": old_ids[0]})
    assert r.status_code == 400


def test_history_reads_pinned_version(client, employer_token, worker):
    task, card = _sent_v2(client, employer_token, worker)
    aid = card["assignment_id"]
    _log(client, worker["token"], aid, card["steps"][0]["id"])
    tid = task["id"]
    steps = _edit_steps(client, employer_token, tid)
    client.patch(f"/api/tasks/{tid}/steps/{steps[1]['id']}", headers=auth(employer_token),
                 json={"sentence": "다른 문장으로 고쳤어요."})
    hist = client.get("/api/worker/me/history", headers=auth(worker["token"])).json()
    h = next(x for x in hist if x["assignment_id"] == aid)
    assert [s["id"] for s in h["steps"]] == [s["id"] for s in card["steps"]]
    assert [s["sentence"] for s in h["steps"]] == [s["sentence"] for s in card["steps"]]
    assert [s["completed"] for s in h["steps"]] == [True, False]
    assert h["assigned_date"] == clock.local_today().isoformat() and h["task_version_no"] == 2


def test_task_updated_at_moves_on_step_edit_not_on_send(client, employer_token, worker):
    task = _task(client, employer_token)
    t0 = client.get(f"/api/tasks/{task['id']}", headers=auth(employer_token)).json()["updated_at"]
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200
    t1 = client.get(f"/api/tasks/{task['id']}", headers=auth(employer_token)).json()["updated_at"]
    assert t1 == t0
    client.patch(f"/api/tasks/{task['id']}/steps/{task['steps'][0]['id']}", headers=auth(employer_token),
                 json={"sentence": "고친 문장이에요."})
    t2 = client.get(f"/api/tasks/{task['id']}", headers=auth(employer_token)).json()["updated_at"]
    assert t2 > t1


# --- 미디어: 버전이 쓰는 사진은 남는다 ----------------------------------------------------

def _jpeg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (64, 48), (10, 120, 200)).save(buf, "JPEG")
    return buf.getvalue()


def _path_of(url: str) -> str:
    p = urlparse(url)
    return f"{p.path}?{p.query}" if p.query else p.path


def test_media_kept_for_version(client, employer_token, worker):
    task = _task(client, employer_token)
    sid = task["steps"][0]["id"]
    up = client.post(f"/api/tasks/{task['id']}/steps/{sid}/photo", headers=auth(employer_token),
                     files={"file": ("p.jpg", _jpeg(), "image/jpeg")})
    assert up.status_code == 200, up.text
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200
    card = next(c for c in _cards(client, worker["token"]) if c["task_id"] == task["id"])
    url = card["steps"][0]["symbol_url"]
    media_id = urlparse(url).path.rsplit("/", 1)[-1]
    with SessionLocal() as db:
        key = db.get(MediaFile, media_id).storage_key

    # 편집기에서 사진을 지운다 → 편집 단계는 레코드를 놓지만 버전이 쓰므로 남는다.
    assert client.delete(f"/api/tasks/{task['id']}/steps/{sid}/photo",
                         headers=auth(employer_token)).status_code == 200
    with SessionLocal() as db:
        assert db.get(MediaFile, media_id) is not None
        media.gc(db, grace_hours=0)
        assert db.get(MediaFile, media_id) is not None
    assert media.media_path(media.KIND_PHOTO, key).is_file()
    again = next(c for c in _cards(client, worker["token"]) if c["task_id"] == task["id"])
    assert client.get(_path_of(again["steps"][0]["symbol_url"])).status_code == 200


def test_photo_moved_by_merge_or_split_stays_confirmed(client, employer_token, worker, monkeypatch):
    """사업주가 올린 사진을 합치기·나누기로 새 단계에 옮겨도 '확인함'이다(명세 §5.5). 예전에는 확인 안 한 자동
    그림(auto_high)이 되어 보낸 직무를 고친 뒤 다시 보내기가 422로 막혔다(1회차 검증)."""
    import ai_client
    task = _task(client, employer_token)
    tid = task["id"]
    s1, s2 = (s["id"] for s in task["steps"])
    up = client.post(f"/api/tasks/{tid}/steps/{s1}/photo", headers=auth(employer_token),
                     files={"file": ("p.jpg", _jpeg(), "image/jpeg")})
    assert up.status_code == 200, up.text
    assert _send(client, employer_token, tid, [worker["id"]]).status_code == 200

    r = client.post(f"/api/tasks/{tid}/steps/merge", headers=auth(employer_token),
                    json={"step_ids": [s1, s2], "sentence": "상자를 옮기고 수량을 확인해요"})
    assert r.status_code == 200, r.text
    merged = r.json()["steps"][0]
    assert merged["symbol_source"] == "photo" and merged["picture_state"] == "confirmed"
    sent = _send(client, employer_token, tid, [worker["id"]])
    assert sent.status_code == 200, sent.text

    def two(raw_input, context=None, **kw):
        return {"task_title": "t", "steps": [
            {"order": 1, "sentence": "상자를 옮겨요.", "action_type": "move", "symbol_query": ["상자"],
             "split_group": 1, "split_check": False, "source_text": raw_input},
            {"order": 2, "sentence": "수량을 세어요.", "action_type": "check", "symbol_query": ["수량"],
             "split_group": 1, "split_check": False, "source_text": raw_input},
        ]}
    monkeypatch.setattr(ai_client, "decompose", two)
    r = client.post(f"/api/tasks/{tid}/steps/{merged['id']}/rewrite", headers=auth(employer_token),
                    json={"sentence": "상자 옮기고 수량 세요"})
    assert r.status_code == 200, r.text
    first = r.json()["task"]["steps"][0]
    assert len(r.json()["split_step_ids"]) == 2
    assert first["symbol_source"] == "photo" and first["picture_state"] == "confirmed"
    check = client.get(f"/api/tasks/{tid}/send-check", headers=auth(employer_token)).json()
    unconfirmed = next(b for b in check["blocking"] if b["code"] == "unconfirmed_auto")
    assert first["id"] not in unconfirmed["step_ids"]


def test_media_released_after_task_delete(client, employer_token, worker):
    task = _task(client, employer_token)
    sid = task["steps"][0]["id"]
    client.post(f"/api/tasks/{task['id']}/steps/{sid}/photo", headers=auth(employer_token),
                files={"file": ("p.jpg", _jpeg(), "image/jpeg")})
    assert _send(client, employer_token, task["id"], [worker["id"]]).status_code == 200
    client.delete(f"/api/tasks/{task['id']}/steps/{sid}/photo", headers=auth(employer_token))
    with SessionLocal() as db:
        vs = db.scalar(select(TaskVersionStep).join(TaskVersion).where(TaskVersion.task_id == task["id"],
                                                                      TaskVersionStep.order_index == 1))
        media_id = vs.symbol_media_id
        key = db.get(MediaFile, media_id).storage_key
    assert delete_task(client, task['id'], auth(employer_token)).status_code == 200
    with SessionLocal() as db:
        assert db.get(MediaFile, media_id) is None
        assert db.scalar(select(func.count()).select_from(TaskVersion)
                         .where(TaskVersion.task_id == task["id"])) == 0
        assert db.scalar(select(func.count()).select_from(Assignment)
                         .where(Assignment.task_id == task["id"])) == 0
    assert not media.media_path(media.KIND_PHOTO, key).is_file()


# --- 완료 기준 4: 근로자 응답 모양 그대로(스키마 스냅샷) ---------------------------------------

def _baseline():
    with open(os.path.join(FIXTURES, "worker_schema_cfa5396.json"), encoding="utf-8") as f:
        return json.load(f)


_SAFETY_FLAG = {"default": False, "title": "Safety Flag", "type": "boolean"}


def _without_version_no(schema: dict) -> dict:
    """cfa5396 뒤에 더한 칸만 뺀다: 카드의 task_version_no(2a-0), 단계의 safety_flag(2b-1 조심 띠, 기본 false).
    그 밖의 칸은 하나도 바뀌지 않아야 한다."""
    schema = json.loads(json.dumps(schema))
    props = schema["properties"]
    assert props.pop("task_version_no") == {"anyOf": [{"type": "integer"}, {"type": "null"}],
                                            "default": None, "title": "Task Version No"}
    for name in ("StepOut", "HistoryStepOut"):
        step = schema["$defs"].get(name)
        if step is not None:
            assert step["properties"].pop("safety_flag") == _SAFETY_FLAG
    return schema


def test_worker_today_schema_snapshot(client, employer_token, worker):
    """cfa5396 TodayCardOut 스키마와 같다(더한 칸은 task_version_no 하나). 실제 응답 키도 같다."""
    assert _without_version_no(schemas.TodayCardOut.model_json_schema()) == _baseline()["TodayCardOut"]
    task, card = _sent_v2(client, employer_token, worker)
    props = set(_baseline()["TodayCardOut"]["properties"])
    assert set(card) == props | {"task_version_no"}
    step_props = set(_baseline()["TodayCardOut"]["$defs"]["StepOut"]["properties"])
    assert all(set(s) == step_props | {"safety_flag"} for s in card["steps"])
    assert all(s["picture_state"] == "confirmed" and s["needs_fallback"] is False for s in card["steps"])


def test_history_schema_snapshot(client, employer_token, worker):
    assert _without_version_no(schemas.HistoryCardOut.model_json_schema()) == _baseline()["HistoryCardOut"]
    task, card = _sent_v2(client, employer_token, worker)
    hist = client.get("/api/worker/me/history", headers=auth(worker["token"])).json()
    h = next(x for x in hist if x["assignment_id"] == card["assignment_id"])
    assert set(h) == set(_baseline()["HistoryCardOut"]["properties"]) | {"task_version_no"}
    step_props = set(_baseline()["HistoryCardOut"]["$defs"]["HistoryStepOut"]["properties"])
    assert all(set(s) == step_props | {"safety_flag"} for s in h["steps"])


# --- 버전 없는 옛 배정(대체 경로) ------------------------------------------------------------

def test_assignment_without_version_falls_back_to_steps(client, employer_token, worker, caplog):
    task = _task(client, employer_token)
    client.post(f"/api/tasks/{task['id']}/publish", headers=auth(employer_token))
    with SessionLocal() as db:
        a = Assignment(task_id=task["id"], worker_id=worker["id"], assigned_date=clock.utcnow(),
                       scheduled_day=clock.local_today())
        db.add(a)
        db.commit()
        aid = a.id
    with caplog.at_level("WARNING", logger="jobcard.versions"):
        card = _card(client, worker["token"], aid)
    assert [s["id"] for s in card["steps"]] == [s["id"] for s in task["steps"]]
    assert card["task_version_no"] is None
    assert any("버전 없는 배정" in r.getMessage() for r in caplog.records)
    # 대체 경로의 로그는 FK가 버전 단계를 가리켜도 SQLite는 강제하지 않는다 — 완료 판정은 지금 단계로 된다.
    r = _log(client, worker["token"], aid, task["steps"][0]["id"])
    assert r.status_code == 201

