"""사업주 직무 목록과 보관·복제·제목 바꾸기(2a-1, contract §2.1).

- GET /api/employer/tasks: 걸러보기는 서로 겹친다(탭 이름은 그대로, 뜻은 필터).
  draft = 보낸 버전 없음, published = 보낸 버전 있음, needs_check = 확인할 단계 1개 이상(초안·보냄 양쪽에 함께 셈),
  archived = archived_at 있음, all = 보관 아닌 전부. 보관한 직무는 archived에만 센다.
  counts는 검색어(q)와 상관없이 걸러보기별 전체 수다(탭 옆 숫자). 검색은 items에만 적용한다.
- 상태는 status 칸이 아니라 버전으로 정한다(2a-0 버전 고정): 보낸 적이 있으면(버전 있음) published.
  옛 publish만 하고 아무에게도 보내지 않은 직무는 버전이 없어 초안이다.
- 보관은 archived_at만 채운다(status는 그대로 둔다 — 꺼낼 때 잃는 것이 없다). 보관한 직무는 send·publish·옛 배정이
  409(send.ensure_sendable, main.assign_task), DELETE는 보관한 직무만 된다(main.delete_task).
- 받은 사람 아바타(이름 앞 글자)는 근로자 정보라, 화면에 실린 근로자마다 열람 기록(task.list)을 남긴다.
- 이 모듈은 main을 import하지 않는다(main이 이 라우터를 include한다).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

import clock
import media
import versions
from auth import require_employer
from database import get_db
from models import Assignment, MediaFile, Step, Task, TaskVersion, Worker
from privacy import record_access_for_workers
from schemas import (
    EmployerTaskListOut,
    EmployerTaskSummaryOut,
    TaskCountsOut,
    TaskFilter,
    TaskOut,
    TaskRecipientOut,
    TaskTitleUpdate,
)
from send import _is_archived, _owned_task
from text_clean import clean_one_line, has_visible

router = APIRouter()

TITLE_MAX = 40
COPY_SUFFIX = " (복사본)"
MAX_AVATARS = 3

MSG_TITLE = "제목을 1~40자로 적어 주세요."
AUDIT_ACTION = "task.list"


# --- 한 직무의 요약 ---------------------------------------------------------------------------

def needs_check_count(task: Task) -> int:
    """보내기 전에 봐야 할 단계 수: 그림 없음(none) + 확인 안 한 자동 그림(auto_high·choose).

    send.send_check가 막는 단계(no_picture·unconfirmed_auto·unreviewed_split의 step_ids)와 같은 집합이다. 나눈 문장
    확인(unreviewed_split)은 2b-1부터 늘 0이다(입력 화면이 끝냄) — 옛 데이터 방어로 같이 센다."""
    return sum(1 for s in task.steps if versions.picture_state(s) != "confirmed" or s.split_needs_review)


def _initials(name: str | None) -> str:
    name = (name or "").strip()
    return name[:1] if name else "?"


def _versions_of(db: Session, tasks: list[Task]) -> dict[str, TaskVersion]:
    """직무마다 마지막 버전(한 번에 읽는다). current_version_id가 비었으면 version_no가 가장 큰 것.

    지난 버전을 전부 읽지 않는다(보낸 횟수만큼 목록이 느려지지 않게): 먼저 current_version_id가 가리키는 버전만 읽고,
    그것이 없거나 다른 직무의 버전이면 (task_id, max(version_no))로 마지막 버전만 찾는다. 단계는 고른 버전 것만 읽는다."""
    if not tasks:
        return {}
    out: dict[str, TaskVersion] = {}
    cur_ids = [t.current_version_id for t in tasks if t.current_version_id]
    if cur_ids:
        rows = db.scalars(select(TaskVersion).where(TaskVersion.id.in_(cur_ids))
                          .options(selectinload(TaskVersion.steps))).all()
        by_id = {v.id: v for v in rows}
        for t in tasks:
            v = by_id.get(t.current_version_id) if t.current_version_id else None
            if v is not None and v.task_id == t.id:
                out[t.id] = v
    rest = [t.id for t in tasks if t.id not in out]
    if rest:
        last = (select(TaskVersion.task_id, func.max(TaskVersion.version_no).label("no"))
                .where(TaskVersion.task_id.in_(rest)).group_by(TaskVersion.task_id).subquery())
        rows = db.scalars(select(TaskVersion)
                          .join(last, (TaskVersion.task_id == last.c.task_id)
                                & (TaskVersion.version_no == last.c.no))
                          .options(selectinload(TaskVersion.steps))).all()
        for v in rows:
            out[v.task_id] = v
    return out


def _recipients_of(db: Session, tasks: list[Task]) -> dict[str, list[tuple[str, str]]]:
    """직무마다 받은 적 있는 근로자 [(worker_id, display_name)], 가장 최근에 보낸 사람부터."""
    ids = [t.id for t in tasks]
    if not ids:
        return {}
    last = func.max(Assignment.assigned_date).label("last")
    rows = db.execute(
        select(Assignment.task_id, Assignment.worker_id, Worker.display_name, last)
        .join(Worker, Worker.id == Assignment.worker_id)
        .where(Assignment.task_id.in_(ids))
        .group_by(Assignment.task_id, Assignment.worker_id, Worker.display_name)
        .order_by(last.desc(), Assignment.worker_id)
    ).all()
    out: dict[str, list[tuple[str, str]]] = {}
    for task_id, worker_id, name, _ in rows:
        out.setdefault(task_id, []).append((worker_id, name))
    return out


def _state(task: Task, version: TaskVersion | None) -> str:
    if _is_archived(task):
        return "archived"
    return "published" if version is not None else "draft"


def _cover_url(task: Task) -> str | None:
    steps = sorted(task.steps, key=lambda x: x.order_index)
    if not steps:
        return None
    url, _ = versions._urls(steps[0])
    return url or None


def summarize(db: Session, tasks: list[Task]) -> list[EmployerTaskSummaryOut]:
    vers = _versions_of(db, tasks)
    recips = _recipients_of(db, tasks)
    out = []
    for t in tasks:
        v = vers.get(t.id)
        people = recips.get(t.id, [])
        shown = people[:MAX_AVATARS]
        out.append(EmployerTaskSummaryOut(
            id=t.id, title=t.title or "", state=_state(t, v),
            needs_check_count=needs_check_count(t),
            has_unsent_changes=v is not None and not versions.same_content(t, v),
            step_count=len(t.steps), cover_url=_cover_url(t),
            recipients=[TaskRecipientOut(worker_id=w, initials=_initials(n)) for w, n in shown],
            recipients_more=max(len(people) - len(shown), 0),
            updated_at=t.updated_at or t.created_at,
            current_version_no=v.version_no if v is not None else None,
        ))
    return out


def _audit_shown(db: Session, request: Request, user: dict, items: list[EmployerTaskSummaryOut]) -> None:
    """화면에 실린 받은 사람(아바타)마다 열람 기록. 실린 근로자가 없으면 근로자 정보가 없으니 남기지 않는다."""
    seen = {r.worker_id for it in items for r in it.recipients}
    if seen:
        record_access_for_workers(db, request, user, AUDIT_ACTION, seen)


def _task_out(db: Session, task: Task) -> TaskOut:
    return TaskOut(id=task.id, title=task.title, status=task.status,
                   steps=[versions.step_to_out(s) for s in task.steps], **versions.task_meta(db, task))


# --- 라우트 ----------------------------------------------------------------------------------

@router.get("/api/employer/tasks", response_model=EmployerTaskListOut)
def list_employer_tasks(request: Request, filter: TaskFilter = "all", q: str = "",
                        db: Session = Depends(get_db),
                        user: dict = Depends(require_employer)) -> EmployerTaskListOut:
    tasks = list(db.scalars(select(Task).where(Task.employer_id == user["sub"])
                            .options(selectinload(Task.steps))
                            .order_by(Task.updated_at.desc(), Task.created_at.desc(), Task.id)).all())
    rows = summarize(db, tasks)
    live = [r for r in rows if r.state != "archived"]
    counts = TaskCountsOut(
        all=len(live),
        draft=sum(1 for r in live if r.state == "draft"),
        needs_check=sum(1 for r in live if r.needs_check_count > 0),
        published=sum(1 for r in live if r.state == "published"),
        archived=len(rows) - len(live),
    )
    if filter == "archived":
        items = [r for r in rows if r.state == "archived"]
    elif filter == "draft":
        items = [r for r in live if r.state == "draft"]
    elif filter == "published":
        items = [r for r in live if r.state == "published"]
    elif filter == "needs_check":
        items = [r for r in live if r.needs_check_count > 0]
    else:
        items = live
    query = q.strip().casefold()
    if query:
        items = [r for r in items if query in r.title.casefold()]
    _audit_shown(db, request, user, items)
    return EmployerTaskListOut(items=items, counts=counts)


@router.patch("/api/tasks/{task_id}", response_model=TaskOut)
def rename_task(task_id: str, payload: TaskTitleUpdate, db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> TaskOut:
    task = _owned_task(task_id, user["sub"], db)
    raw = payload.title
    if not isinstance(raw, str):
        raise HTTPException(status_code=422, detail=MSG_TITLE)
    # 제어 문자는 공백 하나로 바꾼다(목록·근로자 화면 제목은 한 줄이다).
    # 보이지 않는 글자는 지운다(보이지 않는 글자만 있으면 빈 제목이다).
    title = clean_one_line(raw)
    if not 1 <= len(title) <= TITLE_MAX or not has_visible(title):
        raise HTTPException(status_code=422, detail=MSG_TITLE)
    task.title = title  # updated_at은 models._touch_task_updated_at이 갱신한다
    db.commit()
    db.refresh(task)
    return _task_out(db, task)


def _one_summary(db: Session, request: Request, user: dict, task: Task) -> EmployerTaskSummaryOut:
    item = summarize(db, [task])[0]
    _audit_shown(db, request, user, [item])
    return item


@router.post("/api/tasks/{task_id}/archive", response_model=EmployerTaskSummaryOut)
def archive_task(task_id: str, request: Request, db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> EmployerTaskSummaryOut:
    """보관함으로 옮긴다. 이미 보관했으면 그대로(보관한 시각을 바꾸지 않는다). 이미 받은 배정은 건드리지 않는다."""
    task = _owned_task(task_id, user["sub"], db)
    if task.archived_at is None:
        task.archived_at = clock.utcnow()
        db.commit()
        db.refresh(task)
    return _one_summary(db, request, user, task)


@router.post("/api/tasks/{task_id}/unarchive", response_model=EmployerTaskSummaryOut)
def unarchive_task(task_id: str, request: Request, db: Session = Depends(get_db),
                   user: dict = Depends(require_employer)) -> EmployerTaskSummaryOut:
    task = _owned_task(task_id, user["sub"], db)
    changed = task.archived_at is not None
    task.archived_at = None
    if task.status == "archived":
        # 예전 방식(status='archived')으로 보관된 직무: 보낸 버전이 있으면 published, 없으면 draft로 되돌린다.
        task.status = "published" if versions.latest_version(db, task) is not None else "draft"
        changed = True
    if changed:
        db.commit()
        db.refresh(task)
    return _one_summary(db, request, user, task)


def _copy_media(db: Session, employer_id: str, media_id: str | None) -> str | None:
    """같은 파일을 가리키는 새 미디어 레코드(원본을 지워도 복사본의 사진·음성은 남는다).

    파일은 같은 키를 가리키는 레코드가 하나도 없을 때만 지워진다(media.release·gc). 원본 레코드가 이미 없으면 None."""
    if not media_id:
        return None
    rec = db.get(MediaFile, media_id)
    if rec is None or rec.employer_id != employer_id:
        return None
    if media.media_path(rec.kind, rec.storage_key) is None:
        return None
    new = MediaFile(employer_id=rec.employer_id, kind=rec.kind, storage_key=rec.storage_key,
                    sha256=rec.sha256, bytes=rec.bytes)
    db.add(new)
    db.flush()
    return new.id


def copy_title(title: str) -> str:
    """'… (복사본)'. 합쳐 40자를 넘으면 원래 제목을 줄인다."""
    base = (title or "").strip() or "직무"
    room = TITLE_MAX - len(COPY_SUFFIX)
    if len(base) > room:
        base = base[:room].rstrip()
    return base + COPY_SUFFIX


@router.post("/api/tasks/{task_id}/duplicate", response_model=TaskOut)
def duplicate_task(task_id: str, db: Session = Depends(get_db),
                   user: dict = Depends(require_employer)) -> TaskOut:
    """복제해서 고치기: 지금 편집 단계(steps)로 새 초안을 만든다. 버전·배정·기록은 복사하지 않는다(원래 직무에 남음).

    그림 확인(picture_confirmed)은 유지한다 — 사업주가 이미 본 그림이다. 보관한 직무도 복제할 수 있고, 복사본은
    보관하지 않은 초안이다."""
    src = _owned_task(task_id, user["sub"], db)
    copy = Task(employer_id=src.employer_id, title=copy_title(src.title), raw_input=src.raw_input,
                business_type=src.business_type, work_environment=src.work_environment, job=src.job,
                status="draft")
    db.add(copy)
    db.flush()
    for s in sorted(src.steps, key=lambda x: x.order_index):
        db.add(Step(
            task_id=copy.id, order_index=s.order_index, sentence=s.sentence, action_type=s.action_type,
            symbol_query=s.symbol_query, symbol_candidates=s.symbol_candidates,
            symbol_url=s.symbol_url, symbol_source=s.symbol_source,
            needs_fallback=s.needs_fallback, picture_confirmed=s.picture_confirmed,
            symbol_media_id=_copy_media(db, src.employer_id, s.symbol_media_id),
            tts_media_id=_copy_media(db, src.employer_id, s.tts_media_id),
            # (2b-1) 조심 표시·나누기 정보·묶음 경계도 그대로 옮긴다(음성이 옛 문장이면 그 표시도).
            safety_flag=s.safety_flag, safety_source=s.safety_source, safety_note=s.safety_note,
            split_source=s.split_source, split_needs_review=s.split_needs_review, original_span=s.original_span,
            tts_stale=s.tts_stale, group_break=s.group_break,
        ))
    db.commit()
    db.refresh(copy)
    return _task_out(db, copy)
