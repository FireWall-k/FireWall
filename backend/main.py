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
- (Phase 0.2) AI 하네스로 보내는 요청의 근로자 실명은 별칭으로 바꾸고(privacy.Pseudonymizer), 메모는 허용·동의가
  있을 때만 보낸다. 근로자 개인 데이터 열람은 접근 감사 로그에 남긴다. 동의 기록·내보내기·삭제 API.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import posixpath
import re
import secrets
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote

from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from aac_assets import get_aac_image_dir, public_aac_url

import ai_client
from auth import (
    check_production_config,
    code_fingerprint,
    hash_access_code,
    hash_password,
    is_production,
    make_token,
    require_employer,
    require_worker,
    verify_password,
)
import db_migrate
from codes import normalize_workplace_code
from database import checkpoint_wal, get_db
from models import Assignment, Employer, MediaFile, PerformanceLog, Step, Task, Worker, WorkerConsent
from privacy import (
    employer_pseudonymizer,
    has_active_consent,
    is_ambiguous_name,
    policy_version,
    CONSENT_PERSONAL_INFO,
    record_access,
    record_access_for_workers,
    workers_with_active_consent,
)
from schemas import (
    AacMatch,
    AacSearchRequest,
    AacSearchResult,
    AssignmentOut,
    AssignRequest,
    CoachingOut,
    CoachingSuggestionOut,
    ConsentCreate,
    ConsentOut,
    DashboardOut,
    DashboardWorkerOut,
    EmployerLogin,
    HistoryCardOut,
    HistoryStepOut,
    PerformanceLogCreate,
    StepCreate,
    StepOut,
    StepReorder,
    StepStat,
    StepSymbolCandidates,
    StepUpdate,
    TaskCreate,
    TaskOut,
    TaskSummaryOut,
    TodayCardOut,
    TokenOut,
    WorkerCreate,
    WorkerLogin,
    WorkerOut,
    WorkerUpdate,
    WorkerWithCodeOut,
    WorkplaceOut,
)
from ratelimit import client_ip, employer_throttle, ensure_not_blocked, worker_throttle
import maintenance
import media
from photos import MAX_PHOTO_BYTES, ImageRejected, sanitize_image, save_photo, sniff_image
from tts import synthesize_tts


logger = logging.getLogger("jobcard.backend")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 운영 설정이 잘못됐으면(약한 시크릿 등) 첫 로그인 때가 아니라 지금 멈춘다.
    check_production_config()
    # 스키마 변경은 요청 프로세스가 아니라 migrate 서비스(`python manage.py migrate`)가 한다.
    # 여기서는 DB가 head인지 확인만 한다 — 운영은 아니면 기동 거부, 개발은 자동 upgrade(db_migrate 참고).
    db_migrate.ensure_schema_ready()
    # 시드는 스키마가 준비된 뒤에 돌아야 한다(빈 DB에서 테이블이 없으면 조회부터 깨진다).
    _ensure_seed()
    yield


app = FastAPI(title="JOB CARD - Backend", version="0.3.0", lifespan=lifespan)

# 정적 파일의 Content-Type은 운영체제 MIME 표를 따른다. python:3.12-slim 이미지에는 .webp가 없어
# AAC 그림이 text/plain으로 나갔다(Windows 개발 환경에서는 레지스트리 덕에 정상이라 몰랐다).
mimetypes.add_type("image/webp", ".webp")
mimetypes.add_type("audio/mpeg", ".mp3")

# (Phase 0.3) 서버 생성 TTS mp3(/api/tts)와 사업주가 올린 사진(/api/photos)은 더 이상 정적 경로로 열지 않는다.
# 무인증 StaticFiles라 파일명만 알면 누구나 받을 수 있었다(사진에는 사람이, 음성 문장에는 이름이 담길 수 있다).
# 이제 응답에 실린 단기 서명 URL(GET /api/media/{id}?exp=&sig=, media.py)로만 나간다.

# 프로젝트 자체 제작 AAC 이미지 제공(공개 자산이라 서명 없이 그대로 연다)
app.mount(
    "/api/aac/images",
    StaticFiles(
        directory=str(get_aac_image_dir()),
        check_dir=False,
    ),
    name="aac-images",
)

# 날짜 경계의 기준 시간대. 배정 시각은 UTC로 저장하지만 "오늘"은 사용자가 사는 곳의 날짜여야 한다.
# 서버(UTC)와 브라우저(KST)가 서로 다른 날짜를 오늘이라 부르면, 한국 시간 0~9시에 배정한
# 직무가 대시보드의 "오늘"에 안 보였다. 한국은 서머타임이 없어 고정 오프셋으로 충분하다.
APP_UTC_OFFSET_HOURS = int(os.getenv("APP_UTC_OFFSET_HOURS", "9"))
_SQL_LOCAL_DATE_MODIFIER = f"{APP_UTC_OFFSET_HOURS:+d} hours"


def local_day_start_utc(now: datetime | None = None) -> datetime:
    """현지 기준 오늘 0시를 UTC 시각으로 돌려준다(저장된 UTC 시각과 바로 비교할 수 있다)."""
    now = now or datetime.now(timezone.utc)
    offset = timedelta(hours=APP_UTC_OFFSET_HOURS)
    local_midnight = (now + offset).replace(hour=0, minute=0, second=0, microsecond=0)
    return local_midnight - offset


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
def _demo_seed_enabled() -> bool:
    """운영(JOBCARD_ENV=prod)에서는 기본으로 끈다. 공개 저장소에 적힌 demo/demo1234 계정이
    운영 서버에 생기면 그대로 로그인된다. 운영 사업주 계정은 manage.py로 만든다."""
    default = "0" if is_production() else "1"
    return os.getenv("DEMO_SEED", default).strip() == "1"


def _ensure_seed() -> None:
    """데모 사업주 1명 + 근로자 1명을 보장한다(없으면 생성).

    데모 자격증명은 환경변수로 덮어쓸 수 있다. 운영에서는 만들지 않는다(_demo_seed_enabled).
    """
    if not _demo_seed_enabled():
        return
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
            # 실제 사업장 코드는 서버가 무작위로 만들지만, 데모는 안내문(README)에 적을 수 있게 고정한다.
            workplace_code=normalize_workplace_code(os.getenv("DEMO_WORKPLACE_CODE", "DEMO01")),
        )
        worker = Worker(
            id="wrk-demo",
            employer_id="emp-demo",
            display_name="김근로",
        )
        worker.set_access_code(os.getenv("DEMO_WORKER_CODE", "1234"))
        db.add_all([employer, worker])
        db.commit()
    finally:
        db.close()


def _step_to_out(s: Step) -> StepOut:
    # 사진·음성 URL은 저장하지 않고 응답 때마다 서명해 만든다(media.py). 만료되면 화면이 다시 조회해 새 URL을 받는다.
    # 레코드가 지워졌으면(GC) None — 그림 없음 / 브라우저 음성합성으로 대신한다.
    symbol_url = media.signed_url(s.symbol_media.id) if s.symbol_media is not None else s.symbol_url
    tts_url = media.signed_url(s.tts_media.id) if s.tts_media is not None else None
    return StepOut(
        id=s.id, order=s.order_index, sentence=s.sentence,
        action_type=s.action_type, symbol_url=symbol_url,
        symbol_source=s.symbol_source, needs_fallback=s.needs_fallback,
        tts_audio_url=tts_url,
    )


def _tts_media_id(db: Session, employer_id: str, key: str | None) -> str | None:
    """합성된 TTS 파일(상대 키)의 소유 레코드를 만들고 id를 돌려준다. 합성 실패(None)면 None.

    단계마다 새 레코드를 만든다(같은 문장이면 파일은 공유). 레코드를 단계끼리 나눠 쓰지 않아야, 단계를 지우거나
    문장을 고칠 때 그 단계의 레코드를 다른 단계 걱정 없이 바로 지울 수 있다.
    """
    if not key:
        return None
    rec = media.create_record(db, employer_id, media.KIND_TTS, key)
    return rec.id if rec is not None else None


def _step_media_ids(steps) -> list[str]:
    return [i for s in steps for i in (s.symbol_media_id, s.tts_media_id) if i]


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
    # purge: 보존기간 삭제 스케줄(scheduler 서비스)의 마지막 성공 시각·경과 시간(maintenance.py).
    # 실패해도 status는 ok로 둔다 — compose healthcheck가 이 응답을 보므로, 삭제가 밀렸다고 API까지 내리면 안 된다.
    # 모니터링은 purge.stale(주기의 1.5배 초과 또는 한 번도 성공 안 함)을 경보로 쓴다.
    return {"status": "ok", "purge": maintenance.health_info()}


# --- 인증 ---
@app.post("/api/auth/login", response_model=TokenOut)
def employer_login(payload: EmployerLogin, request: Request,
                   db: Session = Depends(get_db)) -> TokenOut:
    # IP 단위(여러 계정 대입)와 계정 단위(여러 IP에서 한 계정 대입)를 모두 센다.
    keys = (f"ip:{client_ip(request)}", f"id:{payload.login_id}")
    ensure_not_blocked(employer_throttle, *keys)
    employer = db.scalar(select(Employer).where(Employer.login_id == payload.login_id))
    if employer is None or not verify_password(payload.password, employer.password_hash):
        for k in keys:
            employer_throttle.fail(k)
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    employer_throttle.reset(f"id:{payload.login_id}")
    return TokenOut(token=make_token(employer.id, "employer"), role="employer",
                    display_name=employer.org_name or employer.name)


@app.post("/api/auth/worker-login", response_model=TokenOut)
def worker_login(payload: WorkerLogin, request: Request,
                 db: Session = Depends(get_db)) -> TokenOut:
    # 성공해도 IP 카운터를 비우지 않는다. 비우면 공격자가 자기 코드로 한 번씩 로그인해
    # 카운터를 계속 초기화하며 대입할 수 있다. 창(window)이 지나면 저절로 풀린다.
    key = f"ip:{client_ip(request)}"
    ensure_not_blocked(worker_throttle, key)
    # 접속 코드는 사업장 안에서만 unique다. 사업장 코드로 사업장을 먼저 정하고, 그 사업장 기준
    # 해시로만 찾는다 — 다른 사업장 근로자의 코드는 여기서 절대 맞지 않는다.
    employer = db.scalar(select(Employer).where(
        Employer.workplace_code == normalize_workplace_code(payload.workplace_code)))
    # 사업장 코드가 없어도 해시 계산과 근로자 조회를 똑같이 한 번 한다. 건너뛰면 응답이 쿼리 하나만큼
    # 빨라져, 메시지가 같아도 응답 시간으로 "이 사업장 코드가 존재한다"를 알 수 있다(타이밍 오라클).
    # 빈 employer_id로는 어떤 근로자도 맞지 않는다(Worker.employer_id는 FK라 비어 있을 수 없다).
    employer_id = employer.id if employer is not None else ""
    worker = db.scalar(select(Worker).where(
        Worker.employer_id == employer_id,
        Worker.access_code_hash == hash_access_code(employer_id, payload.access_code.strip()),
    ))
    if employer is None:
        worker = None
    if worker is None:
        worker_throttle.fail(key)
        # 사업장 코드가 틀린 경우와 접속 코드가 틀린 경우를 같은 응답으로 돌려준다.
        # 다르게 답하면 사업장 코드가 존재하는지를 이 엔드포인트로 탐지할 수 있다.
        raise HTTPException(status_code=401, detail="사업장 코드 또는 접속 코드가 올바르지 않습니다.")
    return TokenOut(token=make_token(worker.id, "worker",
                                     extra={"cf": code_fingerprint(worker.access_code_hash)}),
                    role="worker",
                    display_name=worker.display_name)


def current_worker(user: dict = Depends(require_worker), db: Session = Depends(get_db)) -> dict:
    """근로자 토큰이 지금도 유효한 근로자를 가리키는지 확인한다.

    토큰은 서명만 확인하면 만료(24시간)까지 통과한다. 그러면 삭제된 근로자나, 코드가 새어
    재발급한 뒤의 예전 토큰도 계속 쓰인다. 근로자 존재와 접속 코드 지문(cf)을 DB와 대조한다.
    지문이 없는 토큰은 이 기능 이전에 발급된 것이라 만료까지만 받아 준다.
    """
    worker = db.get(Worker, user["sub"])
    if worker is None:
        raise HTTPException(status_code=401, detail="근로자 정보를 찾을 수 없습니다. 다시 로그인해 주세요.")
    if "cf" in user and user["cf"] != code_fingerprint(worker.access_code_hash):
        raise HTTPException(status_code=401, detail="접속 코드가 바뀌었습니다. 새 코드로 다시 로그인해 주세요.")
    return user


# --- 사업주: 근로자 관리 ---
@app.get("/api/workers", response_model=list[WorkerOut])
def list_workers(request: Request, db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> list[WorkerOut]:
    workers = db.scalars(
        select(Worker).where(Worker.employer_id == user["sub"]).order_by(Worker.created_at)
    ).all()
    ids = [w.id for w in workers]
    consented = workers_with_active_consent(db, ids)
    personal = workers_with_active_consent(db, ids, CONSENT_PERSONAL_INFO)
    # 목록에는 근로자마다 이름·메모가 실린다. worker_id=None 한 줄로는 누구의 정보가 보였는지 추적할 수 없어
    # 실린 근로자마다 남긴다(3차 검증 지적). 3초 폴링 묶기는 근로자별로 적용된다.
    record_access_for_workers(db, request, user, "worker.list", ids)
    return [_worker_out(w, w.id in consented, w.id in personal) for w in workers]


def _worker_out(w: Worker, ai_consent: bool = False, personal_info_consent: bool = False) -> WorkerOut:
    return WorkerOut(id=w.id, display_name=w.display_name,
                     access_code_hint=w.access_code_hint, access_code_length=w.access_code_length,
                     note=w.note or "", ai_note_allowed=bool(w.ai_note_allowed), ai_consent=ai_consent,
                     personal_info_consent=personal_info_consent,
                     name_ambiguous=is_ambiguous_name(w.display_name))


def _owned_worker(worker_id: str, employer_id: str, db: Session) -> Worker:
    worker = db.get(Worker, worker_id)
    if worker is None or worker.employer_id != employer_id:
        # 존재 여부를 노출하지 않도록 소유자 불일치도 404로 통일한다(_owned_task와 같은 규칙).
        raise HTTPException(status_code=404, detail="근로자를 찾을 수 없습니다.")
    return worker


def _worker_with_code(w: Worker, code: str, ai_consent: bool = False,
                      personal_info_consent: bool = False) -> WorkerWithCodeOut:
    # 평문 코드는 DB에 없으므로, 방금 만든(또는 받은) 코드를 응답에 한 번만 실어 보낸다.
    return WorkerWithCodeOut(**_worker_out(w, ai_consent, personal_info_consent).model_dump(),
                             access_code=code)


@app.get("/api/workplace", response_model=WorkplaceOut)
def my_workplace(db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> WorkplaceOut:
    """근로자 기기에 입력해 둘 사업장 코드. 근로자 관리 화면에 보여 준다."""
    employer = db.get(Employer, user["sub"])
    if employer is None:
        raise HTTPException(status_code=401, detail="사업주 정보를 찾을 수 없습니다. 다시 로그인해 주세요.")
    return WorkplaceOut(workplace_code=employer.workplace_code, org_name=employer.org_name)


@app.post("/api/workers", response_model=WorkerWithCodeOut, status_code=201)
def create_worker(payload: WorkerCreate, db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> WorkerWithCodeOut:
    if payload.access_code is not None:
        # 코드를 직접 정하는 요청은 "이 코드를 쓰는 동료가 있나"를 시험하는 통로가 될 수 있다
        # (409 응답). 근로자 로그인과 같은 제한을 사업주 id 단위로 건다.
        key = f"employer:{user['sub']}"
        ensure_not_blocked(worker_throttle, key)
        # 접속 코드는 사업장 안에서만 unique다. 다른 사업장의 코드와는 충돌 자체가 없으므로
        # 이 409는 자기 사업장 정보만 드러낸다(예전에는 전역 unique라 남의 사업장 코드를 알려 줬다).
        if _access_code_taken(db, user["sub"], payload.access_code):
            worker_throttle.fail(key)
            raise HTTPException(status_code=409, detail="이미 사용 중인 접속 코드입니다. 다른 코드를 입력해 주세요.")
    for _ in range(_CODE_COMMIT_ATTEMPTS):
        code = (payload.access_code if payload.access_code is not None
                else _new_access_code(db, user["sub"]))
        worker = Worker(employer_id=user["sub"], display_name=payload.display_name)
        worker.set_access_code(code)
        db.add(worker)
        try:
            db.commit()
        except IntegrityError:
            # 위의 중복 확인과 commit 사이에 같은 사업장에서 같은 코드가 먼저 저장된 경우
            # (동시 요청). DB의 (employer_id, access_code_hash) unique가 막아 준 것을 500이 아니라
            # 직접 지정이면 409, 서버 생성이면 다른 코드로 다시 시도한다.
            db.rollback()
            if payload.access_code is not None:
                worker_throttle.fail(f"employer:{user['sub']}")
                raise HTTPException(status_code=409,
                                    detail="이미 사용 중인 접속 코드입니다. 다른 코드를 입력해 주세요.")
            continue
        db.refresh(worker)
        return _worker_with_code(worker, code)
    raise HTTPException(status_code=503, detail="접속 코드를 만들지 못했습니다. 다시 시도해 주세요.")


ACCESS_CODE_DIGITS = 6
# 서버가 만든 코드가 확인과 저장 사이에 동시 요청과 겹쳤을 때 다시 뽑는 횟수. 6자리라 거의 일어나지 않는다.
_CODE_COMMIT_ATTEMPTS = 5


def _access_code_taken(db: Session, employer_id: str, code: str) -> bool:
    return db.scalar(select(Worker.id).where(
        Worker.employer_id == employer_id,
        Worker.access_code_hash == hash_access_code(employer_id, code),
    )) is not None


def _new_access_code(db: Session, employer_id: str) -> str:
    """사업장 안에서 겹치지 않는 6자리 무작위 숫자 코드. 근로자가 누르기 쉽게 숫자만 쓴다."""
    for _ in range(50):
        code = "".join(secrets.choice("0123456789") for _ in range(ACCESS_CODE_DIGITS))
        if not _access_code_taken(db, employer_id, code):
            return code
    raise HTTPException(status_code=503, detail="접속 코드를 만들지 못했습니다. 다시 시도해 주세요.")


@app.post("/api/workers/{worker_id}/access-code", response_model=WorkerWithCodeOut)
def reissue_access_code(worker_id: str, db: Session = Depends(get_db),
                        user: dict = Depends(require_employer)) -> WorkerWithCodeOut:
    """접속 코드를 새 6자리 무작위 코드로 바꾼다(예전 짧은 코드 교체·코드 유출 시).

    이미 발급된 로그인 토큰도 함께 무효가 된다. 토큰의 cf 지문은 저장된 코드 해시에서 만들므로,
    코드가 바뀌면 지문이 맞지 않아 current_worker에서 401이 된다(새 코드로 다시 로그인해야 한다).
    """
    worker = db.get(Worker, worker_id)
    if worker is None or worker.employer_id != user["sub"]:
        raise HTTPException(status_code=404, detail="근로자를 찾을 수 없습니다.")
    for _ in range(_CODE_COMMIT_ATTEMPTS):
        code = _new_access_code(db, user["sub"])
        # 해시가 바뀌면 cf 지문도 바뀌어 예전 토큰은 current_worker에서 401이 된다.
        worker.set_access_code(code)
        try:
            db.commit()
        except IntegrityError:
            # 확인과 저장 사이에 동시 요청이 같은 코드를 먼저 가져간 경우. 다른 코드로 다시 뽑는다.
            db.rollback()
            continue
        return _worker_with_code(worker, code, has_active_consent(db, worker.id),
                                 has_active_consent(db, worker.id, CONSENT_PERSONAL_INFO))
    raise HTTPException(status_code=503, detail="접속 코드를 만들지 못했습니다. 다시 시도해 주세요.")


@app.patch("/api/workers/{worker_id}", response_model=WorkerOut)
def update_worker(worker_id: str, payload: WorkerUpdate, request: Request,
                  db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> WorkerOut:
    """근로자 이름·메모·"AI 코칭에 메모 사용" 허용을 바꾼다. 보낸 필드만 바꾼다."""
    worker = _owned_worker(worker_id, user["sub"], db)
    if payload.display_name is not None and payload.display_name.strip():
        worker.display_name = payload.display_name.strip()
    if payload.note is not None:
        worker.note = payload.note.strip()
    if payload.ai_note_allowed is not None:
        worker.ai_note_allowed = payload.ai_note_allowed
    record_access(db, request, user, "worker.update", worker.id, commit=False)
    db.commit()
    db.refresh(worker)
    return _worker_out(worker, has_active_consent(db, worker.id),
                       has_active_consent(db, worker.id, CONSENT_PERSONAL_INFO))


# --- 사업주: 동의 기록 ---
def _consent_out(c: WorkerConsent) -> ConsentOut:
    return ConsentOut(id=c.id, consent_type=c.consent_type, subject=c.subject,
                      policy_version=c.policy_version, granted_at=c.granted_at,
                      revoked_at=c.revoked_at, recorded_by=c.recorded_by)


@app.get("/api/workers/{worker_id}/consents", response_model=list[ConsentOut])
def list_consents(worker_id: str, request: Request, db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> list[ConsentOut]:
    _owned_worker(worker_id, user["sub"], db)
    rows = db.scalars(select(WorkerConsent).where(WorkerConsent.worker_id == worker_id)
                      .order_by(WorkerConsent.granted_at)).all()
    record_access(db, request, user, "worker.consents", worker_id)
    return [_consent_out(c) for c in rows]


@app.post("/api/workers/{worker_id}/consents", response_model=ConsentOut, status_code=201)
def grant_consent(worker_id: str, payload: ConsentCreate, request: Request,
                  db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> ConsentOut:
    """보호자·당사자에게서 받은 동의를 기록한다. 지금 개인정보 처리방침 버전이 함께 남는다.

    같은 종류의 동의를 다시 받으면(예: 방침 개정 후 재동의) 새 행을 쌓는다 — 예전 동의가 언제 어떤 버전이었는지가
    근거로 남아야 하므로 덮어쓰지 않는다.
    """
    _owned_worker(worker_id, user["sub"], db)
    consent = WorkerConsent(worker_id=worker_id, consent_type=payload.consent_type,
                            subject=payload.subject, policy_version=policy_version(),
                            recorded_by=user["sub"])
    db.add(consent)
    record_access(db, request, user, "worker.consent.grant", worker_id, commit=False)
    db.commit()
    db.refresh(consent)
    return _consent_out(consent)


@app.post("/api/workers/{worker_id}/consents/{consent_id}/revoke", response_model=ConsentOut)
def revoke_consent(worker_id: str, consent_id: str, request: Request,
                   db: Session = Depends(get_db),
                   user: dict = Depends(require_employer)) -> ConsentOut:
    """동의 철회. 행을 지우지 않고 철회 시각을 남긴다(언제까지 유효했는지가 근거가 된다)."""
    _owned_worker(worker_id, user["sub"], db)
    consent = db.get(WorkerConsent, consent_id)
    if consent is None or consent.worker_id != worker_id:
        raise HTTPException(status_code=404, detail="동의 기록을 찾을 수 없습니다.")
    if consent.revoked_at is None:
        consent.revoked_at = datetime.now(timezone.utc)
    record_access(db, request, user, "worker.consent.revoke", worker_id, commit=False)
    db.commit()
    db.refresh(consent)
    return _consent_out(consent)


# --- 사업주: 근로자 데이터 내보내기(근로자·보호자의 열람 요구에 바로 응하기 위한 셀프서비스) ---
def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


@app.get("/api/workers/{worker_id}/export")
def export_worker(worker_id: str, request: Request, db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> JSONResponse:
    """근로자 한 명의 데이터(프로필·동의·배정·수행 로그)를 JSON 파일로 내려준다.

    접속 코드 해시는 인증 비밀이라 넣지 않는다. 서버에 사본을 만들지 않고 응답으로만 보낸다
    (내보낸 파일이 서버 디스크에 남으면 그것도 파기 대상이 된다).
    """
    worker = _owned_worker(worker_id, user["sub"], db)
    consents = db.scalars(select(WorkerConsent).where(WorkerConsent.worker_id == worker_id)
                          .order_by(WorkerConsent.granted_at)).all()
    assignments = db.scalars(select(Assignment).where(Assignment.worker_id == worker_id)
                             .order_by(Assignment.assigned_date)).all()
    task_ids = {a.task_id for a in assignments}
    tasks = {t.id: t for t in db.scalars(select(Task).where(Task.id.in_(task_ids))).all()}
    logs = db.scalars(select(PerformanceLog).where(
        PerformanceLog.assignment_id.in_([a.id for a in assignments]))
        .order_by(PerformanceLog.completed_at)).all()
    steps = {s.id: s for s in db.scalars(
        select(Step).where(Step.id.in_({log.step_id for log in logs}))).all()}

    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": policy_version(),
        "worker": {
            "id": worker.id, "display_name": worker.display_name, "note": worker.note or "",
            "ai_note_allowed": bool(worker.ai_note_allowed), "created_at": _iso(worker.created_at),
            "access_code_hint": worker.access_code_hint,
        },
        "consents": [_consent_out(c).model_dump(mode="json") for c in consents],
        "assignments": [{
            "id": a.id, "task_id": a.task_id,
            "task_title": tasks[a.task_id].title if a.task_id in tasks else "",
            "assigned_date": _iso(a.assigned_date), "status": a.status,
        } for a in assignments],
        "performance_logs": [{
            "assignment_id": log.assignment_id, "step_id": log.step_id,
            "step_order": steps[log.step_id].order_index if log.step_id in steps else None,
            "sentence": steps[log.step_id].sentence if log.step_id in steps else "",
            "completed_at": _iso(log.completed_at), "duration_sec": log.duration_sec,
            "replay_count": log.replay_count, "stuck": bool(log.stuck),
        } for log in logs],
    }
    record_access(db, request, user, "worker.export", worker_id)
    # 파일명에 이름을 넣지 않는다(다운로드 폴더·브라우저 기록에 남는다). id 앞부분으로 구분한다.
    return JSONResponse(content=data, headers={
        "Content-Disposition": f'attachment; filename="worker-{worker.id[:8]}.json"',
        "Cache-Control": "no-store",
    })


@app.get("/api/workers/{worker_id}/tasks", response_model=list[TaskSummaryOut])
def worker_tasks(worker_id: str, request: Request, date: str | None = None,
                 db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> list[TaskSummaryOut]:
    """특정 근로자에게 배정된 직무 목록(중복 제거, 최신순).

    date(YYYY-MM-DD)를 주면 그 날짜에 배정된 직무만 반환한다(달력 보기용).
    날짜는 현지(APP_UTC_OFFSET_HOURS) 기준이다 — 브라우저의 "오늘"·worker_today와 같은 기준.
    """
    _owned_worker(worker_id, user["sub"], db)
    record_access(db, request, user, "worker.history", worker_id)
    assignment_query = select(Assignment).where(Assignment.worker_id == worker_id)
    if date:
        assignment_query = assignment_query.where(
            func.date(Assignment.assigned_date, _SQL_LOCAL_DATE_MODIFIER) == date
        )
    task_ids = list({a.task_id for a in db.scalars(assignment_query).all()})
    if not task_ids:
        return []
    tasks = db.scalars(
        select(Task).where(Task.id.in_(task_ids)).order_by(Task.created_at.desc())
    ).all()
    return [
        TaskSummaryOut(id=t.id, title=t.title, status=t.status, created_at=t.created_at)
        for t in tasks
    ]


@app.get("/api/workers/{worker_id}/active-dates", response_model=list[str])
def worker_active_dates(worker_id: str, request: Request, db: Session = Depends(get_db),
                        user: dict = Depends(require_employer)) -> list[str]:
    """근로자에게 배정이 있는 날짜(YYYY-MM-DD) 목록. 달력에서 활동일 표시용."""
    _owned_worker(worker_id, user["sub"], db)
    record_access(db, request, user, "worker.history", worker_id)
    rows = db.scalars(
        select(func.date(Assignment.assigned_date, _SQL_LOCAL_DATE_MODIFIER))
        .where(Assignment.worker_id == worker_id)
        .distinct()
    ).all()
    return sorted({str(r) for r in rows if r})


@app.delete("/api/workers/{worker_id}")
def delete_worker(worker_id: str, request: Request, db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> dict:
    """근로자를 삭제한다. 그 근로자의 배정·수행 로그·동의 기록도 함께 지운다(직무는 사업주 데이터라 유지).

    개인정보 파기 요건: DB 행만 지우면 SQLite 파일의 빈 페이지와 WAL에 이름·메모가 남는다.
    secure_delete(database.py)로 지운 페이지를 0으로 덮고, 커밋 뒤 WAL을 체크포인트해 옛 프레임도 비운다.
    근로자 단위로 저장하는 파일은 아직 없다(사진·TTS는 직무 단계 단위 — docs/privacy/data-map.md 참고).
    접근 감사 로그는 보존기간 동안 남기되 근로자 id만 담고 이름은 담지 않는다.

    직무 원문·제목·단계 문장(과 그 문장으로 만든 TTS mp3)에 이름을 적었다면 그건 사업주 데이터라 여기서
    지우지 않는다. 대신 이름이 들어 있는 직무 목록(name_mentions)을 돌려줘, 사업주가 고치거나 지우게 한다
    (직무를 고치면 옛 TTS 파일은 미참조가 되어 purge가 지운다).
    WAL 체크포인트가 다른 연결의 읽기 때문에 끝나지 않으면 wal_checkpointed=false로 알린다(purge가 다시 한다).
    """
    worker = _owned_worker(worker_id, user["sub"], db)
    name_mentions = _tasks_mentioning(db, user["sub"], worker.display_name)
    assignment_ids = [a.id for a in db.scalars(
        select(Assignment).where(Assignment.worker_id == worker_id)
    ).all()]
    if assignment_ids:
        db.execute(delete(PerformanceLog).where(PerformanceLog.assignment_id.in_(assignment_ids)))
        db.execute(delete(Assignment).where(Assignment.worker_id == worker_id))
    db.execute(delete(WorkerConsent).where(WorkerConsent.worker_id == worker_id))
    db.delete(worker)
    record_access(db, request, user, "worker.delete", worker_id, commit=False)
    db.commit()
    checkpointed = checkpoint_wal(db)
    return {"ok": True, "wal_checkpointed": checkpointed, "name_mentions": name_mentions}


def _tasks_mentioning(db: Session, employer_id: str, name: str) -> list[dict]:
    """이 사업장 직무 중 원문·제목·단계 문장에 이름이 그대로 들어 있는 것. 근로자 삭제 뒤 사업주 안내용."""
    name = (name or "").strip()
    if len(name) < 2:
        # 한 글자 이름은 거의 모든 문장에 걸려 목록이 의미가 없다.
        return []
    pattern = f"%{name}%"
    in_steps = select(Step.task_id).where(Step.sentence.like(pattern))
    tasks = db.scalars(select(Task).where(
        Task.employer_id == employer_id,
        (Task.title.like(pattern)) | (Task.raw_input.like(pattern)) | (Task.id.in_(in_steps)),
    ).order_by(Task.created_at)).all()
    return [{"task_id": t.id, "title": t.title} for t in tasks]


def _step_search_terms(step: "Step") -> list[str]:
    """단계의 AAC 검색어. 저장된 symbol_query가 있으면 그걸 쓴다(생성 때와 같은 질의),
    없으면 문장에서 뽑는다(사업주가 직접 추가했거나 문장을 수정한 경우)."""
    stored = [t.strip() for t in (step.symbol_query or "").split(",") if t.strip()]
    if stored:
        return stored[:4]
    terms = re.findall(r"[가-힣A-Za-z]+", step.sentence) or [step.sentence[:12]]
    return terms[:4]


def _task_context(task: Task, sentence: str, action_type: str) -> dict:
    """AAC 검색용 맥락. 직무 생성 시와 같은 조건을 재현한다.

    같은 문장이라도 업종 맥락이 있고 없고에 따라 순위와 채택 여부가 달라진다.
    생성·후보조회·단계추가가 모두 이 함수를 거쳐야 결과가 어긋나지 않는다.
    """
    return {
        "business_type": task.business_type or "",
        "work_environment": task.work_environment or "",

        "job": (
            (task.business_type or "")
            if (task.business_type or "").strip()
            else ""
        ),
        "job_hint": task.job or "",

        "sentence": sentence,
        "action_type": action_type,
        # 업종을 안 넣은 직무는 단계 문장 하나만으로 직무를 못 알아낼 때가 많다
        # ("큰 나사를 나누세요"만 봐서는 조립인지 알 수 없다). 원문 전체에는 대개
        # 직무를 알려주는 단어가 하나쯤 있다("부품 상자에서 나사를...") — AAC 검색의
        # infer_job()이 이걸 보조 신호로 쓴다.
        "raw_input": task.raw_input or "",
    }


# --- 사업주: 직무 생성(AI 분해 트리거) ---
def _pick_symbol(
    terms: list[str],
    context: dict | None = None,
) -> dict:
    """작업 단계에 가장 적합한 자체 AAC 이미지를 선택한다."""

    symbols = ai_client.map_symbols(
        terms[:4],
        context=context or {},
    ).get("symbols", [])

    sym = next(
        (
            s
            for s in symbols
            if not s.get("needs_fallback")
            and s.get("image_url")
        ),
        None,
    )

    if sym is None:
        sym = symbols[0] if symbols else {}

    sym = dict(sym)

    # /api/aac/images/... 를
    # http://localhost:8000/api/aac/images/... 로 변환
    sym["image_url"] = public_aac_url(
        sym.get("image_url")
    )

    return sym


# 직무 생성 시 동시에 준비할 단계 수. AI 서비스·TTS에 한꺼번에 몰리는 요청 수의 상한이기도 하다.
_STEP_WORKERS = int(os.getenv("STEP_PREP_WORKERS", "8"))


def _sendable_note(db: Session, worker: Worker | None, note: str | None) -> str:
    """AI로 보내도 되는 근로자 특성 메모. 조건이 하나라도 빠지면 빈 문자열이다.

    - 어느 근로자의 메모인지 정해져 있어야 한다(근로자 미지정이면 누구의 허용인지 알 수 없다).
    - 사업주가 그 근로자에 대해 "AI 코칭에 메모 사용"을 켰어야 한다(기본 꺼짐).
    - 근로자(또는 보호자)의 AI 처리(국외 이전) 동의가 살아 있어야 한다.
    메모에는 장애 특성처럼 민감한 내용이 들어가기 쉬워, 기본값을 "안 보냄"으로 둔다.
    """
    if worker is None or not worker.ai_note_allowed:
        return ""
    if not has_active_consent(db, worker.id):
        return ""
    return (note if note is not None and note.strip() else worker.note or "").strip()


@app.post("/api/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> TaskOut:
    target = _owned_worker(payload.worker_id, user["sub"], db) if payload.worker_id else None
    # AI 하네스로 보내는 글(원문·맥락)에서 근로자 실명을 별칭으로 바꾼다. 하네스는 이 글을 해외 LLM과
    # 임베딩 API로 보낸다. 응답(제목·문장)은 아래에서 실명으로 되돌려 저장한다 — 근로자 화면과 음성은
    # 사업주가 쓴 그대로여야 한다.
    masker = employer_pseudonymizer(db, user["sub"])
    raw_masked = masker.mask(payload.raw_input)
    context = {
        "business_type": masker.mask(payload.business_type or ""),
        "work_environment": masker.mask(payload.work_environment or ""),
        "worker_note": masker.mask(_sendable_note(db, target, payload.worker_note)),
        # _task_context()와 같은 이유로 넣는다 — 업종 미입력 시 직무 추론의 보조 신호.
        "raw_input": raw_masked,
    }
    # 그림 검색에는 메모가 필요 없다. 검색 질의도 임베딩 API로 나갈 수 있으므로 빼고 보낸다.
    symbol_context = {k: v for k, v in context.items() if k != "worker_note"}
    try:
        decomposed = ai_client.decompose(raw_masked, context)
    except Exception:  # noqa: BLE001 - AI 하네스 장애는 502로 전달한다
        # 예외 원문(내부 호스트명·연결 오류 등)은 사용자 화면에 나가면 안 된다. 로그에만 남긴다.
        logger.exception("직무 분해 호출 실패")
        raise HTTPException(status_code=502,
                            detail="직무를 단계로 나누지 못했습니다. 잠시 뒤 다시 시도해 주세요.")

    job = str(decomposed.get("job") or "").strip()
    explicit_business_type = bool(
        context["business_type"].strip()
    )
    steps = decomposed.get("steps", [])

    def prepare(step: dict) -> dict:
        """단계 하나의 그림·음성을 준비한다(네트워크 호출만 하고 DB는 건드리지 않는다).

        그림 검색(AI 하네스)에는 별칭이 든 문장을 그대로 쓰고, 저장·음성 합성에는 실명으로 되돌린 문장을 쓴다.
        """
        masked_sentence = step["sentence"]
        sentence = masker.unmask(masked_sentence)
        action_type = step.get("action_type", "other")

        symbol_terms = (
            step.get("symbol_query")
            or [k["term"] for k in step.get("keywords", [])]
        )
        symbol_terms = symbol_terms[:4] or [masked_sentence[:12]]

        sym = _pick_symbol(
            symbol_terms,
            context={
                **symbol_context,

                # 사용자가 직접 입력한 업종만 hard gate로 사용
                "job": (
                    context["business_type"]
                    if explicit_business_type
                    else ""
                ),

                # LLM이 추론한 직무는 약한 힌트로만 사용
                "job_hint": job,

                "sentence": masked_sentence,
                "action_type": action_type,
            },
        )
        return {
            "sentence": sentence,
            "action_type": action_type,
            "symbol_terms": masker.unmask_obj(symbol_terms),
            "sym": sym,
            # 파일만 만든다(상대 키). 소유 레코드는 아래 DB 단계에서 단계와 같은 트랜잭션으로 만든다.
            "tts": synthesize_tts(sentence, user["sub"]),
        }

    # 단계마다 그림 검색·음성 합성을 순서대로 하면 5~7단계 직무가 20~30초 걸렸다.
    # 단계끼리는 서로 기다릴 이유가 없으니 동시에 돌린다. 결과 순서는 map이 입력 순서대로 지킨다.
    # DB 쓰기는 네트워크 호출이 끝난 뒤에 한다 — SQLite는 쓰는 동안 다른 쓰기를 막는다.
    if steps:
        with ThreadPoolExecutor(max_workers=min(_STEP_WORKERS, len(steps))) as pool:
            prepared = list(pool.map(prepare, steps))
    else:
        prepared = []

    # 맥락을 저장해 둔다. 나중에 후보 재검색/단계 추가가 같은 조건으로 돌아야 한다.
    task = Task(employer_id=user["sub"], title=masker.unmask(decomposed.get("task_title", "직무")),
                # 저장은 사업주가 쓴 원문 그대로(context는 AI로 보낼 별칭 적용본이다).
                raw_input=payload.raw_input, status="draft",
                business_type=payload.business_type or "",
                work_environment=payload.work_environment or "",
                job=job,
                )
    db.add(task)
    db.flush()

    for step, p in zip(steps, prepared):
        sym = p["sym"]
        db.add(
            Step(
                task_id=task.id,
                order_index=step["order"],
                sentence=p["sentence"],
                action_type=p["action_type"],
                symbol_query=",".join(
                            str(term).strip()
                            for term in p["symbol_terms"]
                            if str(term).strip()
                        ),
                symbol_url=sym.get("image_url"),
                symbol_source=sym.get("source", "fallback"),
                needs_fallback=sym.get("needs_fallback", True),
                tts_media_id=_tts_media_id(db, user["sub"], p["tts"]),
            )
        )

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
    media_ids = _step_media_ids(task.steps)
    db.delete(task)  # Step은 Task.steps의 cascade="all, delete-orphan"으로 함께 삭제됨
    db.commit()
    # 직무의 사진은 바로, TTS 레코드는 바로(파일은 GC 유예 뒤) 지운다. 다른 직무가 같은 사진을 쓰면 남는다.
    media.release(db, media_ids)
    return {"ok": True}


@app.post("/api/tasks/{task_id}/steps", response_model=TaskOut, status_code=201)
def add_step(task_id: str, payload: StepCreate, db: Session = Depends(get_db),
             user: dict = Depends(require_employer)) -> TaskOut:
    """검토 화면에서 사업주가 단계를 직접 추가한다.

    맨 끝에 붙이며(순서는 이후 드래그로 조정), 상징/TTS는 서버가 생성한다.
    LLM symbol_query가 없으므로 문장에서 한글/영문 단어를 뽑아 상징 후보로 쓴다.
    """
    task = _owned_task(task_id, user["sub"], db)
    sentence = payload.sentence.strip()
    action_type = payload.action_type or "other"
    terms = re.findall(r"[가-힣A-Za-z]+", sentence) or [sentence[:12]]
    # 직무 생성 때와 같은 맥락으로 검색해야 나중에 추가한 단계만 다른 그림이 붙지 않는다.
    # 검색어·맥락은 AI 하네스(→ 임베딩 API)로 가므로 근로자 실명을 별칭으로 바꿔 보낸다.
    masker = employer_pseudonymizer(db, user["sub"])
    sym = _pick_symbol(masker.mask_obj(terms),
                       context=masker.mask_obj(_task_context(task, sentence, action_type)))
    next_order = max((s.order_index for s in task.steps), default=0) + 1
    db.add(Step(
        task_id=task.id, order_index=next_order, sentence=sentence,
        action_type=action_type,
        symbol_url=sym.get("image_url"),
        symbol_source=sym.get("source", "fallback"),
        needs_fallback=sym.get("needs_fallback", True),
        tts_media_id=_tts_media_id(db, user["sub"], synthesize_tts(sentence, user["sub"])),
    ))
    db.commit()
    db.refresh(task)
    return _task_out(task)


@app.patch("/api/tasks/{task_id}/steps/reorder", response_model=TaskOut)
def reorder_steps(task_id: str, payload: StepReorder, db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> TaskOut:
    """단계 순서를 새로 지정한다.

    step_ids는 이 직무의 모든 단계를 정확히 한 번씩 포함해야 한다(부분 순서 불가).
    받은 순서대로 order_index를 1..N으로 재부여한다.
    """
    task = _owned_task(task_id, user["sub"], db)
    current_ids = {s.id for s in task.steps}
    if len(payload.step_ids) != len(current_ids) or set(payload.step_ids) != current_ids:
        raise HTTPException(status_code=400, detail="순서 목록이 현재 단계와 일치하지 않습니다.")
    order_by_id = {sid: i for i, sid in enumerate(payload.step_ids, start=1)}
    for s in task.steps:
        s.order_index = order_by_id[s.id]
    db.commit()
    db.refresh(task)
    return _task_out(task)


# (Phase 0.3) 업로드 사진은 더 이상 경로 prefix로 받지 않는다. "/api/photos/"만 맞으면 다른 사업장의 사진 URL도
# 붙일 수 있었다. 사진은 아래 update_step에서 소유 레코드(MediaFile.employer_id)를 조회해 받는다.
_OWN_IMAGE_PATHS = ("/api/aac/images/",)


def _is_own_image_url(url: str) -> bool:
    """근로자 화면에 뜨는 그림은 이 서버가 내주는 AAC 이미지여야 한다(업로드 사진은 update_step이 따로 본다).

    아무 URL이나 받으면 외부 이미지(부적절한 그림, 접속 추적용 픽셀)가 근로자 화면에 뜬다.
    경로는 퍼센트 인코딩을 끝까지 푼 뒤 검사한다. 브라우저·프록시는 %2e%2e를 ..로, %2f를 /로 풀어 정규화하므로
    인코딩된 채로 보면 "/api/aac/images/%2e%2e/..."가 prefix 검사를 통과해 AAC 폴더 밖 경로를 가리킬 수 있다.
    이중 인코딩(%252e)도 있으니 더 바뀌지 않을 때까지 푼다. 정규화 결과가 원래 경로와 다르면(., .., //) 거부한다.
    """
    base = os.getenv("PUBLIC_BACKEND_URL", "http://localhost:8000").rstrip("/")
    path = url[len(base):] if url.startswith(base + "/") else url
    decoded = path
    for _ in range(5):
        nxt = unquote(decoded)
        if nxt == decoded:
            break
        decoded = nxt
    else:
        return False  # 다섯 번 풀어도 계속 바뀌는 경로는 정상 그림 URL이 아니다
    if any(ch in decoded for ch in ("\\", "\x00", "?", "#")) or "//" in decoded:
        return False
    # 제어 문자(탭·줄바꿈 등)는 브라우저 URL 파서가 지운 뒤 정규화한다. ".\t."은 여기서는 ".."이 아니지만
    # 브라우저에서는 ".."이 되어 AAC 폴더 밖 경로를 가리키므로, 정상 그림 경로에 없을 제어 문자는 통째로 거부한다.
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in decoded):
        return False
    if posixpath.normpath(decoded) != decoded or ".." in decoded.split("/"):
        return False
    return decoded.startswith(_OWN_IMAGE_PATHS)


_MEDIA_GONE = "사진이 방금 다른 화면에서 지워졌습니다. 사진을 다시 올려 주세요."


@app.patch("/api/tasks/{task_id}/steps/{step_id}", response_model=StepOut)
def update_step(task_id: str, step_id: str, payload: StepUpdate,
                db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> StepOut:
    _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")
    released: list[str] = []
    claimed: str | None = None
    if payload.symbol_url is not None:
        media_id = media.parse_media_url(payload.symbol_url)
        if media_id is not None:
            # 업로드 사진: 서명 대신 소유 레코드를 본다. 다른 사업장 media id·없는 id는 똑같이 거부한다
            # (어느 쪽인지 구분해 알려 주면 남의 media id가 있는지 확인하는 통로가 된다).
            rec = media.owned(db, user["sub"], media_id, media.KIND_PHOTO)
            if rec is None:
                raise HTTPException(status_code=400, detail="이 서비스의 그림이나 사진만 단계에 붙일 수 있습니다.")
            claimed = rec.id
            if step.symbol_media_id and step.symbol_media_id != rec.id:
                released.append(step.symbol_media_id)
            step.symbol_media_id = rec.id
            step.symbol_url = None
            step.symbol_source = "photo"
        else:
            if not _is_own_image_url(payload.symbol_url):
                raise HTTPException(status_code=400, detail="이 서비스의 그림이나 사진만 단계에 붙일 수 있습니다.")
            if step.symbol_media_id:
                released.append(step.symbol_media_id)
            step.symbol_media_id = None
            step.symbol_url = payload.symbol_url
            # 검토 화면에서 AAC 후보를 고른 경우 출처를 LOCAL_AAC로 남긴다.
            # (예전에는 무조건 fallback으로 적어 어디서 온 그림인지 알 수 없었다.)
            step.symbol_source = payload.symbol_source or "fallback"
        step.needs_fallback = False
    if payload.sentence is not None:
        step.sentence = payload.sentence
        if step.tts_media_id:
            released.append(step.tts_media_id)
        step.tts_media_id = _tts_media_id(db, user["sub"], synthesize_tts(payload.sentence, user["sub"]))
        # 저장된 symbol_query는 옛 문장에 묶여 있다. 비우면 후보 조회가 새 문장에서
        # 검색어를 다시 뽑는다.
        step.symbol_query = ""
    # 확인과 커밋 사이에 다른 요청의 release()가 레코드를 지우지 못하게 커밋 직전에 같은 트랜잭션에서 잠근다
    # (media.claim). TTS 합성(네트워크 호출) 뒤에 잠그는 이유: SQLite 쓰기 잠금은 DB 전체라, 합성 동안 쥐고 있으면
    # 다른 모든 쓰기가 기다린다. 이미 지워졌으면 붙이지 않는다 — 400(남의 것)과 구분해 409로 다시 시도하게 한다.
    if claimed is not None and not media.claim(db, user["sub"], claimed, media.KIND_PHOTO):
        db.rollback()
        raise HTTPException(status_code=409, detail=_MEDIA_GONE)
    db.commit()
    media.release(db, released)
    # 커밋 뒤 재확인: claim의 잠금은 SQLite에서는 충분하지만, 격리 수준이 다른 DB나 잠금 밖에서 지운 경우까지
    # 단계가 사라진 media를 가리킨 채 남지 않게 한다. 사라졌으면 그림 없음 상태로 되돌리고 409를 준다.
    db.refresh(step)
    if step.symbol_media_id and not media.exists_(db, step.symbol_media_id):
        step.symbol_media_id = None
        step.symbol_url = None
        step.symbol_source = "fallback"
        step.needs_fallback = True
        db.commit()
        raise HTTPException(status_code=409, detail=_MEDIA_GONE)
    return _step_to_out(step)


@app.get("/api/tasks/{task_id}/steps/{step_id}/symbol-candidates",
         response_model=StepSymbolCandidates)
def step_symbol_candidates(task_id: str, step_id: str, db: Session = Depends(get_db),
                           user: dict = Depends(require_employer)) -> StepSymbolCandidates:
    """단계에 붙일 AAC 후보를 돌려준다(검토 화면의 후보 선택용).

    후보를 컬럼에 저장하지 않고 그때그때 다시 검색한다 — 문장이 수정되면 후보도 따라
    바뀌어야 하는데, 저장해 두면 어긋난 채 굳는다.

    같은 조건으로 검색해야 생성 시 판정과 어긋나지 않는다:
      - 업종 맥락: Task에 저장해 둔 business_type/work_environment
      - 검색어: 생성 때 쓴 symbol_query (단계에 저장). 없으면 문장에서 뽑는다.

    reason='accepted'는 '생성 땐 폴백이었는데 지금 다시 보니 쓸 만한 매칭이 있다'는
    뜻이다(예: 임계값 재교정 후). 그 매칭도 후보로 돌려줘 사업주가 한 번에 적용하게 한다.
    """
    task = _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")

    masker = employer_pseudonymizer(db, user["sub"])
    symbols = ai_client.map_symbols(
        masker.mask_obj(_step_search_terms(step)),
        context=masker.mask_obj(_task_context(task, step.sentence, step.action_type)),
    ).get("symbols", [])
    sym = symbols[0] if symbols else {}
    reason = sym.get("reason", "no_candidate")

    raw = list(sym.get("candidates", []))
    if reason == "accepted" and sym.get("image_url") and not raw:
        # 채택된 매칭은 candidates에 안 실려 온다. 단일 후보로 만들어 준다.
        raw = [{
            "asset_id": sym.get("external_id", ""),
            "group_id": sym.get("external_id", ""),
            "job": "", "asset_type": "action",
            "label": sym.get("resolved_keyword", ""),
            "image_url": sym.get("image_url"),
            "score": sym.get("confidence", 0.0),
        }]

    candidates = [
        AacMatch(**{**c, "image_url": public_aac_url(c.get("image_url"))})
        for c in raw
    ]
    return StepSymbolCandidates(step_id=step.id, reason=reason, candidates=candidates)


@app.delete("/api/tasks/{task_id}/steps/{step_id}", response_model=TaskOut)
def delete_step(task_id: str, step_id: str, db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> TaskOut:
    """단계를 삭제하고 남은 단계의 순서를 1부터 다시 매긴다."""
    task = _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")
    if len(task.steps) <= 1:
        raise HTTPException(
            status_code=400,
            detail="마지막 단계는 삭제할 수 없습니다. 직무 자체를 삭제하려면 대시보드를 이용하세요.",
        )
    # 이 단계를 참조하는 수행 로그를 먼저 정리한다(게시 후 삭제 대비).
    db.execute(delete(PerformanceLog).where(PerformanceLog.step_id == step_id))
    media_ids = _step_media_ids([step])
    db.delete(step)
    db.flush()
    # 남은 단계 순서 재정렬(1,2,3…).
    remaining = db.scalars(
        select(Step).where(Step.task_id == task_id).order_by(Step.order_index)
    ).all()
    for i, s in enumerate(remaining, start=1):
        s.order_index = i
    db.commit()
    media.release(db, media_ids)
    db.refresh(task)
    return _task_out(task)


@app.post("/api/tasks/{task_id}/publish", response_model=TaskOut)
def publish_task(task_id: str, db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> TaskOut:
    task = _owned_task(task_id, user["sub"], db)
    task.status = "published"
    db.commit()
    db.refresh(task)
    return _task_out(task)


@app.post("/api/aac/search", response_model=AacSearchResult)
def search_aac(
    payload: AacSearchRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(require_employer),
) -> AacSearchResult:

    context = {
        "job": payload.job or ""
    }

    # 검색어도 AI 하네스(→ 임베딩 API)로 간다. 근로자 이름을 넣어 검색하는 경우를 대비해 별칭으로 바꾼다.
    masker = employer_pseudonymizer(db, user["sub"])
    result = masker.unmask_obj(ai_client.search_aac(
        masker.mask(payload.query.strip()),
        context=context,
        limit=payload.limit,
    ))

    matches = []

    for item in result.get("matches", []):
        row = dict(item)

        row["image_url"] = (
            public_aac_url(row.get("image_url"))
            or ""
        )

        matches.append(
            AacMatch(**row)
        )

    return AacSearchResult(
        query=result.get(
            "query",
            payload.query.strip(),
        ),
        matches=matches,
    )


# --- 사업주: 근로자에게 배정(여러 명 동시 가능) ---
@app.post("/api/tasks/{task_id}/assignments", response_model=list[AssignmentOut])
def assign_task(task_id: str, payload: AssignRequest = AssignRequest(),
                db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> list[AssignmentOut]:
    task = _owned_task(task_id, user["sub"], db)
    if task.status != "published":
        raise HTTPException(status_code=400, detail="게시된 직무만 배정할 수 있습니다.")

    if payload.worker_ids:
        worker_ids = list(dict.fromkeys(payload.worker_ids))  # 순서 보존 중복 제거
    elif payload.worker_id:
        worker_ids = [payload.worker_id]
    else:
        all_workers = db.scalars(select(Worker).where(Worker.employer_id == user["sub"])).all()
        if len(all_workers) != 1:
            raise HTTPException(status_code=400, detail="배정할 근로자를 지정해 주세요.")
        worker_ids = [all_workers[0].id]

    workers = db.scalars(select(Worker).where(Worker.id.in_(worker_ids))).all()
    found_by_id = {w.id: w for w in workers}
    for wid in worker_ids:
        w = found_by_id.get(wid)
        if w is None or w.employer_id != user["sub"]:
            raise HTTPException(status_code=404, detail="해당 근로자를 찾을 수 없습니다.")

    out: list[AssignmentOut] = []
    for wid in worker_ids:
        # 같은 직무를 같은 근로자에게 이미(미완료로) 배정했다면 중복 생성하지 않고 그대로 돌려준다.
        existing = db.scalar(
            select(Assignment).where(
                Assignment.task_id == task_id,
                Assignment.worker_id == wid,
                Assignment.status != "done",
            )
        )
        if existing is not None:
            out.append(AssignmentOut(id=existing.id, task_id=existing.task_id,
                                     worker_id=existing.worker_id, status=existing.status))
            continue
        a = Assignment(task_id=task_id, worker_id=wid, status="assigned")
        db.add(a)
        db.flush()
        out.append(AssignmentOut(id=a.id, task_id=a.task_id, worker_id=a.worker_id, status=a.status))

    db.commit()
    return out


# --- 근로자: 오늘의 카드 ---
@app.get("/api/worker/me/today", response_model=list[TodayCardOut])
def worker_today(db: Session = Depends(get_db),
                 user: dict = Depends(current_worker)) -> list[TodayCardOut]:
    start_of_day = local_day_start_utc()
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


@app.get("/api/worker/me/history", response_model=list[HistoryCardOut])
def worker_history(db: Session = Depends(get_db),
                   user: dict = Depends(current_worker)) -> list[HistoryCardOut]:
    """근로자 본인이 받았던 일을 전부 최신순으로 돌려준다(오늘 것 포함).

    /api/worker/me/today는 완료된 배정을 목록에서 뺀다(다음 일에 집중하게 하려는 설계)
    — 그 결과 근로자가 끝낸 일을 다시 열어 볼 방법이 없었다. 이 API로 지난 단계별
    그림·문장을 다시 볼 수 있다(완료 처리는 하지 않는 읽기 전용 복습 용도).
    """
    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.worker_id == user["sub"])
        .order_by(Assignment.assigned_date.desc())
    ).all()
    offset = timedelta(hours=APP_UTC_OFFSET_HOURS)
    out: list[HistoryCardOut] = []
    for a in assignments:
        task = db.get(Task, a.task_id)
        if task is None:
            continue
        completed_step_ids = set(db.scalars(
            select(PerformanceLog.step_id).where(PerformanceLog.assignment_id == a.id)
        ).all())
        out.append(HistoryCardOut(
            assignment_id=a.id, task_id=task.id, task_title=task.title,
            assigned_date=(a.assigned_date + offset).date().isoformat(),
            status=a.status,
            steps=[
                HistoryStepOut(**_step_to_out(s).model_dump(),
                               completed=s.id in completed_step_ids)
                for s in task.steps
            ],
        ))
    return out


# --- 근로자: 단계 완료 로그(업서트) ---
@app.post("/api/performance-logs", status_code=201)
def create_log(payload: PerformanceLogCreate, db: Session = Depends(get_db),
               user: dict = Depends(current_worker)) -> dict:
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

    # 근로자 삭제와 겹치는 경우를 막는다. 위의 배정 조회는 쓰기 트랜잭션 밖에서 읽은 것이라, 그 사이에
    # delete_worker가 커밋하면 근로자와 이어지지 않는 고아 수행 로그가 들어가거나(SQLite는 외래 키를
    # 강제하지 않는다), 지워진 배정의 상태 갱신이 StaleDataError로 500이 났다(3차 검증 지적).
    # flush로 쓰기(= SQLite 쓰기 잠금)를 먼저 잡은 뒤 배정이 아직 있는지 다시 본다. 잠금을 잡은 뒤에는
    # 다른 연결이 배정을 지울 수 없으므로, 여기서 있으면 커밋까지 있다.
    gone = HTTPException(status_code=404, detail="배정을 찾을 수 없습니다.")
    try:
        db.flush()
    except StaleDataError:
        db.rollback()
        raise gone from None
    if db.scalar(select(Assignment.id).where(Assignment.id == a.id)) is None:
        db.rollback()
        raise gone
    db.commit()
    return {"ok": True, "assignment_status": a.status}


# --- 사업주: 대시보드 집계 ---
def _log_worker_ids(logs, db: Session) -> set[str]:
    """수행 로그들이 어느 근로자의 것인지(접근 감사용)."""
    assignment_ids = {log.assignment_id for log in logs}
    if not assignment_ids:
        return set()
    return set(db.scalars(
        select(Assignment.worker_id).where(Assignment.id.in_(assignment_ids))
    ).all())


def _logs_by_step(task_id: str, worker_id: str | None, db: Session) -> dict[str, PerformanceLog]:
    """직무의 수행 로그를 step_id 기준으로 모은다.

    worker_id를 주면 해당 근로자의 배정만 집계한다. 한 직무를 여러 근로자에게
    배정한 경우(1:N), worker_id 없이 모으면 같은 step_id가 덮어써져 한 명분만
    남으므로, 대시보드는 항상 근로자를 지정해 호출한다.
    """
    query = select(Assignment).where(Assignment.task_id == task_id)
    if worker_id:
        query = query.where(Assignment.worker_id == worker_id)
    assignment_ids = [a.id for a in db.scalars(query).all()]
    if not assignment_ids:
        return {}
    logs = db.scalars(
        select(PerformanceLog).where(PerformanceLog.assignment_id.in_(assignment_ids))
    ).all()
    return {log.step_id: log for log in logs}


@app.get("/api/dashboard/tasks/{task_id}/workers", response_model=list[DashboardWorkerOut])
def dashboard_workers(task_id: str, request: Request, db: Session = Depends(get_db),
                      user: dict = Depends(require_employer)) -> list[DashboardWorkerOut]:
    """이 직무를 배정받은 근로자 목록(중복 제거). 대시보드 근로자 선택용."""
    _owned_task(task_id, user["sub"], db)
    assignments = db.scalars(
        select(Assignment).where(Assignment.task_id == task_id).order_by(Assignment.assigned_date)
    ).all()
    out: list[DashboardWorkerOut] = []
    seen: set[str] = set()
    for a in assignments:
        if a.worker_id in seen:
            continue
        seen.add(a.worker_id)
        worker = db.get(Worker, a.worker_id)
        if worker is None:
            continue
        out.append(DashboardWorkerOut(
            worker_id=worker.id, display_name=worker.display_name,
            access_code_hint=worker.access_code_hint, status=a.status,
        ))
    # 이 목록에는 여러 근로자의 이름·진행 상태가 실린다. 누구의 정보가 보였는지 남기려고 근로자마다 기록한다.
    record_access_for_workers(db, request, user, "dashboard.workers", [o.worker_id for o in out])
    return out


@app.get("/api/dashboard/tasks/{task_id}", response_model=DashboardOut)
def dashboard(task_id: str, request: Request, worker_id: str | None = None,
              db: Session = Depends(get_db),
              user: dict = Depends(require_employer)) -> DashboardOut:
    task = _owned_task(task_id, user["sub"], db)
    if worker_id:
        # 다른 사업장 근로자 id로 감사 행이 남지 않게, 기록 전에 소유를 확인한다(404 규칙 통일).
        _owned_worker(worker_id, user["sub"], db)
    logs_by_step = _logs_by_step(task_id, worker_id, db)
    # 근로자별 수행 기록 열람. 3초 폴링은 privacy.record_access가 짧은 창 안에서 한 줄로 합친다.
    if worker_id:
        record_access(db, request, user, "dashboard.view", worker_id)
    else:
        # 근로자를 고르지 않은 집계 화면에도 여러 근로자의 수행 기록이 섞여 보인다. worker_id=None 한 줄로는
        # 누구의 기록이 보였는지 알 수 없으므로, 실제로 화면에 실린 기록의 근로자마다 남긴다.
        record_access_for_workers(db, request, user, "dashboard.view",
                                  _log_worker_ids(logs_by_step.values(), db))

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
def task_coaching(task_id: str, request: Request, worker_id: str | None = None,
                  db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> CoachingOut:
    """근로자 수행 데이터를 바탕으로 사업주용 AI 개선 제안을 돌려준다(기능 2).

    개인정보(Phase 0.2):
    - 이 코칭에 기록이 들어가는 근로자 중 한 명이라도 AI 처리 동의가 없거나 철회했으면 LLM을 쓰지 않는다
      (allow_llm=False → AI 하네스가 규칙 기반 제안만 만든다). 근로자를 고르지 않은 집계 코칭은 여러 명의
      기록이 섞이므로 전원의 동의가 필요하다.
    - 직무 제목·문장 속 근로자 실명은 별칭으로 바꿔 보내고, 응답의 별칭은 실명으로 되돌린다.
    - 근로자 특성 메모는 그 근로자를 골랐고, 메모 사용 허용 + 동의가 있을 때만 넣는다.
    """
    task = _owned_task(task_id, user["sub"], db)
    # 다른 사업장 근로자 id면 404. 감사 기록(coaching.view)은 이 확인 뒤에만 남는다.
    target = _owned_worker(worker_id, user["sub"], db) if worker_id else None
    logs_by_step = _logs_by_step(task_id, worker_id, db)

    included_query = select(Assignment.worker_id).where(Assignment.task_id == task_id)
    if worker_id:
        included_query = included_query.where(Assignment.worker_id == worker_id)
    included = sorted(set(db.scalars(included_query).all()))
    consented = workers_with_active_consent(db, included)
    allow_llm = all(w in consented for w in included)

    masker = employer_pseudonymizer(db, user["sub"])
    steps_payload = []
    for s in task.steps:
        log = logs_by_step.get(s.id)
        steps_payload.append({
            "order": s.order_index,
            "sentence": masker.mask(s.sentence),
            "action_type": s.action_type,
            "completed": log is not None,
            "stuck": bool(log.stuck) if log else False,
            "replay_count": log.replay_count if log else 0,
            "duration_sec": log.duration_sec if log else 0.0,
        })

    # 업종·환경을 안 넘기면 LLM이 이 직무가 카페인지 조립인지도 모른 채 제안을 짠다
    # (예전엔 빈 dict를 그대로 넘겨 항상 그런 상태였다).
    coaching_context = {
        "business_type": masker.mask(task.business_type or ""),
        "work_environment": masker.mask(task.work_environment or ""),
        "job": task.job or "",
    }
    if target is not None and allow_llm:
        note = _sendable_note(db, target, None)
        if note:
            coaching_context["worker_note"] = masker.mask(note)
    if worker_id:
        record_access(db, request, user, "coaching.view", worker_id)
    else:
        # 집계 코칭은 배정된 근로자 전원의 기록을 쓴다. 대시보드 집계와 같은 이유로 근로자마다 남긴다.
        record_access_for_workers(db, request, user, "coaching.view", included)
    raw = masker.unmask_obj(ai_client.coaching(masker.mask(task.title), steps_payload,
                                               coaching_context, allow_llm=allow_llm))
    suggestions = []
    for s in raw.get("suggestions", []):
        suggestions.append(CoachingSuggestionOut(
            order=int(s.get("order", 0)),
            issue=str(s.get("issue", "")),
            suggestion=str(s.get("suggestion", "")),
            action=str(s.get("action", "ok")),
        ))
    return CoachingOut(summary=str(raw.get("summary", "")), suggestions=suggestions,
                       ai_excluded=not allow_llm)


@app.get("/api/media/{media_id}")
def get_media(media_id: str, exp: str = "", sig: str = "", db: Session = Depends(get_db)) -> FileResponse:
    """사진·TTS 파일을 서명 URL로 내준다(media.py).

    <img>/<audio>는 Authorization 헤더를 못 보내므로 토큰 대신 서명을 본다. 서명은 인증·소유권 검사를 통과한
    응답에서만 만들어지고 media id에 묶여 있어, 다른 사업장은 id를 알아도 받을 수 없다(서명 없음·위조·만료 → 403).
    """
    if not media.verify(media_id, exp, sig):
        raise HTTPException(status_code=403, detail="링크가 만료됐거나 올바르지 않습니다. 화면을 새로 고쳐 주세요.")
    rec = db.get(MediaFile, media_id)
    path = media.media_path(rec.kind, rec.storage_key) if rec is not None else None
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    remaining = max(int(exp) - int(datetime.now(timezone.utc).timestamp()), 0)
    return FileResponse(path, media_type=media.content_type(rec.storage_key), headers={
        # private: 공유 캐시(프록시)에 남기지 않는다. 브라우저 캐시는 서명이 유효한 동안만 쓴다.
        "Cache-Control": f"private, max-age={remaining}",
        "X-Content-Type-Options": "nosniff",
        # 서명 URL이 다른 사이트의 Referer로 새지 않게 한다(이 응답에서 이동할 일은 없지만 기본값을 막아 둔다).
        "Referrer-Policy": "no-referrer",
    })


@app.post("/api/tasks/{task_id}/steps/{step_id}/photo", response_model=StepOut)
async def upload_step_photo(task_id: str, step_id: str,
                            file: UploadFile = File(...),
                            db: Session = Depends(get_db),
                            user: dict = Depends(require_employer)) -> StepOut:
    """단계에 실제 현장 사진을 올려 자체 AAC 자동 상징을 대체한다(기능 5)."""
    _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")

    # 한도보다 1바이트만 더 읽는다. 전부 읽고 나서 크기를 재면 큰 파일이 통째로 메모리에 올라간다.
    data = await file.read(MAX_PHOTO_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="사진은 5MB 이하만 업로드할 수 있습니다.")
    if sniff_image(data) is None:
        raise HTTPException(status_code=400, detail="이미지 파일(jpg/png/webp/gif)만 업로드할 수 있습니다.")
    try:
        # EXIF(GPS)·메타데이터를 버리고 긴 변 1600px WebP로 다시 만든다(photos.sanitize_image).
        clean = sanitize_image(data)
    except ImageRejected as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from None

    key = save_photo(clean)
    rec = media.create_record(db, user["sub"], media.KIND_PHOTO, key)
    if rec is None:  # 방금 쓴 파일이 없다 = 디스크 문제. 단계는 바꾸지 않는다.
        raise HTTPException(status_code=500, detail="사진을 저장하지 못했습니다. 다시 시도해 주세요.")
    previous = step.symbol_media_id
    step.symbol_media_id = rec.id
    step.symbol_url = None
    step.symbol_source = "photo"
    step.needs_fallback = False
    db.commit()
    # 교체된 옛 사진은 다른 단계가 쓰지 않으면 바로 지운다(커밋 실패로 남은 새 파일은 gc-media가 지운다).
    media.release(db, [previous])
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
    previous = step.symbol_media_id
    step.symbol_media_id = None
    step.symbol_url = None
    step.symbol_source = "fallback"
    step.needs_fallback = True
    db.commit()
    media.release(db, [previous])
    db.refresh(step)
    return _step_to_out(step)
