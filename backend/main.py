"""백엔드 API 서버 (FastAPI) — 오케스트레이션 허브.

프론트엔드는 이 API만 본다. 직무 생성 시 AI 하네스를 HTTP로 호출해 분해 + 상징
매핑을 받고, TTS는 Google Cloud Text-to-Speech로 mp3를 생성한다(실패 시 None →
프론트의 브라우저 음성합성 fallback).

평가 반영 변경점:
- on_event(deprecated) → lifespan
- 모든 자원 엔드포인트에 인증/인가 + 소유권 검사
- 단일 사용자 하드코딩(limit(1)) 제거 → 토큰의 sub 사용
- /api/worker/me/today: 소유자 + '오늘' 날짜 기준 필터
- /api/performance-logs: (assignment, step) 업서트 + 완료 집계
"""
from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import ai_client
from auth import (
    hash_password,
    make_token,
    require_employer,
    require_worker,
    verify_password,
)
from database import Base, engine, get_db
from models import Assignment, Employer, PerformanceLog, Step, Task, Worker
from schemas import (
    ArasaacMatch,
    ArasaacSearchRequest,
    ArasaacSearchResult,
    AssignmentOut,
    AssignRequest,
    CoachingOut,
    CoachingSuggestionOut,
    DashboardOut,
    EmployerLogin,
    PerformanceLogCreate,
    StepOut,
    StepStat,
    StepUpdate,
    TaskCreate,
    TaskOut,
    TaskSummaryOut,
    TodayCardOut,
    TokenOut,
    WorkerLogin,
)
from photos import MAX_PHOTO_BYTES, get_photo_dir, save_photo, sniff_image
from tts import get_tts_cache_dir, synthesize_tts_url


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    _ensure_seed()
    yield


app = FastAPI(title="JOB CARD - Backend", version="0.3.0", lifespan=lifespan)

# 서버 생성 TTS mp3 캐시 제공. URL 예: http://localhost:8000/api/tts/<hash>.mp3
app.mount("/api/tts", StaticFiles(directory=str(get_tts_cache_dir())), name="tts")

# 사업주가 올린 단계별 실제 사진 제공. URL 예: http://localhost:8000/api/photos/<uuid>.png
app.mount("/api/photos", StaticFiles(directory=str(get_photo_dir())), name="photos")


def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- 시드 ---
def _ensure_seed() -> None:
    """데모 사업주 1명 + 근로자 1명을 보장한다(없으면 생성).

    데모 자격증명은 환경변수로 덮어쓸 수 있다. 운영에서는 반드시 변경한다.
    """
    db = next(get_db())
    try:
        if db.scalar(select(Employer).limit(1)) is not None:
            return
        employer = Employer(
            id="emp-demo",
            name="데모 사업주",
            org_name="잇다 보호작업장",
            login_id=os.getenv("DEMO_EMPLOYER_LOGIN", "demo"),
            password_hash=hash_password(os.getenv("DEMO_EMPLOYER_PASSWORD", "demo1234")),
        )
        worker = Worker(
            id="wrk-demo",
            employer_id="emp-demo",
            display_name="김근로",
            access_code=os.getenv("DEMO_WORKER_CODE", "1234"),
        )
        db.add_all([employer, worker])
        db.commit()
    finally:
        db.close()


def _step_to_out(s: Step) -> StepOut:
    return StepOut(
        id=s.id, order=s.order_index, sentence=s.sentence,
        action_type=s.action_type, symbol_url=s.symbol_url,
        symbol_source=s.symbol_source, needs_fallback=s.needs_fallback,
        tts_audio_url=s.tts_audio_url,
    )


def _task_out(task: Task) -> TaskOut:
    return TaskOut(id=task.id, title=task.title, status=task.status,
                   steps=[_step_to_out(s) for s in task.steps])


def _owned_task(task_id: str, employer_id: str, db: Session) -> Task:
    task = db.get(Task, task_id)
    if task is None or task.employer_id != employer_id:
        # 존재 여부를 노출하지 않도록 소유자 불일치도 404로 통일한다.
        raise HTTPException(status_code=404, detail="직무를 찾을 수 없습니다.")
    return task


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


# --- 인증 ---
@app.post("/api/auth/login", response_model=TokenOut)
def employer_login(payload: EmployerLogin, db: Session = Depends(get_db)) -> TokenOut:
    employer = db.scalar(select(Employer).where(Employer.login_id == payload.login_id))
    if employer is None or not verify_password(payload.password, employer.password_hash):
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    return TokenOut(token=make_token(employer.id, "employer"), role="employer",
                    display_name=employer.org_name or employer.name)


@app.post("/api/auth/worker-login", response_model=TokenOut)
def worker_login(payload: WorkerLogin, db: Session = Depends(get_db)) -> TokenOut:
    worker = db.scalar(select(Worker).where(Worker.access_code == payload.access_code))
    if worker is None:
        raise HTTPException(status_code=401, detail="접속 코드가 올바르지 않습니다.")
    return TokenOut(token=make_token(worker.id, "worker"), role="worker",
                    display_name=worker.display_name)


# --- 사업주: 직무 생성(AI 분해 트리거) ---
@app.post("/api/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> TaskOut:
    context = {
        "business_type": payload.business_type or "",
        "work_environment": payload.work_environment or "",
        "worker_note": payload.worker_note or "",
    }
    try:
        decomposed = ai_client.decompose(payload.raw_input, context)
    except Exception as e:  # noqa: BLE001 - AI 하네스 장애는 502로 명확히 전달
        raise HTTPException(status_code=502, detail=f"AI 분해 서비스 오류: {e}")

    task = Task(employer_id=user["sub"], title=decomposed.get("task_title", "직무"),
                raw_input=payload.raw_input, status="draft")
    db.add(task)
    db.flush()

    for step in decomposed.get("steps", []):
        sentence = step["sentence"]
        # LLM이 제공한 구체 명사(symbol_query)를 우선 사용, 없으면 키워드로 폴백.
        symbol_terms = step.get("symbol_query") or [k["term"] for k in step.get("keywords", [])]
        symbol_terms = symbol_terms[:4] or [sentence[:12]]
        symbols = ai_client.map_symbols(symbol_terms).get("symbols", [])
        sym = next((s for s in symbols if not s.get("needs_fallback") and s.get("image_url")), None)
        if sym is None:
            sym = symbols[0] if symbols else {}
        db.add(Step(
            task_id=task.id, order_index=step["order"], sentence=sentence,
            action_type=step.get("action_type", "other"),
            symbol_url=sym.get("image_url"),
            symbol_source=sym.get("source", "fallback"),
            needs_fallback=sym.get("needs_fallback", True),
            tts_audio_url=synthesize_tts_url(sentence),
        ))

    db.commit()
    db.refresh(task)
    return _task_out(task)


@app.get("/api/tasks", response_model=list[TaskSummaryOut])
def list_tasks(db: Session = Depends(get_db),
               user: dict = Depends(require_employer)) -> list[TaskSummaryOut]:
    tasks = db.scalars(
        select(Task).where(Task.employer_id == user["sub"]).order_by(Task.created_at.desc())
    ).all()
    return [
        TaskSummaryOut(id=t.id, title=t.title, status=t.status, created_at=t.created_at)
        for t in tasks
    ]


@app.get("/api/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db),
             user: dict = Depends(require_employer)) -> TaskOut:
    return _task_out(_owned_task(task_id, user["sub"], db))


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> dict:
    """직무를 삭제한다. 단계는 cascade로 함께 지워지고, 배정/수행 로그는 명시적으로 정리한다."""
    task = _owned_task(task_id, user["sub"], db)
    assignment_ids = [a.id for a in db.scalars(
        select(Assignment).where(Assignment.task_id == task_id)
    ).all()]
    if assignment_ids:
        db.execute(delete(PerformanceLog).where(PerformanceLog.assignment_id.in_(assignment_ids)))
        db.execute(delete(Assignment).where(Assignment.task_id == task_id))
    db.delete(task)  # Step은 Task.steps의 cascade="all, delete-orphan"으로 함께 삭제됨
    db.commit()
    return {"ok": True}


@app.patch("/api/tasks/{task_id}/steps/{step_id}", response_model=StepOut)
def update_step(task_id: str, step_id: str, payload: StepUpdate,
                db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> StepOut:
    _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")
    if payload.sentence is not None:
        step.sentence = payload.sentence
        step.tts_audio_url = synthesize_tts_url(payload.sentence)
    if payload.symbol_url is not None:
        step.symbol_url = payload.symbol_url
        step.symbol_source = "fallback"
        step.needs_fallback = False
    db.commit()
    db.refresh(step)
    return _step_to_out(step)


@app.post("/api/tasks/{task_id}/publish", response_model=TaskOut)
def publish_task(task_id: str, db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> TaskOut:
    task = _owned_task(task_id, user["sub"], db)
    task.status = "published"
    db.commit()
    db.refresh(task)
    return _task_out(task)


@app.post("/api/arasaac/search", response_model=ArasaacSearchResult)
def search_arasaac(payload: ArasaacSearchRequest,
                   user: dict = Depends(require_employer)) -> ArasaacSearchResult:
    result = ai_client.search_arasaac(payload.term.strip(), langs=payload.langs or [],
                                      limit=payload.limit)
    return ArasaacSearchResult(
        term=result.get("term", payload.term.strip()),
        matches=[ArasaacMatch(**m) for m in result.get("matches", [])],
    )


# --- 사업주: 근로자에게 배정 ---
@app.post("/api/tasks/{task_id}/assignments", response_model=AssignmentOut)
def assign_task(task_id: str, payload: AssignRequest = AssignRequest(),
                db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> AssignmentOut:
    task = _owned_task(task_id, user["sub"], db)
    if task.status != "published":
        raise HTTPException(status_code=400, detail="게시된 직무만 배정할 수 있습니다.")

    if payload.worker_id:
        worker = db.get(Worker, payload.worker_id)
        if worker is None or worker.employer_id != user["sub"]:
            raise HTTPException(status_code=404, detail="해당 근로자를 찾을 수 없습니다.")
    else:
        workers = db.scalars(select(Worker).where(Worker.employer_id == user["sub"])).all()
        if len(workers) != 1:
            raise HTTPException(status_code=400, detail="배정할 근로자를 지정해 주세요.")
        worker = workers[0]

    a = Assignment(task_id=task_id, worker_id=worker.id, status="assigned")
    db.add(a)
    db.commit()
    db.refresh(a)
    return AssignmentOut(id=a.id, task_id=a.task_id, worker_id=a.worker_id, status=a.status)


# --- 근로자: 오늘의 카드 ---
@app.get("/api/worker/me/today", response_model=list[TodayCardOut])
def worker_today(db: Session = Depends(get_db),
                 user: dict = Depends(require_worker)) -> list[TodayCardOut]:
    start_of_day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assignments = db.scalars(
        select(Assignment).where(
            Assignment.worker_id == user["sub"],
            Assignment.status != "done",
            Assignment.assigned_date >= start_of_day,
        )
    ).all()
    out: list[TodayCardOut] = []
    for a in assignments:
        task = db.get(Task, a.task_id)
        if task is None:
            continue
        out.append(TodayCardOut(
            assignment_id=a.id, task_id=task.id, task_title=task.title,
            steps=[_step_to_out(s) for s in task.steps],
        ))
    return out


# --- 근로자: 단계 완료 로그(업서트) ---
@app.post("/api/performance-logs", status_code=201)
def create_log(payload: PerformanceLogCreate, db: Session = Depends(get_db),
               user: dict = Depends(require_worker)) -> dict:
    a = db.get(Assignment, payload.assignment_id)
    if a is None or a.worker_id != user["sub"]:
        raise HTTPException(status_code=404, detail="배정을 찾을 수 없습니다.")

    step = db.get(Step, payload.step_id)
    if step is None or step.task_id != a.task_id:
        raise HTTPException(status_code=400, detail="이 배정에 속하지 않는 단계입니다.")

    # (assignment, step) 업서트: 같은 단계를 다시 끝내면 마지막 기록으로 갱신한다.
    log = db.scalar(
        select(PerformanceLog).where(
            PerformanceLog.assignment_id == a.id,
            PerformanceLog.step_id == payload.step_id,
        )
    )
    if log is None:
        log = PerformanceLog(assignment_id=a.id, step_id=payload.step_id)
        db.add(log)
    log.duration_sec = payload.duration_sec
    log.replay_count = payload.replay_count
    log.stuck = payload.stuck

    task = db.get(Task, a.task_id)
    total = len(task.steps)
    logged_ids = set(db.scalars(
        select(PerformanceLog.step_id).where(PerformanceLog.assignment_id == a.id)
    ).all()) | {payload.step_id}
    if total and len(logged_ids) >= total:
        a.status = "done"

    db.commit()
    return {"ok": True, "assignment_status": a.status}


# --- 사업주: 대시보드 집계 ---
@app.get("/api/dashboard/tasks/{task_id}", response_model=DashboardOut)
def dashboard(task_id: str, db: Session = Depends(get_db),
              user: dict = Depends(require_employer)) -> DashboardOut:
    task = _owned_task(task_id, user["sub"], db)

    assignment_ids = [a.id for a in db.scalars(
        select(Assignment).where(Assignment.task_id == task_id)
    ).all()]

    logs = []
    if assignment_ids:
        logs = db.scalars(
            select(PerformanceLog).where(PerformanceLog.assignment_id.in_(assignment_ids))
        ).all()
    logs_by_step: dict[str, PerformanceLog] = {log.step_id: log for log in logs}

    step_stats: list[StepStat] = []
    stuck_steps: list[int] = []
    completed = 0
    for s in task.steps:
        log = logs_by_step.get(s.id)
        if log is not None:
            completed += 1
        if log and log.stuck:
            stuck_steps.append(s.order_index)
        step_stats.append(StepStat(
            order=s.order_index, sentence=s.sentence, completed=log is not None,
            duration_sec=log.duration_sec if log else 0.0,
            replay_count=log.replay_count if log else 0,
            stuck=log.stuck if log else False,
        ))

    total = len(task.steps)
    rate = round(completed / total * 100, 1) if total else 0.0
    return DashboardOut(
        task_id=task.id, task_title=task.title, total_steps=total,
        completed_steps=completed, completion_rate=rate,
        stuck_steps=stuck_steps, steps=step_stats,
    )


@app.get("/api/dashboard/tasks/{task_id}/coaching", response_model=CoachingOut)
def task_coaching(task_id: str, db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> CoachingOut:
    """근로자 수행 데이터를 바탕으로 사업주용 AI 개선 제안을 돌려준다(기능 2)."""
    task = _owned_task(task_id, user["sub"], db)

    assignment_ids = [a.id for a in db.scalars(
        select(Assignment).where(Assignment.task_id == task_id)
    ).all()]
    logs = []
    if assignment_ids:
        logs = db.scalars(
            select(PerformanceLog).where(PerformanceLog.assignment_id.in_(assignment_ids))
        ).all()
    logs_by_step: dict[str, PerformanceLog] = {log.step_id: log for log in logs}

    steps_payload = []
    for s in task.steps:
        log = logs_by_step.get(s.id)
        steps_payload.append({
            "order": s.order_index,
            "sentence": s.sentence,
            "completed": log is not None,
            "stuck": bool(log.stuck) if log else False,
            "replay_count": log.replay_count if log else 0,
            "duration_sec": log.duration_sec if log else 0.0,
        })

    raw = ai_client.coaching(task.title, steps_payload, {})
    suggestions = []
    for s in raw.get("suggestions", []):
        suggestions.append(CoachingSuggestionOut(
            order=int(s.get("order", 0)),
            issue=str(s.get("issue", "")),
            suggestion=str(s.get("suggestion", "")),
            action=str(s.get("action", "ok")),
        ))
    return CoachingOut(summary=str(raw.get("summary", "")), suggestions=suggestions)


def _photo_public_url(filename: str) -> str:
    base = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
    return f"{base}/api/photos/{filename}"


@app.post("/api/tasks/{task_id}/steps/{step_id}/photo", response_model=StepOut)
async def upload_step_photo(task_id: str, step_id: str,
                            file: UploadFile = File(...),
                            db: Session = Depends(get_db),
                            user: dict = Depends(require_employer)) -> StepOut:
    """단계에 실제 현장 사진을 올려 ARASAAC 자동 상징을 대체한다(기능 5)."""
    _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="사진은 5MB 이하만 업로드할 수 있습니다.")
    if sniff_image(data) is None:
        raise HTTPException(status_code=400, detail="이미지 파일(jpg/png/webp/gif)만 업로드할 수 있습니다.")

    filename = save_photo(data)
    step.symbol_url = _photo_public_url(filename)
    step.symbol_source = "photo"
    step.needs_fallback = False
    db.commit()
    db.refresh(step)
    return _step_to_out(step)


@app.delete("/api/tasks/{task_id}/steps/{step_id}/photo", response_model=StepOut)
def remove_step_photo(task_id: str, step_id: str,
                      db: Session = Depends(get_db),
                      user: dict = Depends(require_employer)) -> StepOut:
    """업로드한 사진을 제거하고 기본(자동 상징) 상태로 되돌린다."""
    _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")
    step.symbol_url = None
    step.symbol_source = "fallback"
    step.needs_fallback = True
    db.commit()
    db.refresh(step)
    return _step_to_out(step)
