"""2a-1 직무 목록·보관·복제·제목 시험 (scratchpad/p2/contract.md §2.1, tasks.md §3.1).

지키는 것:
- 걸러보기는 겹친다: 확인할 것이 있는 초안은 초안·확인 필요 양쪽에, 보낸 뒤 고쳐 확인할 것이 생긴 직무는 보냄에 남는다.
  보관한 직무는 보관에만 센다. counts는 검색어와 상관없다.
- 보관한 직무는 send·publish·옛 배정이 409(code archived). 꺼내면 다시 보낼 수 있다.
- DELETE는 보관한 직무만(409 문구 고정). 응답 모양 {ok: true} 그대로.
- 복제는 새 초안('… (복사본)'), 그림 확인 유지, 같은 파일의 새 미디어 레코드. 원래 직무의 배정·기록은 그대로.
- 받은 사람 아바타는 근로자 정보라 열람 기록(task.list)을 남긴다.
"""
import os
import sys
import uuid
from io import BytesIO

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

import manage  # noqa: E402
import photos  # noqa: E402
import task_list  # noqa: E402
from conftest import auth, delete_task, give_pictures  # noqa: E402
from database import SessionLocal  # noqa: E402
from models import AccessAuditLog, Assignment, MediaFile, PerformanceLog, Step, Task, TaskVersion  # noqa: E402


# --- 도우미 ------------------------------------------------------------------

def _employer(client) -> dict:
    """시험마다 따로 쓰는 사업장(개수가 다른 시험의 직무에 흔들리지 않게)."""
    login = f"list-{uuid.uuid4().hex[:8]}"
    manage.create_employer(login, "", "목록 시험", "correct-horse-1")
    r = client.post("/api/auth/login", json={"login_id": login, "password": "correct-horse-1"})
    assert r.status_code == 200, r.text
    return auth(r.json()["token"])


def _worker(client, emp, name="김민지") -> dict:
    r = client.post("/api/workers", json={"display_name": name}, headers=emp)
    assert r.status_code == 201, r.text
    w = r.json()
    code = client.get("/api/workplace", headers=emp).json()["workplace_code"]
    login = client.post("/api/auth/worker-login", json={"workplace_code": code, "access_code": w["access_code"]})
    assert login.status_code == 200, login.text
    w["headers"] = auth(login.json()["token"])
    return w


def _task(client, emp, title=None, pictures=True) -> str:
    r = client.post("/api/tasks", json={"raw_input": "상자를 옮기고 수량을 확인하세요"}, headers=emp)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    if pictures:
        give_pictures(client, emp["Authorization"].split()[1], tid)
    if title:
        assert client.patch(f"/api/tasks/{tid}", json={"title": title}, headers=emp).status_code == 200
    return tid


def _send(client, emp, tid, worker_ids):
    return client.post(f"/api/tasks/{tid}/send", headers=emp, json={"worker_ids": worker_ids, "day": "today"})


def _list(client, emp, filter="all", q=""):
    r = client.get("/api/employer/tasks", params={"filter": filter, "q": q}, headers=emp)
    assert r.status_code == 200, r.text
    return r.json()


def _ids(body) -> set:
    return {it["id"] for it in body["items"]}


def _row(client, emp, tid) -> dict:
    for f in ("all", "archived"):
        for it in _list(client, emp, f)["items"]:
            if it["id"] == tid:
                return it
    raise AssertionError(f"목록에 {tid}가 없다")


def _set_step(step_id, **values):
    with SessionLocal() as db:
        step = db.get(Step, step_id)
        for k, v in values.items():
            setattr(step, k, v)
        db.commit()


def _steps(client, emp, tid) -> list:
    return client.get(f"/api/tasks/{tid}", headers=emp).json()["steps"]


def _png() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (32, 32), (0, 128, 0)).save(buf, "PNG")
    return buf.getvalue()


# --- 걸러보기 -------------------------------------------------------------------

def test_filters_overlap(client):
    emp = _employer(client)
    w = _worker(client, emp)
    unchecked = _task(client, emp, "확인 대기 초안", pictures=False)   # 그림 없는 단계 2개
    ready = _task(client, emp, "준비된 초안")
    sent = _task(client, emp, "보낸 직무")
    gone = _task(client, emp, "보관한 직무")
    assert _send(client, emp, sent, [w["id"]]).status_code == 200
    assert _send(client, emp, gone, [w["id"]]).status_code == 200
    assert client.post(f"/api/tasks/{gone}/archive", headers=emp).status_code == 200

    body = _list(client, emp)
    assert body["counts"] == {"all": 3, "draft": 2, "needs_check": 1, "published": 1, "archived": 1}
    assert _ids(body) == {unchecked, ready, sent}
    # 확인 대기 초안은 초안·확인 필요 양쪽에 센다.
    assert _ids(_list(client, emp, "draft")) == {unchecked, ready}
    assert _ids(_list(client, emp, "needs_check")) == {unchecked}
    assert _ids(_list(client, emp, "published")) == {sent}
    assert _ids(_list(client, emp, "archived")) == {gone}

    row = _row(client, emp, unchecked)
    assert row["state"] == "draft" and row["needs_check_count"] == 2 and row["step_count"] == 2
    assert row["current_version_no"] is None and row["recipients"] == [] and row["has_unsent_changes"] is False
    sent_row = _row(client, emp, sent)
    assert sent_row["state"] == "published" and sent_row["current_version_no"] == 1
    assert sent_row["recipients"] == [{"worker_id": w["id"], "initials": "김"}] and sent_row["recipients_more"] == 0
    assert sent_row["cover_url"]
    assert _row(client, emp, gone)["state"] == "archived"

    # 검색은 items에만, counts는 그대로. 대소문자·앞뒤 빈칸은 따지지 않는다.
    found = _list(client, emp, "all", "  보낸 ")
    assert _ids(found) == {sent} and found["counts"] == body["counts"]
    assert _ids(_list(client, emp, "draft", "보낸")) == set()


def test_sent_then_edited_stays_in_published(client):
    emp = _employer(client)
    w = _worker(client, emp)
    tid = _task(client, emp, "보낸 뒤 고침")
    assert _send(client, emp, tid, [w["id"]]).status_code == 200
    row = _row(client, emp, tid)
    assert row["state"] == "published" and row["needs_check_count"] == 0 and row["has_unsent_changes"] is False

    # 보낸 뒤 첫 단계 그림을 자동 그림(확인 전)으로 바꾸고 문장도 고친다.
    first = _steps(client, emp, tid)[0]["id"]
    r = client.patch(f"/api/tasks/{tid}/steps/{first}", headers=emp, json={"sentence": "상자를 두 손으로 옮겨요."})
    assert r.status_code == 200, r.text
    _set_step(first, picture_confirmed=False, needs_fallback=False)

    row = _row(client, emp, tid)
    assert row["state"] == "published" and row["current_version_no"] == 1
    assert row["needs_check_count"] == 1 and row["has_unsent_changes"] is True
    assert tid in _ids(_list(client, emp, "published"))
    assert tid in _ids(_list(client, emp, "needs_check"))
    assert tid not in _ids(_list(client, emp, "draft"))


def test_unsent_title_change_and_updated_at(client):
    emp = _employer(client)
    w = _worker(client, emp)
    tid = _task(client, emp, "제목 고침")
    assert _send(client, emp, tid, [w["id"]]).status_code == 200
    before = _row(client, emp, tid)["updated_at"]
    r = client.patch(f"/api/tasks/{tid}", json={"title": "  새 제목  "}, headers=emp)
    assert r.status_code == 200 and r.json()["title"] == "새 제목"
    assert r.json()["version"] == {"current_no": 1, "has_unsent_changes": True}
    row = _row(client, emp, tid)
    assert row["has_unsent_changes"] is True and row["updated_at"] >= before
    # 보관은 '고친 것'이 아니다(고친 날이 바뀌지 않는다).
    after_title = row["updated_at"]
    assert client.post(f"/api/tasks/{tid}/archive", headers=emp).json()["updated_at"] == after_title


def test_rename_title_rules(client):
    emp = _employer(client)
    tid = _task(client, emp)
    msg = {"detail": "제목을 1~40자로 적어 주세요."}
    for bad in ("", "   ", "가" * 41):
        r = client.patch(f"/api/tasks/{tid}", json={"title": bad}, headers=emp)
        assert r.status_code == 422 and r.json() == msg
    r = client.patch(f"/api/tasks/{tid}", json={}, headers=emp)
    assert r.status_code == 422 and r.json() == msg
    r = client.patch(f"/api/tasks/{tid}", json={"title": "가" * 40}, headers=emp)
    assert r.status_code == 200 and r.json()["title"] == "가" * 40
    assert set(r.json()) >= {"id", "title", "status", "steps", "version", "updated_at"}


def test_rename_title_control_chars_and_non_text(client):
    emp = _employer(client)
    tid = _task(client, emp)
    msg = {"detail": "제목을 1~40자로 적어 주세요."}
    # 글자가 아닌 값도 공용 문구가 아니라 제목 문구로 막는다.
    for bad in (123, True, ["가"], {"a": 1}):
        r = client.patch(f"/api/tasks/{tid}", json={"title": bad}, headers=emp)
        assert r.status_code == 422 and r.json() == msg, bad
    # 줄바꿈·탭 같은 제어 문자는 공백 하나로 바뀐다(목록·근로자 화면 제목은 한 줄).
    r = client.patch(f"/api/tasks/{tid}", json={"title": " a\r\n\n b\tc\u2028d "}, headers=emp)
    assert r.status_code == 200 and r.json()["title"] == "a  b c d"
    # 제어 문자만 있으면 빈 제목이다.
    r = client.patch(f"/api/tasks/{tid}", json={"title": "\n\t\r"}, headers=emp)
    assert r.status_code == 422 and r.json() == msg
    assert _row(client, emp, tid)["title"] == "a  b c d"


# --- 보관 ----------------------------------------------------------------------

def test_archive_blocks_send(client):
    emp = _employer(client)
    w = _worker(client, emp)
    tid = _task(client, emp, "보관 시험")
    assert _send(client, emp, tid, [w["id"]]).status_code == 200
    r = client.post(f"/api/tasks/{tid}/archive", headers=emp)
    assert r.status_code == 200 and r.json()["state"] == "archived" and r.json()["id"] == tid
    # 두 번 보관해도 그대로(보관 시각을 바꾸지 않는다).
    with SessionLocal() as db:
        at = db.get(Task, tid).archived_at
    assert client.post(f"/api/tasks/{tid}/archive", headers=emp).status_code == 200
    with SessionLocal() as db:
        assert db.get(Task, tid).archived_at == at
    # 옛 대시보드가 쓰는 근로자별 직무와 옛 목록에도 보관 여부가 실린다(보관한 직무에 [보관하기]를 다시 띄우지 않게).
    rows = client.get(f"/api/workers/{w['id']}/tasks", headers=emp).json()
    assert [(r["id"], r["archived"]) for r in rows] == [(tid, True)]
    assert {r["id"]: r["archived"] for r in client.get("/api/tasks", headers=emp).json()}[tid] is True

    blocked = {"detail": "보관한 직무는 보낼 수 없어요. 보관함에서 꺼낸 뒤 보내 주세요.",
               "code": "archived", "step_ids": []}
    r = _send(client, emp, tid, [w["id"]])
    assert r.status_code == 409 and r.json() == blocked
    r = client.post(f"/api/tasks/{tid}/publish", headers=emp)
    assert r.status_code == 409 and r.json() == blocked
    r = client.post(f"/api/tasks/{tid}/assignments", headers=emp, json={"worker_ids": [w["id"]]})
    assert r.status_code == 409 and r.json() == blocked
    # 받는 사람·날짜가 잘못돼도 보관 409가 먼저다(옛 배정 경로와 같은 답).
    for body in ({"worker_ids": []}, {"worker_ids": [str(uuid.uuid4())]},
                 {"worker_ids": [w["id"]], "day": "2000-01-01"}):
        r = client.post(f"/api/tasks/{tid}/send", headers=emp, json=body)
        assert r.status_code == 409 and r.json() == blocked, body
    check = client.get(f"/api/tasks/{tid}/send-check", headers=emp).json()
    assert check["ok"] is False and any(b["code"] == "archived" for b in check["blocking"])
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(Assignment).where(Assignment.task_id == tid)) == 1

    r = client.post(f"/api/tasks/{tid}/unarchive", headers=emp)
    assert r.status_code == 200 and r.json()["state"] == "published"
    assert client.get(f"/api/workers/{w['id']}/tasks", headers=emp).json()[0]["archived"] is False
    assert _send(client, emp, tid, [w["id"]]).status_code == 200


def test_unarchive_draft_goes_back_to_draft(client):
    emp = _employer(client)
    tid = _task(client, emp, pictures=False)
    assert client.post(f"/api/tasks/{tid}/archive", headers=emp).json()["state"] == "archived"
    # 보관한 직무는 확인할 것이 있어도 '확인 필요'에 세지 않는다.
    assert _list(client, emp)["counts"] == {"all": 0, "draft": 0, "needs_check": 0, "published": 0, "archived": 1}
    r = client.post(f"/api/tasks/{tid}/unarchive", headers=emp)
    assert r.status_code == 200 and r.json()["state"] == "draft" and r.json()["needs_check_count"] == 2


def test_delete_requires_archive(client):
    emp = _employer(client)
    tid = _task(client, emp)
    r = client.delete(f"/api/tasks/{tid}", headers=emp)
    assert r.status_code == 409 and r.json() == {"detail": "보관함으로 옮긴 직무만 완전히 지울 수 있어요."}
    assert client.get(f"/api/tasks/{tid}", headers=emp).status_code == 200
    assert client.post(f"/api/tasks/{tid}/archive", headers=emp).status_code == 200
    r = client.delete(f"/api/tasks/{tid}", headers=emp)
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get(f"/api/tasks/{tid}", headers=emp).status_code == 404
    assert _list(client, emp)["counts"]["archived"] == 0


def test_other_employer_gets_404(client):
    emp = _employer(client)
    other = _employer(client)
    tid = _task(client, emp)
    for method, path, body in (("post", "archive", None), ("post", "unarchive", None), ("post", "duplicate", None)):
        assert getattr(client, method)(f"/api/tasks/{tid}/{path}", headers=other).status_code == 404
    assert client.patch(f"/api/tasks/{tid}", json={"title": "남의 것"}, headers=other).status_code == 404
    assert client.delete(f"/api/tasks/{tid}", headers=other).status_code == 404
    assert _list(client, other)["counts"]["all"] == 0


def test_list_requires_employer_and_valid_filter(client, worker_token):
    assert client.get("/api/employer/tasks", headers=auth(worker_token)).status_code == 403
    emp = _employer(client)
    r = client.get("/api/employer/tasks", params={"filter": "sent"}, headers=emp)
    assert r.status_code == 422 and "detail" in r.json()


# --- 복제 ----------------------------------------------------------------------

def test_duplicate_keeps_original_logs(client):
    emp = _employer(client)
    w = _worker(client, emp)
    tid = _task(client, emp, "원래 직무")
    first = _steps(client, emp, tid)[0]["id"]
    r = client.post(f"/api/tasks/{tid}/steps/{first}/photo", headers=emp,
                    files={"file": ("p.png", _png(), "image/png")})
    assert r.status_code == 200, r.text
    assert _send(client, emp, tid, [w["id"]]).status_code == 200
    card = [c for c in client.get("/api/worker/me/today", headers=w["headers"]).json() if c["task_id"] == tid][0]
    r = client.post("/api/performance-logs", headers=w["headers"], json={
        "assignment_id": card["assignment_id"], "step_id": card["steps"][0]["id"],
        "duration_sec": 3.0, "replay_count": 0, "stuck": False})
    assert r.status_code in (200, 201), r.text

    def counts():
        with SessionLocal() as db:
            aids = select(Assignment.id).where(Assignment.task_id == tid)
            return (db.scalar(select(func.count()).select_from(PerformanceLog)
                              .where(PerformanceLog.assignment_id.in_(aids))),
                    db.scalar(select(func.count()).select_from(Assignment).where(Assignment.task_id == tid)),
                    db.scalar(select(func.count()).select_from(TaskVersion).where(TaskVersion.task_id == tid)))

    before = counts()
    assert before == (1, 1, 1)
    r = client.post(f"/api/tasks/{tid}/duplicate", headers=emp)
    assert r.status_code == 200, r.text
    copy = r.json()
    assert copy["id"] != tid and copy["title"] == "원래 직무 (복사본)" and copy["status"] == "draft"
    assert copy["version"] == {"current_no": None, "has_unsent_changes": False}
    assert copy["recipients_count"] == 0
    orig_steps = _steps(client, emp, tid)
    assert [s["sentence"] for s in copy["steps"]] == [s["sentence"] for s in orig_steps]
    assert all(s["picture_state"] == "confirmed" for s in copy["steps"])  # 그림 확인 유지
    assert {s["id"] for s in copy["steps"]}.isdisjoint({s["id"] for s in orig_steps})
    row = _row(client, emp, copy["id"])
    assert row["state"] == "draft" and row["needs_check_count"] == 0 and row["recipients"] == []
    assert counts() == before

    # 같은 파일의 새 미디어 레코드: 원래 직무를 지워도 복사본 사진은 남는다.
    with SessionLocal() as db:
        src_step = db.get(Step, orig_steps[0]["id"])
        copy_step = db.get(Step, copy["steps"][0]["id"])
        assert copy_step.symbol_media_id and copy_step.symbol_media_id != src_step.symbol_media_id
        src_rec = db.get(MediaFile, src_step.symbol_media_id)
        copy_rec = db.get(MediaFile, copy_step.symbol_media_id)
        assert copy_rec.storage_key == src_rec.storage_key and copy_rec.kind == "photo"
        if src_step.tts_media_id:
            assert copy_step.tts_media_id and copy_step.tts_media_id != src_step.tts_media_id
        path = photos.get_photo_dir() / copy_rec.storage_key
        copy_media_id = copy_rec.id
    assert path.exists()

    # 복사본을 지워도 원래 직무의 배정·기록·버전은 그대로.
    assert delete_task(client, copy["id"], emp).status_code == 200
    assert counts() == before
    assert path.exists()

    # 다시 복제한 뒤 원래 직무를 지우면, 복사본 사진 파일은 남는다(다른 레코드가 같은 키를 씀).
    copy2 = client.post(f"/api/tasks/{tid}/duplicate", headers=emp).json()
    assert delete_task(client, tid, emp).status_code == 200
    assert path.exists()
    with SessionLocal() as db:
        assert db.get(MediaFile, copy_media_id) is None  # 지운 복사본의 레코드는 정리됨
        step2 = db.get(Step, copy2["steps"][0]["id"])
        assert db.get(MediaFile, step2.symbol_media_id) is not None
    got = client.get(f"/api/tasks/{copy2['id']}", headers=emp).json()
    assert got["steps"][0]["symbol_url"]
    delete_task(client, copy2["id"], emp)


def test_copy_title_fits_40():
    assert task_list.copy_title("컵 씻기") == "컵 씻기 (복사본)"
    long = "가" * 40
    out = task_list.copy_title(long)
    assert len(out) == 40 and out.endswith(" (복사본)")
    assert task_list.copy_title("") == "직무 (복사본)"


# --- 받은 사람·감사 ------------------------------------------------------------

def test_recipients_avatars_and_audit(client):
    emp = _employer(client)
    people = [_worker(client, emp, n) for n in ("김가", "이나", "박다", "최라", "정마")]
    tid = _task(client, emp, "여럿에게")
    assert _send(client, emp, tid, [p["id"] for p in people[:2]]).status_code == 200
    assert _send(client, emp, tid, [p["id"] for p in people[2:]]).status_code == 200
    with SessionLocal() as db:
        before = db.scalar(select(func.max(AccessAuditLog.at))) or None
    row = _row(client, emp, tid)
    assert len(row["recipients"]) == 3 and row["recipients_more"] == 2
    shown = {r["worker_id"] for r in row["recipients"]}
    # 가장 최근에 보낸 사람부터(두 번째 보내기의 셋).
    assert shown == {p["id"] for p in people[2:]}
    assert {r["initials"] for r in row["recipients"]} == {"박", "최", "정"}
    with SessionLocal() as db:
        q = select(AccessAuditLog.worker_id).where(AccessAuditLog.action == "task.list")
        if before is not None:
            q = q.where(AccessAuditLog.at >= before)
        logged = set(db.scalars(q).all())
    assert shown <= logged
    assert not ({p["id"] for p in people[:2]} & logged)  # 화면에 실리지 않은 사람은 남기지 않는다
    assert "task.list" in __import__("privacy").DEDUPED_ACTIONS


def test_list_without_recipients_writes_no_audit(client):
    emp = _employer(client)
    _task(client, emp)
    with SessionLocal() as db:
        n = db.scalar(select(func.count()).select_from(AccessAuditLog).where(AccessAuditLog.action == "task.list"))
    _list(client, emp)
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(AccessAuditLog)
                         .where(AccessAuditLog.action == "task.list")) == n
