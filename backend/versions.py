"""직무 버전 고정(2a-0, contract §1).

- steps는 사업주 편집 작업면이다. 보낼 때 snapshot()이 steps를 TaskVersion·TaskVersionStep으로 복사한다.
- 배정은 task_version_id로 버전에 묶인다. 근로자 화면·기록·완료 판정·도움·대시보드·내보내기는 그 버전 단계를 읽는다
  (assignment_steps). 그래서 하는 중에 사업주가 고쳐도 근로자 화면과 진행이 어긋나지 않는다(결정 5: 다음 배정부터).
- 같은 내용인지는 해시 없이 필드별로 바로 비교한다(same_content 하나).
- 근로자 응답은 version_step_to_out으로 만든다. 보낸 단계는 사업주가 확인한 것이라 picture_state='confirmed',
  needs_fallback=false로 고정한다.
"""
from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

import clock
import media
from models import Assignment, PerformanceLog, Step, Task, TaskVersion, TaskVersionStep
from schemas import StepOut, TaskVersionInfoOut

logger = logging.getLogger("jobcard.versions")


# --- 그림 상태·단계 응답 -----------------------------------------------------------------

def picture_state(s: Step) -> str:
    """단계 그림 4상태(스펙 5.5).

    none(그림 없음) → confirmed(사업주가 고름·올림·확인) → auto_high(자동 채택, 확인 전) → choose(그림은 있으나
    자동 채택 못 함, 사업주가 골라야 함) 순서로 판정한다. 사진 레코드가 지워졌으면(GC) 그림 없음이다.
    """
    has_picture = s.symbol_media is not None or bool((s.symbol_url or "").strip())
    if not has_picture:
        return "none"
    if s.picture_confirmed:
        return "confirmed"
    if not s.needs_fallback:
        return "auto_high"
    return "choose"


def _urls(s) -> tuple[str | None, str | None]:
    # 사진·음성 URL은 저장하지 않고 응답 때마다 서명해 만든다(media.py). 레코드가 지워졌으면 None.
    symbol_url = media.signed_url(s.symbol_media.id) if s.symbol_media is not None else s.symbol_url
    tts_url = media.signed_url(s.tts_media.id) if s.tts_media is not None else None
    return symbol_url, tts_url


def step_to_out(s: Step) -> StepOut:
    """편집 단계(steps) 응답."""
    symbol_url, tts_url = _urls(s)
    return StepOut(
        id=s.id, order=s.order_index, sentence=s.sentence,
        action_type=s.action_type, symbol_url=symbol_url,
        symbol_source=s.symbol_source, needs_fallback=s.needs_fallback,
        tts_audio_url=tts_url, picture_state=picture_state(s),
    )


def version_step_to_out(vs: TaskVersionStep) -> StepOut:
    """버전 단계 응답(근로자 화면). 모양은 StepOut 그대로다."""
    symbol_url, tts_url = _urls(vs)
    return StepOut(
        id=vs.id, order=vs.order_index, sentence=vs.sentence,
        action_type=vs.action_type, symbol_url=symbol_url,
        symbol_source=vs.symbol_source, needs_fallback=False,
        tts_audio_url=tts_url, picture_state="confirmed",
    )


def worker_step_out(s) -> StepOut:
    """배정 단계 응답. 버전 단계면 version_step_to_out, (버전 없는 옛 배정의 대체 경로) Step이면 step_to_out."""
    return version_step_to_out(s) if isinstance(s, TaskVersionStep) else step_to_out(s)


def step_key(s) -> str:
    """버전을 넘어 같은 단계로 묶는 키(contract §1.6). 버전 단계는 source_step_id, 없으면 자기 id."""
    return getattr(s, "source_step_id", None) or s.id


# --- 버전 찾기·비교·만들기 ----------------------------------------------------------------

def latest_version(db: Session, task: Task) -> TaskVersion | None:
    if task.current_version_id:
        v = db.get(TaskVersion, task.current_version_id)
        if v is not None:
            return v
    return db.scalar(select(TaskVersion).where(TaskVersion.task_id == task.id)
                     .order_by(TaskVersion.version_no.desc()).limit(1))


def _fields(s) -> tuple:
    # 2b-1부터 safety_flag·group_break를 더한다(contract §1.1).
    return (s.sentence or "", s.symbol_url or None, s.symbol_media_id or None, s.action_type or "")


def same_content(task: Task, version: TaskVersion | None) -> bool:
    """지금 steps와 버전 단계가 같은 내용인지(제목, 단계 수, 순서마다 문장·그림 URL·사진·동작 종류). 해시는 쓰지 않는다."""
    if version is None:
        return False
    if (task.title or "") != (version.title or ""):
        return False
    steps = sorted(task.steps, key=lambda s: s.order_index)
    vsteps = sorted(version.steps, key=lambda s: s.order_index)
    if len(steps) != len(vsteps):
        return False
    return all(_fields(a) == _fields(b) for a, b in zip(steps, vsteps))


def snapshot(db: Session, task: Task, created_by: str | None) -> TaskVersion:
    """지금 steps로 새 버전을 만든다(커밋은 부르는 쪽). 버전 단계 id는 새 uuid다.

    사진·음성은 같은 MediaFile 레코드를 가리킨다. media._unreferenced가 버전 단계 참조도 세므로, 편집기에서 사진이나
    문장(음성)을 바꿔 편집 단계가 레코드를 놓아도 버전이 쓰는 동안은 지워지지 않는다.
    """
    no = (db.scalar(select(func.max(TaskVersion.version_no)).where(TaskVersion.task_id == task.id)) or 0) + 1
    v = TaskVersion(task_id=task.id, version_no=no, title=task.title or "", created_by=created_by,
                    created_at=clock.utcnow())
    for i, s in enumerate(sorted(task.steps, key=lambda x: x.order_index), start=1):
        v.steps.append(TaskVersionStep(
            source_step_id=s.id, order_index=i, sentence=s.sentence, action_type=s.action_type,
            symbol_query=s.symbol_query or "", symbol_url=s.symbol_url, symbol_source=s.symbol_source,
            symbol_media_id=s.symbol_media_id, tts_media_id=s.tts_media_id,
        ))
    db.add(v)
    db.flush()
    task.current_version_id = v.id
    return v


def has_unsent_changes(db: Session, task: Task) -> bool:
    """보낸 뒤 고친 내용이 있는지. 보낸 적이 없으면 False."""
    v = latest_version(db, task)
    return v is not None and not same_content(task, v)


# --- 배정이 읽는 단계 -----------------------------------------------------------------------

def assignment_version(db: Session, a: Assignment) -> TaskVersion | None:
    return db.get(TaskVersion, a.task_version_id) if a.task_version_id else None


def assignment_steps(db: Session, a: Assignment, task: Task | None = None) -> list:
    """배정의 단계 목록(순서대로). 버전이 없는 옛 배정만 task.steps로 대신 읽는다(읽기 전용 대체 경로 하나)."""
    v = assignment_version(db, a)
    if v is not None:
        return list(v.steps)
    logger.warning("버전 없는 배정 %s — 직무의 지금 단계로 대신 읽는다", a.id)
    task = task or db.get(Task, a.task_id)
    return list(task.steps) if task is not None else []


def step_of_assignment(db: Session, a: Assignment, step_id: str):
    """step_id가 이 배정의 단계면 그 단계, 아니면 None. 소속 = vs.version_id == a.task_version_id."""
    if a.task_version_id:
        vs = db.get(TaskVersionStep, step_id)
        return vs if vs is not None and vs.version_id == a.task_version_id else None
    step = db.get(Step, step_id)
    return step if step is not None and step.task_id == a.task_id else None


def find_step(db: Session, step_id: str | None):
    """로그·도움이 가리키는 단계(버전 단계, 없으면 버전 없는 옛 배정의 Step)."""
    if not step_id:
        return None
    return db.get(TaskVersionStep, step_id) or db.get(Step, step_id)


def find_steps(db: Session, step_ids) -> dict:
    ids = {i for i in step_ids if i}
    if not ids:
        return {}
    out = {s.id: s for s in db.scalars(select(TaskVersionStep).where(TaskVersionStep.id.in_(ids))).all()}
    rest = ids - set(out)
    if rest:
        out.update({s.id: s for s in db.scalars(select(Step).where(Step.id.in_(rest))).all()})
    return out


def version_no_of(db: Session, a: Assignment) -> int | None:
    v = assignment_version(db, a)
    return v.version_no if v is not None else None


# --- TaskOut에 붙이는 정보(contract §1.4 GET /api/tasks/{id}) --------------------------------

def task_meta(db: Session, task: Task) -> dict:
    v = latest_version(db, task)
    today = clock.local_today()
    recipients = db.scalar(select(func.count(func.distinct(Assignment.worker_id)))
                           .where(Assignment.task_id == task.id)) or 0
    started = (select(PerformanceLog.id).where(PerformanceLog.assignment_id == Assignment.id,
                                               PerformanceLog.completed.is_(True)).exists())
    in_progress = db.scalar(select(func.count()).select_from(Assignment).where(
        Assignment.task_id == task.id, Assignment.scheduled_day == today,
        Assignment.status != "done", started)) or 0
    return {
        "version": TaskVersionInfoOut(current_no=v.version_no if v is not None else None,
                                      has_unsent_changes=v is not None and not same_content(task, v)),
        "in_progress_count": in_progress,
        "recipients_count": recipients,
        "updated_at": task.updated_at,
    }
