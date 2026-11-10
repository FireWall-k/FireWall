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
- (근로자 화면 0·1차, 0006) 그림 없는 단계가 있으면 보내기(publish) 422, 그림 4상태(picture_state),
  자동 접속 코드 4자리 + 사업장 단위 로그인 제한, 근로자 화면 설정(a11y_prefs), 오늘 할 일 이어서 하기 정보,
  도움 요청 API(help_requests). 도움 요청은 수행 로그와 따로 두어 단계 완료로 세지 않는다.
- (2a-0, 0007) 버전 고정: 보낼 때 steps를 버전으로 복사하고(versions.py), 근로자 화면·완료 판정·도움·대시보드·내보내기는
  배정의 버전 단계를 읽는다. 편집은 steps만 바꾸고 로그·도움을 지우지 않는다. 보내기 검사·보내기·받는 사람은 send.py.
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

from typing import Literal

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, object_session
from sqlalchemy.orm.exc import StaleDataError
from aac_assets import get_aac_image_dir, public_aac_url

import ai_client
from auth import (
    check_production_config,
    code_fingerprint,
    decrypt_access_code,
    encrypt_access_code,
    hash_access_code,
    hash_password,
    is_production,
    make_device_token,
    make_token,
    require_employer,
    require_worker,
    verify_device_token,
    verify_password,
)
import clock
import db_migrate
import send
import task_list
import versions
import workers_admin
from codes import normalize_workplace_code
from database import get_db
from models import (
    Assignment,
    Employer,
    HelpRequest,
    MediaFile,
    PerformanceLog,
    Step,
    Task,
    TaskVersion,
    TaskVersionStep,
    Worker,
    WorkerConsent,
)
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
    ActiveHelpOut,
    EmployerHelpOut,
    EmployerLogin,
    HelpCreate,
    HelpOut,
    HistoryCardOut,
    HistoryStepOut,
    LogResultOut,
    PerformanceLogCreate,
    SplitPreviewOut,
    SplitPreviewStep,
    StepAddOut,
    StepCreate,
    StepMerge,
    StepOut,
    StepReorder,
    StepRewrite,
    StepRewriteOut,
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
    WorkerMeOut,
    WorkerOut,
    WorkerUpdate,
    WorkerWithCodeOut,
    merge_a11y_prefs,
    parse_a11y_prefs,
)
from ratelimit import (
    client_ip,
    employer_throttle,
    ensure_not_blocked,
    help_throttle,
    take_ai_split_call,
    worker_day_throttle,
    worker_throttle,
    worker_wp_day_throttle,
    worker_wp_throttle,
)
from schemas import MAX_CONFIRMED_STEPS, MAX_RAW_INPUT, MAX_STEP_SENTENCE
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


def _validation_message(errors: list) -> str:
    """요청 검증 실패(422)를 화면에 그대로 띄울 한국어 한 문장으로. FastAPI 기본값은 detail이 목록이라
    프런트 오류 칸에 '[object Object]'가 떴다(입력 화면 나누기 2차 검증)."""
    for err in errors:
        loc = [str(x) for x in err.get("loc") or []]
        kind = str(err.get("type") or "")
        if kind == "value_error":
            msg = str(err.get("msg") or "")
            return msg.removeprefix("Value error, ").strip() or "입력한 내용을 다시 확인해 주세요."
        if "steps" in loc and loc[-1] == "steps" and kind == "too_long":
            return f"단계는 {MAX_CONFIRMED_STEPS}줄까지 만들 수 있어요. 줄을 합치거나 지워 주세요."
        if "steps" in loc and loc[-1] == "steps" and kind == "too_short":
            return "단계가 한 줄 이상 있어야 해요."
        if loc and loc[-1] == "sentence" and kind == "string_too_long":
            return f"한 줄은 {MAX_STEP_SENTENCE}자까지 쓸 수 있어요. 줄을 나눠 주세요."
        if loc and loc[-1] == "sentence" and kind == "string_too_short":
            return "빈 단계 문장이 있습니다."
        if loc and loc[-1] == "raw_input" and kind == "string_too_long":
            return f"직무 내용은 {MAX_RAW_INPUT}자까지 쓸 수 있어요."
        if loc and loc[-1] == "raw_input" and kind in ("string_too_short", "missing"):
            return "직무 내용을 입력해 주세요."
    return "입력한 내용을 다시 확인해 주세요."


@app.exception_handler(RequestValidationError)
async def _korean_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": _validation_message(exc.errors())})


@app.exception_handler(send.ApiError)
async def _api_error(request: Request, exc: send.ApiError) -> JSONResponse:
    # 단계를 가리키는 오류는 {"detail", "code", "step_ids"}(contract §0). 화면은 code로 그 단계로 간다.
    return JSONResponse(status_code=exc.status_code, content=exc.body())

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
    # compose는 "${DEMO_SEED:-}"로 넘겨 .env에 값이 없으면 빈 문자열이 '설정된' 상태가 된다. 빈 값을 끔으로
    # 읽으면 compose로 새로 설치한 개발 서버에 README의 데모 계정이 아예 생기지 않았다 — 빈 값은 미설정과 같다.
    return ((os.getenv("DEMO_SEED") or "").strip() or default) == "1"


def _ensure_seed() -> None:
    """데모 사업주 1명 + 근로자 1명을 보장한다(없으면 생성).

    데모 자격증명은 환경변수로 덮어쓸 수 있다. 운영에서는 만들지 않는다(_demo_seed_enabled).
    """
    if not _demo_seed_enabled():
        return
    db = next(get_db())
    try:
        if db.scalar(select(Employer).limit(1)) is not None:
            _backfill_demo_code_cipher(db)
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


def _backfill_demo_code_cipher(db: Session) -> None:
    """0005 이전에 만든 데모 근로자는 코드 암호문이 비어 사업주 화면에 뒤 2자리만 보인다. 데모 코드는 공개
    기본값(DEMO_WORKER_CODE)이라 해시가 그 값과 맞으면 바로 채운다. 다른(바뀐) 코드는 건드리지 않는다."""
    employer = db.scalar(select(Employer).where(
        Employer.login_id == os.getenv("DEMO_EMPLOYER_LOGIN", "demo")))
    if employer is None:
        return
    code = os.getenv("DEMO_WORKER_CODE", "1234")
    worker = db.scalar(select(Worker).where(Worker.employer_id == employer.id,
                                            Worker.access_code_hash == hash_access_code(employer.id, code)))
    if worker is not None and worker.access_code_cipher is None:
        worker.access_code_cipher = encrypt_access_code(employer.id, code)
        db.commit()


@app.get("/api/auth/demo")
def demo_credentials(db: Session = Depends(get_db)) -> dict:
    """로그인 화면이 데모 계정을 미리 채우게 한다('로그인'만 누르면 들어가는 시연용).

    - 운영이거나 데모 시드가 꺼져 있으면 404 — 데모 계정이 없는 서버에서는 아무것도 알려 주지 않는다.
    - 비밀번호·접속 코드는 '저장소에 공개된 기본값(환경변수)이 지금도 맞을 때만' 돌려준다. 사업주가
      데모 계정 비밀번호나 근로자 코드를 바꿨다면 그 값은 이제 비밀이므로 null로 둔다(실제 값을 흘리지 않는다).
    - 사업장 코드는 DB 값을 준다. Alembic 도입 전 설치본의 데모 사업주는 0002 리비전에서 무작위 코드를
      받았으므로 환경변수 기본값(DEMO01)을 주면 근로자 로그인이 틀린다.
    """
    if is_production() or not _demo_seed_enabled():
        raise HTTPException(status_code=404, detail="Not Found")
    login_id = os.getenv("DEMO_EMPLOYER_LOGIN", "demo")
    password = os.getenv("DEMO_EMPLOYER_PASSWORD", "demo1234")
    worker_code = os.getenv("DEMO_WORKER_CODE", "1234")
    employer = db.scalar(select(Employer).where(Employer.login_id == login_id))
    if employer is None:
        raise HTTPException(status_code=404, detail="Not Found")
    employer_out = ({"login_id": login_id, "password": password}
                    if verify_password(password, employer.password_hash) else None)
    code_hash = hash_access_code(employer.id, worker_code)
    has_worker = db.scalar(select(Worker.id).where(Worker.employer_id == employer.id,
                                                   Worker.access_code_hash == code_hash)) is not None
    worker_out = ({"workplace_code": employer.workplace_code, "access_code": worker_code}
                  if has_worker and employer.workplace_code else None)
    return {"employer": employer_out, "worker": worker_out}


def _utcnow() -> datetime:
    """DB에 저장하는 시각(naive UTC). SQLite DateTime은 시간대를 저장하지 않아, 비교는 naive UTC끼리 한다."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive_utc(dt: datetime | None) -> datetime | None:
    if dt is None or dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


# 그림 4상태와 편집 단계 응답은 versions.py에 있다(보내기 검사 send.py와 같이 쓴다). 예전 이름을 그대로 둔다.
picture_state = versions.picture_state
_step_to_out = versions.step_to_out


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
    # (2a-0) 보낸 버전·고친 내용 안 보냄·하는 중 수·받은 사람 수·고친 날을 함께 싣는다(contract §1.4).
    session = object_session(task)
    meta = versions.task_meta(session, task) if session is not None else {}
    return TaskOut(id=task.id, title=task.title, status=task.status,
                   steps=[_step_to_out(s) for s in task.steps], **meta)


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
    wp_key = f"wp:{normalize_workplace_code(payload.workplace_code)}"
    employer = db.scalar(select(Employer).where(
        Employer.workplace_code == normalize_workplace_code(payload.workplace_code)))
    # 믿는 기기(2차 검증): 이 사업장에 한 번 맞게 들어온 기기는 서명된 기기 표시(device_token)를 갖고 있다.
    # 그런 기기의 "주인 근로자"는 사업장·IP 공용 잠금에 막히지 않고, 근로자 몫의 잠금("dev:{근로자 id}")만 본다.
    # 예전에는 사업장 코드를 아는 사람이 100번 틀리면(또는 근로자들이 하루 동안 잘못 누른 것이 쌓이면) 맞는 번호를
    # 넣은 근로자까지 24시간 막혔다.
    # 3차 검증: 믿음은 그 기기의 주인에게만 준다. 예전에는 표시가 있으면 틀린 번호를 사업장 키에 세지 않았고, 동료
    # 번호로도 들어가 동료 몫의 새 표시를 받았다 — 나쁜 동료가 사업장 하루 한도 위에 자기 몫 100번을 더 얹고,
    # 뚫은 동료마다 100번씩 늘릴 수 있었다. 지금은
    #   - 틀린 번호는 근로자 몫에 더해 IP·사업장 키에도 센다(믿지 않는 기기와 같은 예산을 쓴다).
    #   - 주인이 아닌 근로자로 맞으면 믿지 않는 기기와 같은 IP·사업장 잠금을 본다. 잠겨 있으면 틀린 번호와 같은
    #     401로 답한다(429로 답하면 "이 번호는 맞다"를 알려 주게 된다).
    #   - 표시의 근로자가 지워졌거나 코드가 다시 발급됐으면(지문 cf가 다르면) 믿지 않는다.
    device = verify_device_token(payload.device_token)
    owner = None
    if device is not None and employer is not None and device["e"] == employer.id:
        owner = db.get(Worker, device["w"])
        if (owner is None or owner.employer_id != employer.id
                or device.get("cf") != code_fingerprint(owner.access_code_hash)):
            owner = None
    trusted = owner is not None
    shared_keys = ((worker_throttle, key), (worker_wp_throttle, wp_key),
                   (worker_day_throttle, key), (worker_wp_day_throttle, wp_key))
    if trusted:
        own_keys = ((worker_throttle, f"dev:{owner.id}"), (worker_day_throttle, f"dev:{owner.id}"))
        check_keys = own_keys
        fail_keys = own_keys + shared_keys
    else:
        # 자동 코드는 4자리라(창업자 결정 3) 시도 제한이 방어선이다. IP 키에 더해 사업장 키로도 센다 — IP를 바꿔 가며
        # 한 사업장의 1만 개를 훑는 대입을 막는다. 없는 사업장 코드도 같은 키 규칙으로 센다(존재 오라클 방지).
        # 하루 창: 10분 창이 풀릴 때마다 다시 훑는 느린 대입을 막는다(사업장·IP 각각 하루 100번).
        check_keys = shared_keys
        fail_keys = shared_keys
    for throttle, k in check_keys:
        ensure_not_blocked(throttle, k)
    # 접속 코드는 사업장 안에서만 unique다. 사업장 코드로 사업장을 먼저 정하고, 그 사업장 기준
    # 해시로만 찾는다 — 다른 사업장 근로자의 코드는 여기서 절대 맞지 않는다.
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
    if worker is not None and trusted and worker.id != owner.id:
        # 주인이 아닌 근로자: 믿지 않는 기기와 같은 공용 잠금을 본다. 잠겼으면 틀린 번호와 똑같이 답한다.
        if any(throttle.retry_after(k) for throttle, k in shared_keys):
            worker = None
    if worker is None:
        for throttle, k in fail_keys:
            throttle.fail(k)
        # 사업장 코드가 틀린 경우와 접속 코드가 틀린 경우를 같은 응답으로 돌려준다.
        # 다르게 답하면 사업장 코드가 존재하는지를 이 엔드포인트로 탐지할 수 있다.
        raise HTTPException(status_code=401, detail="사업장 코드 또는 접속 코드가 올바르지 않습니다.")
    if worker.access_code_cipher is None:
        # 0005 이전 근로자는 평문 코드를 알 수 없어 사업주 화면에 뒤 2자리만 보였다. 로그인에 성공한 지금은
        # 서버가 맞는 평문을 받았으니 암호문을 채워 둔다 — 그다음부터 사업주 화면에 전체 코드가 보인다.
        worker.access_code_cipher = encrypt_access_code(worker.employer_id, payload.access_code.strip())
        db.commit()
    return TokenOut(token=make_token(worker.id, "worker",
                                     extra={"cf": code_fingerprint(worker.access_code_hash)}),
                    role="worker",
                    display_name=worker.display_name,
                    # 근로자 기기가 키패드 위 띠에 보여 줄 사업장 이름(로그인한 뒤에만 알려 준다).
                    workplace_name=employer.org_name or employer.name,
                    device_token=make_device_token(employer.id, worker.id,
                                                   code_fingerprint(worker.access_code_hash)))


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
    # (2d) 목록 열: 오늘 배지·7일 완료·7일 도움·동의 상태. 전체 접속 코드는 싣지 않는다(reveal로만).
    columns = workers_admin.list_columns(db, ids)
    return [_worker_out(w, w.id in consented, w.id in personal).model_copy(update=columns[w.id])
            for w in workers]


def _worker_out(w: Worker, ai_consent: bool = False, personal_info_consent: bool = False) -> WorkerOut:
    return WorkerOut(id=w.id, display_name=w.display_name,
                     access_code_hint=w.access_code_hint, access_code_length=w.access_code_length,
                     code_length=w.access_code_length,
                     note=w.note or "", ai_note_allowed=bool(w.ai_note_allowed), ai_consent=ai_consent,
                     personal_info_consent=personal_info_consent,
                     name_ambiguous=is_ambiguous_name(w.display_name),
                     a11y_prefs=parse_a11y_prefs(w.a11y_prefs))


def _owned_worker(worker_id: str, employer_id: str, db: Session) -> Worker:
    worker = db.get(Worker, worker_id)
    if worker is None or worker.employer_id != employer_id:
        # 존재 여부를 노출하지 않도록 소유자 불일치도 404로 통일한다(_owned_task와 같은 규칙).
        raise HTTPException(status_code=404, detail="근로자를 찾을 수 없습니다.")
    return worker


def _worker_with_code(w: Worker, code: str, ai_consent: bool = False,
                      personal_info_consent: bool = False) -> WorkerWithCodeOut:
    # 방금 만든(또는 받은) 코드를 그대로 싣는다(암호문을 다시 풀 필요가 없다).
    out = _worker_out(w, ai_consent, personal_info_consent).model_dump()
    out["access_code"] = code
    return WorkerWithCodeOut(**out)


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
        if _code_prefix_clash(db, user["sub"], payload.access_code):
            worker_throttle.fail(key)
            raise HTTPException(status_code=409, detail=_PREFIX_CLASH_DETAIL)
    for _ in range(_CODE_COMMIT_ATTEMPTS):
        code = (payload.access_code if payload.access_code is not None
                else _new_access_code(db, user["sub"]))
        # (2d) 새 근로자의 화면 설정은 사업장 기본값에서(이미 있는 근로자는 기본값을 바꿔도 그대로).
        worker = Worker(employer_id=user["sub"], display_name=payload.display_name,
                        a11y_prefs=workers_admin.new_worker_prefs(db.get(Employer, user["sub"])))
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


# 창업자 결정 3: 근로자 키패드는 4자리를 누르면 바로 들어간다. 그래서 자동 코드도 4자리(1만 개)다.
# 사업장 안에서만 겹치지 않으면 된다(_new_access_code가 확인). 대입 방어는 로그인 시도 제한(ratelimit.py)이 한다.
# 사업주가 직접 정한 코드(4~12자리)와 예전에 만든 6자리 코드는 그대로 로그인된다(해시 비교라 길이와 무관).
ACCESS_CODE_DIGITS = 4
# 서버가 만든 코드가 확인과 저장 사이에 동시 요청과 겹쳤을 때 다시 뽑는 횟수.
_CODE_COMMIT_ATTEMPTS = 5


def _access_code_taken(db: Session, employer_id: str, code: str, exclude_worker_id: str | None = None) -> bool:
    query = select(Worker.id).where(
        Worker.employer_id == employer_id,
        Worker.access_code_hash == hash_access_code(employer_id, code),
    )
    if exclude_worker_id is not None:
        query = query.where(Worker.id != exclude_worker_id)
    return db.scalar(query) is not None


_PREFIX_CLASH_DETAIL = ("앞 4자리가 다른 근로자의 접속 코드와 겹칩니다. 근로자 화면(/w)은 4자리를 누르면 바로 "
                        "들어가므로 다른 코드를 입력해 주세요.")


def _code_prefix_clash(db: Session, employer_id: str, code: str, exclude_worker_id: str | None = None) -> bool:
    """4자리 코드와 더 긴 코드의 앞 4자리가 겹치는지(2차 검증).

    근로자 키패드(/w)는 4번째 숫자에서 바로 보낸다. 동료가 '1234', 내가 '123456'이면 내가 /w에서 앞 4자리를
    누르는 순간 동료 계정으로 들어간다. 그래서 4자리 코드는 긴 코드의 앞 4자리와, 긴 코드의 앞 4자리는 4자리 코드와
    같으면 안 된다. 긴 코드의 평문은 암호문(access_code_cipher)을 풀어 본다 — 암호문이 없는 아주 옛 근로자는
    알 수 없어 건너뛴다(그 근로자가 한 번 로그인하면 채워진다).
    """
    if len(code) > ACCESS_CODE_DIGITS:
        return _access_code_taken(db, employer_id, code[:ACCESS_CODE_DIGITS], exclude_worker_id)
    rows = db.execute(select(Worker.id, Worker.access_code_cipher).where(
        Worker.employer_id == employer_id,
        Worker.access_code_length > ACCESS_CODE_DIGITS,
    )).all()
    for wid, cipher in rows:
        if wid == exclude_worker_id:
            continue
        plain = decrypt_access_code(employer_id, cipher)
        if plain is not None and plain.startswith(code):
            return True
    return False


def _new_access_code(db: Session, employer_id: str, exclude_worker_id: str | None = None) -> str:
    """사업장 안에서 겹치지 않는 4자리 무작위 숫자 코드. 근로자가 누르기 쉽게 숫자만 쓴다.

    1만 개 중 50번 뽑는다. 사업장 근로자가 수천 명이 아닌 한 겹치지 않는 코드를 찾는다.
    """
    for _ in range(50):
        code = "".join(secrets.choice("0123456789") for _ in range(ACCESS_CODE_DIGITS))
        # 다시 뽑는 근로자 자신의 예전 코드는 곧 바뀌므로 앞 4자리 겹침 검사에서 뺀다.
        if not _access_code_taken(db, employer_id, code) and                 not _code_prefix_clash(db, employer_id, code, exclude_worker_id):
            return code
    raise HTTPException(status_code=503, detail="접속 코드를 만들지 못했습니다. 다시 시도해 주세요.")


@app.post("/api/workers/{worker_id}/access-code", response_model=WorkerWithCodeOut)
def reissue_access_code(worker_id: str, db: Session = Depends(get_db),
                        user: dict = Depends(require_employer)) -> WorkerWithCodeOut:
    """접속 코드를 새 4자리 무작위 코드로 바꾼다(예전 긴 코드 교체·코드 유출 시).

    이미 발급된 로그인 토큰도 함께 무효가 된다. 토큰의 cf 지문은 저장된 코드 해시에서 만들므로,
    코드가 바뀌면 지문이 맞지 않아 current_worker에서 401이 된다(새 코드로 다시 로그인해야 한다).
    """
    worker = db.get(Worker, worker_id)
    if worker is None or worker.employer_id != user["sub"]:
        raise HTTPException(status_code=404, detail="근로자를 찾을 수 없습니다.")
    for _ in range(_CODE_COMMIT_ATTEMPTS):
        code = _new_access_code(db, user["sub"], exclude_worker_id=worker.id)
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
    """근로자 이름·메모·"AI 코칭에 메모 사용" 허용·화면 설정(a11y_prefs)을 바꾼다. 보낸 필드만 바꾼다."""
    worker = _owned_worker(worker_id, user["sub"], db)
    if payload.display_name is not None and payload.display_name.strip():
        worker.display_name = payload.display_name.strip()
    if payload.note is not None:
        worker.note = payload.note.strip()
    if payload.ai_note_allowed is not None:
        worker.ai_note_allowed = payload.ai_note_allowed
    if payload.a11y_prefs is not None:
        # 보낸 키만 병합한다(예: 소리 자동 재생만 끄기). 결과는 항상 8개 키를 다 채운 JSON이다.
        worker.a11y_prefs = merge_a11y_prefs(worker.a11y_prefs, payload.a11y_prefs)
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
    """근로자 한 명의 데이터(프로필·동의·배정·수행 로그·도움 요청)를 JSON 파일로 내려준다.

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
    helps = db.scalars(select(HelpRequest).where(HelpRequest.worker_id == worker_id)
                       .order_by(HelpRequest.created_at)).all()
    # (2a-0) 로그·도움은 버전 단계를 가리킨다. 문장은 그 로그의 버전 단계 문장이다(contract §1.7).
    steps = versions.find_steps(db, {log.step_id for log in logs} | {h.step_id for h in helps if h.step_id})
    version_nos = dict(db.execute(
        select(TaskVersion.id, TaskVersion.version_no)
        .where(TaskVersion.id.in_({a.task_version_id for a in assignments if a.task_version_id}))).all())

    data = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": policy_version(),
        "worker": {
            "id": worker.id, "display_name": worker.display_name, "note": worker.note or "",
            "ai_note_allowed": bool(worker.ai_note_allowed), "created_at": _iso(worker.created_at),
            "access_code_hint": worker.access_code_hint,
            # 0006: 근로자 화면 설정과 마지막 접속 시각도 그 사람에 관한 정보라 사본에 싣는다.
            "a11y_prefs": parse_a11y_prefs(worker.a11y_prefs).model_dump(mode="json"),
            "last_seen_at": _iso(worker.last_seen_at),
        },
        "consents": [_consent_out(c).model_dump(mode="json") for c in consents],
        "assignments": [{
            "id": a.id, "task_id": a.task_id,
            "task_title": tasks[a.task_id].title if a.task_id in tasks else "",
            "assigned_date": _iso(a.assigned_date), "status": a.status,
            "scheduled_day": a.scheduled_day.isoformat() if a.scheduled_day else None,
            "task_version_no": version_nos.get(a.task_version_id),
        } for a in assignments],
        "performance_logs": [{
            "assignment_id": log.assignment_id, "step_id": log.step_id,
            "step_order": steps[log.step_id].order_index if log.step_id in steps else None,
            "sentence": steps[log.step_id].sentence if log.step_id in steps else "",
            "completed_at": _iso(log.completed_at), "duration_sec": log.duration_sec,
            "replay_count": log.replay_count, "stuck": bool(log.stuck),
            "completed": bool(log.completed),
        } for log in logs],
        "help_requests": [{
            "assignment_id": h.assignment_id,
            "step_order": steps[h.step_id].order_index if h.step_id in steps else None,
            "state": h.state, "resolution": h.resolution,
            "created_at": _iso(h.created_at), "acknowledged_at": _iso(h.acknowledged_at),
            "cancelled_at": _iso(h.cancelled_at), "resolved_at": _iso(h.resolved_at),
        } for h in helps],
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
    (2a-0) 배정의 '그 날'은 scheduled_day(그 일을 하는 날)다. 내일로 보낸 일은 내일 날짜에 보인다.
    """
    _owned_worker(worker_id, user["sub"], db)
    record_access(db, request, user, "worker.history", worker_id)
    assignment_query = select(Assignment).where(Assignment.worker_id == worker_id)
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=422, detail="날짜를 다시 골라 주세요.") from None
        assignment_query = assignment_query.where(Assignment.scheduled_day == day)
    task_ids = list({a.task_id for a in db.scalars(assignment_query).all()})
    if not task_ids:
        return []
    tasks = db.scalars(
        select(Task).where(Task.id.in_(task_ids)).order_by(Task.created_at.desc())
    ).all()
    return [
        TaskSummaryOut(id=t.id, title=t.title, status=t.status, created_at=t.created_at,
                       archived=send._is_archived(t))
        for t in tasks
    ]


@app.get("/api/workers/{worker_id}/active-dates", response_model=list[str])
def worker_active_dates(worker_id: str, request: Request, db: Session = Depends(get_db),
                        user: dict = Depends(require_employer)) -> list[str]:
    """근로자에게 배정이 있는 날짜(YYYY-MM-DD) 목록. 달력에서 활동일 표시용."""
    _owned_worker(worker_id, user["sub"], db)
    record_access(db, request, user, "worker.history", worker_id)
    rows = db.scalars(
        select(Assignment.scheduled_day).where(Assignment.worker_id == worker_id).distinct()
    ).all()
    return sorted({r.isoformat() for r in rows if r})


# (2d) 근로자 지우기는 POST /api/workers/{id}/delete(이름 다시 적기, workers_admin.py). 옛 DELETE는 옛 화면과 함께 지웠다.


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


def _decompose_inputs(db: Session, payload: TaskCreate, employer_id: str):
    """AI 하네스로 보낼 원문·맥락(근로자 실명은 별칭으로)과 되돌릴 masker를 만든다.

    AI 하네스는 이 글을 해외 LLM과 임베딩 API로 보낸다. 응답(제목·문장)은 masker로 실명으로 되돌려 저장·표시한다 —
    근로자 화면과 음성은 사업주가 쓴 그대로여야 한다.
    """
    target = _owned_worker(payload.worker_id, employer_id, db) if payload.worker_id else None
    masker = employer_pseudonymizer(db, employer_id)
    raw_masked = masker.mask(payload.raw_input)
    context = {
        "business_type": masker.mask(payload.business_type or ""),
        "work_environment": masker.mask(payload.work_environment or ""),
        "worker_note": masker.mask(_sendable_note(db, target, payload.worker_note)),
        # _task_context()와 같은 이유로 넣는다 — 업종 미입력 시 직무 추론의 보조 신호.
        "raw_input": raw_masked,
    }
    return masker, raw_masked, context


def _decompose_or_502(raw_masked: str, context: dict) -> dict:
    try:
        return ai_client.decompose(raw_masked, context)
    except Exception:  # noqa: BLE001 - AI 하네스 장애는 502로 전달한다
        # 예외 원문(내부 호스트명·연결 오류 등)은 사용자 화면에 나가면 안 된다. 로그에만 남긴다.
        logger.exception("직무 분해 호출 실패")
        raise HTTPException(status_code=502,
                            detail="직무를 단계로 나누지 못했습니다. 잠시 뒤 다시 시도해 주세요.")


def _split_fields(step: dict, masker) -> dict:
    """AI 분해 응답의 나누기 정보(split_group·split_check·source_text)를 모양을 확인해 옮긴다.
    AI 하네스가 아직 이 칸을 안 주거나 모양이 다르면 '확실·원문 그대로'로 본다."""
    group = step.get("split_group")
    source = step.get("source_text")
    return {
        "split_group": group if isinstance(group, int) and not isinstance(group, bool) else None,
        "split_check": step.get("split_check") is True,
        "source_text": masker.unmask(source) if isinstance(source, str) and source.strip() else None,
    }


def _step_terms(step: dict) -> list:
    """AI 분해 응답 단계의 그림 검색어(symbol_query, 없으면 keywords의 term)."""
    query = step.get("symbol_query") or [k.get("term") for k in step.get("keywords") or []
                                         if isinstance(k, dict)]
    return [str(t) for t in query if str(t or "").strip()]


@app.post("/api/tasks/split-preview", response_model=SplitPreviewOut)
def split_preview(payload: TaskCreate, db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> SplitPreviewOut:
    """입력 화면의 [단계로 나누기] — 직무를 만들지 않고 나눈 결과만 돌려준다(한 줄 = 한 동작 = 그림 1장).

    사업주가 이 목록을 그 자리에서 고치고 [이대로 그림 고르기]를 누르면 POST /api/tasks에 steps로 보내
    그때 초안을 만든다. 그림 검색·음성 합성은 여기서 하지 않는다(확인 전에 비용을 쓰지 않는다).
    """
    if not take_ai_split_call(user["sub"]):
        raise HTTPException(status_code=429, detail="나누기를 너무 자주 눌렀어요. 1분 뒤에 다시 눌러 주세요.")
    masker, raw_masked, context = _decompose_inputs(db, payload, user["sub"])
    decomposed = _decompose_or_502(raw_masked, context)
    steps: list[SplitPreviewStep] = []
    for step in decomposed.get("steps") or []:
        if not isinstance(step, dict):
            continue
        sentence = str(step.get("sentence") or "").strip()
        if not sentence:
            continue
        steps.append(SplitPreviewStep(
            order=len(steps) + 1,
            sentence=masker.unmask(sentence),
            action_type=str(step.get("action_type") or "other")[:20],
            symbol_query=[masker.unmask(t) for t in _step_terms(step)][:8],
            **_split_fields(step, masker),
        ))
    if len(steps) > MAX_CONFIRMED_STEPS:
        # 확인하면 반드시 실패하는 목록을 보여 주지 않는다(GPT가 안 될 때 쓰는 규칙 경로는 단계 수를 자르지 않는다).
        raise HTTPException(status_code=422, detail=(
            f"단계가 {len(steps)}개로 나뉘었어요. 한 직무는 {MAX_CONFIRMED_STEPS}단계까지예요. "
            "직무를 둘로 나눠 입력해 주세요."))
    return SplitPreviewOut(task_title=masker.unmask(str(decomposed.get("task_title") or "직무")),
                           job=str(decomposed.get("job") or "").strip(), steps=steps)


@app.post("/api/tasks", response_model=TaskOut, status_code=201)
def create_task(payload: TaskCreate, db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> TaskOut:
    masker, raw_masked, context = _decompose_inputs(db, payload, user["sub"])
    # 그림 검색에는 메모가 필요 없다. 검색 질의도 임베딩 API로 나갈 수 있으므로 빼고 보낸다.
    symbol_context = {k: v for k, v in context.items() if k != "worker_note"}
    if payload.steps:
        # 입력 화면에서 사업주가 확인한 단계 — 다시 나누지 않는다(AI 분해 호출 없음).
        # 아래 prepare()가 그림 검색에는 별칭 문장을, 저장·음성에는 실명 문장을 쓰므로 여기서 별칭으로 바꿔 둔다.
        decomposed = {
            "task_title": masker.mask((payload.title or "").strip() or "직무"),
            "job": (payload.job or "").strip(),
            "steps": [
                {
                    "order": i,
                    "sentence": masker.mask(cs.sentence),
                    # 보내지 않은 줄(고친·합친·새 줄)은 규칙 분류기로 매긴다(LLM 없음). 실패하면 other.
                    "action_type": cs.action_type or ai_client.classify_action(masker.mask(cs.sentence)),
                    "symbol_query": masker.mask_obj(
                        cs.symbol_query or re.findall(r"[가-힣A-Za-z]+", cs.sentence)[:4]),
                }
                for i, cs in enumerate(payload.steps, start=1)
            ],
        }
    else:
        decomposed = _decompose_or_502(raw_masked, context)

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
        TaskSummaryOut(id=t.id, title=t.title, status=t.status, created_at=t.created_at,
                       archived=send._is_archived(t))
        for t in tasks
    ]


@app.get("/api/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: str, db: Session = Depends(get_db),
             user: dict = Depends(require_employer)) -> TaskOut:
    return _task_out(_owned_task(task_id, user["sub"], db))


@app.delete("/api/tasks/{task_id}")
def delete_task(task_id: str, db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> dict:
    """직무를 삭제한다. 단계는 cascade로 함께 지워지고, 배정/수행 로그/도움 요청/버전은 명시적으로 정리한다
    (contract §1.7: 버전, 버전 단계, 배정, 로그, 도움, 미디어 참조).

    (2a-1) 보관함으로 옮긴 직무만 지운다(409). 기록까지 사라지는 일이라 한 번 더 거치게 한다.
    보관은 새로 보내기만 막고 이미 받은 배정은 남긴다(근로자 오늘 할 일에도 그대로). 완전히 지우면 배정·기록도 지운다.
    응답 모양({ok: true})은 그대로다."""
    task = _owned_task(task_id, user["sub"], db)
    if not send._is_archived(task):
        raise HTTPException(status_code=409, detail="보관함으로 옮긴 직무만 완전히 지울 수 있어요.")
    assignment_ids = [a.id for a in db.scalars(
        select(Assignment).where(Assignment.task_id == task_id)
    ).all()]
    if assignment_ids:
        db.execute(delete(HelpRequest).where(HelpRequest.assignment_id.in_(assignment_ids)))
        db.execute(delete(PerformanceLog).where(PerformanceLog.assignment_id.in_(assignment_ids)))
        db.execute(delete(Assignment).where(Assignment.task_id == task_id))
    version_ids = list(db.scalars(select(TaskVersion.id).where(TaskVersion.task_id == task_id)).all())
    version_steps = (db.scalars(select(TaskVersionStep).where(TaskVersionStep.version_id.in_(version_ids))).all()
                     if version_ids else [])
    media_ids = _step_media_ids(task.steps) + _step_media_ids(version_steps)
    if version_ids:
        db.execute(delete(TaskVersionStep).where(TaskVersionStep.version_id.in_(version_ids)))
        db.execute(delete(TaskVersion).where(TaskVersion.id.in_(version_ids)))
    db.delete(task)  # Step은 Task.steps의 cascade="all, delete-orphan"으로 함께 삭제됨
    db.commit()
    # 직무의 사진은 바로, TTS 레코드는 바로(파일은 GC 유예 뒤) 지운다. 다른 직무가 같은 사진을 쓰면 남는다.
    media.release(db, media_ids)
    return {"ok": True}


@app.post("/api/tasks/{task_id}/steps", response_model=StepAddOut, status_code=201)
def add_step(task_id: str, payload: StepCreate, db: Session = Depends(get_db),
             user: dict = Depends(require_employer)) -> StepAddOut:
    """검토 화면에서 사업주가 단계를 직접 추가한다.

    맨 끝에 붙이며(순서는 이후 드래그로 조정), 상징/TTS는 서버가 생성한다.
    LLM symbol_query가 없으므로 문장에서 한글/영문 단어를 뽑아 상징 후보로 쓴다.
    새 문장에 동작이 둘이면(초안일 때만) 문장 고치기와 같이 경고 없이 두 단계로 나눠 넣고 split_step_ids를
    돌려준다 — 화면이 [되돌리기]를 띄운다(한 단계 = 한 동작 = 그림 1장, 설계 5.5).
    """
    task = _owned_task(task_id, user["sub"], db)
    sentence = payload.sentence.strip()
    action_type = payload.action_type or "other"
    next_order = max((s.order_index for s in task.steps), default=0) + 1
    parts = _detect_split(db, task, user["sub"], sentence) if task.status != "published" else []
    prepared = ([_prepare_new_step(db, task, user["sub"], part["sentence"], part["action_type"], part["terms"])
                 for part in parts]
                or [_prepare_new_step(db, task, user["sub"], sentence, action_type)])
    new_steps = [_insert_step(db, task, user["sub"], prep, next_order + i) for i, prep in enumerate(prepared)]
    db.commit()
    db.refresh(task)
    out = _task_out(task)
    return StepAddOut(**out.model_dump(), sentence=sentence,
                      split_step_ids=[s.id for s in new_steps] if parts else [])


def _prepare_new_step(db: Session, task: Task, employer_id: str, sentence: str,
                      action_type: str = "other", terms: list[str] | None = None,
                      photo_media_id: str | None = None) -> dict:
    """사업주가 쓴 문장의 그림·음성을 준비한다(네트워크 호출만, DB는 건드리지 않는다).

    직무 생성 때와 같은 맥락으로 검색해야 나중에 만든 단계만 다른 그림이 붙지 않는다.
    검색어·맥락은 AI 하네스(→ 임베딩 API)로 가므로 근로자 실명을 별칭으로 바꿔 보낸다.
    terms(AI가 준 검색어)가 있으면 저장해 두고 후보 재조회도 같은 질의로 한다. 없으면 문장에서 뽑는다.
    add_step·rewrite_step·merge_steps가 함께 쓴다.
    photo_media_id: 원래 단계에 사업주가 올린 사진 — 그림을 새로 찾지 않고 그 사진을 그대로 붙인다
    (나누거나 되돌릴 때 사진이 사라지지 않게).
    """
    query = [t for t in (terms or []) if str(t).strip()][:4]
    if photo_media_id:
        sym = {"photo_media_id": photo_media_id, "source": "photo", "needs_fallback": False}
    else:
        search = query or re.findall(r"[가-힣A-Za-z]+", sentence) or [sentence[:12]]
        masker = employer_pseudonymizer(db, employer_id)
        sym = _pick_symbol(masker.mask_obj(search[:4]),
                           context=masker.mask_obj(_task_context(task, sentence, action_type)))
    return {"sentence": sentence, "action_type": action_type, "sym": sym,
            "symbol_query": ",".join(str(t).strip() for t in query),
            "tts": synthesize_tts(sentence, employer_id)}


def _insert_step(db: Session, task: Task, employer_id: str, prepared: dict, order_index: int) -> Step:
    sym = prepared["sym"]
    step = Step(
        task_id=task.id, order_index=order_index, sentence=prepared["sentence"],
        action_type=prepared["action_type"],
        symbol_query=prepared.get("symbol_query") or "",
        symbol_url=None if sym.get("photo_media_id") else sym.get("image_url"),
        symbol_media_id=sym.get("photo_media_id"),
        symbol_source=sym.get("source", "fallback"),
        needs_fallback=sym.get("needs_fallback", True),
        # 사업주가 올린 사진을 합치기·나누기로 새 단계에 옮기면 그대로 '확인함'이다(명세 §5.5). 빠뜨리면
        # 확인 안 한 자동 그림(auto_high)이 되어 보낸 직무를 고친 뒤 다시 보내기가 422로 막혔다(1회차 검증).
        picture_confirmed=bool(sym.get("photo_media_id")),
        tts_media_id=_tts_media_id(db, employer_id, prepared["tts"]),
    )
    db.add(step)
    return step


def _replace_steps(db: Session, task: Task, employer_id: str, old: list[Step],
                   prepared: list[dict]) -> tuple[list[Step], list[str]]:
    """연속한 단계들(old)을 새 단계들로 같은 자리에서 바꾸고 순서를 1..N으로 다시 매긴다(커밋은 부르는 쪽).
    놓아줄 사진·음성 레코드 id를 돌려준다(커밋 뒤 media.release). 새 단계로 넘긴 사진(prepared의 photo_media_id)은
    놓아주지 않는다. (2a-0) 수행 로그·도움은 버전 단계를 가리키므로 지우지 않는다(편집으로 기록이 사라지지 않는다)."""
    position = min(s.order_index for s in old)
    ids = {s.id for s in old}
    others = sorted((s for s in task.steps if s.id not in ids), key=lambda s: s.order_index)
    kept = {p["sym"].get("photo_media_id") for p in prepared} - {None}
    media_ids = [m for m in _step_media_ids(old) if m not in kept]
    for s in old:
        db.delete(s)
    db.flush()
    new_steps = [_insert_step(db, task, employer_id, p, 0) for p in prepared]
    ordered = ([s for s in others if s.order_index < position] + new_steps
               + [s for s in others if s.order_index > position])
    for i, s in enumerate(ordered, start=1):
        s.order_index = i
    db.flush()
    return new_steps, media_ids


# 편집기 저장 시 나누기 확인의 AI 시간 제한(초). 저장을 오래 붙잡지 않게 직무 생성(AI_TIMEOUT)보다 짧다.
_SPLIT_CHECK_TIMEOUT = float(os.getenv("AI_SPLIT_CHECK_TIMEOUT", "8"))
# 동작이 둘일 수 있는 겉모양: 쉼표·순서 접속어, 또는 마지막이 아닌 어절의 연결 꼴(-고·-서·-며·-다가), '-어' 꼴
# (집어·올려·꺼내), '-(으)ㄴ 다음/후/뒤'. 하나도 없으면 동작 하나다("컵을 깨끗이 닦으세요") — GPT를 부르지 않는다.
_SPLIT_HINT_RE = re.compile(r"[,，]|그리고|그다음|그 다음")
_CONNECTIVE_TAIL_RE = re.compile(
    r"(?:고|서|며|면서|다가|다음|다음에|후|후에|뒤|뒤에)$|[아어여워와해봐줘놔둬려겨켜쳐혀펴껴내빼대새개매]$")


def _may_have_two_actions(sentence: str) -> bool:
    if _SPLIT_HINT_RE.search(sentence):
        return True
    words = re.findall(r"[가-힣A-Za-z0-9]+", sentence)
    return any(_CONNECTIVE_TAIL_RE.search(w) for w in words[:-1])


# 편집기에서 고친 문장 하나를 나눌 때 받아들이는 최대 단계 수. 이보다 많으면 문장이 아니라 직무 하나를
# 통째로 적은 것이라 저장하며 몰래 나누지 않는다(그대로 저장하고 사업주가 단계 추가로 나눈다).
_MAX_REWRITE_PARTS = 4


def _detect_split(db: Session, task: Task, employer_id: str, sentence: str) -> list[dict]:
    """고친 문장 하나를 AI 분해에 다시 넣어 동작이 둘 이상인지 본다. 확실히 나눈 경우에만 나눈 단계를 돌려준다.

    - AI가 '애매하다'(split_check)고 한 줄이 하나라도 있으면 나누지 않는다. GPT는 한 동작 문장도 나누는
      경향이 있어(개발셋 한 단계 문장 92개 중 30개), 확실한 것만 저장하는 순간 나눈다. 틀려도 [되돌리기]가 있다.
    - AI 하네스 장애·시간 초과(_SPLIT_CHECK_TIMEOUT)면 나누지 않고 그대로 저장한다(편집을 막지 않는다).
    - 동작이 하나뿐인 문장은 AI 분해(GPT)를 부르지 않는다 — 오타 고치기마다 GPT를 부르면 저장이 느리고 비용이
      든다. 먼저 AI 하네스의 규칙 동작 세기(/ai/split-hint, LLM 없음)에 묻고, 하네스가 답하지 못하면 겉모양 검사
      (_may_have_two_actions)로 대신한다. 겉모양 검사만 쓰면 '냉장고 문을 닫으세요'처럼 명사 끝 글자에도 걸렸다(2차 검증).
      사업주별 호출 한도(ratelimit.ai_split_throttle)를 넘어도 부르지 않는다.
    - 근로자 특성 메모는 보내지 않는다. 문장·맥락의 근로자 실명은 별칭으로 바꿔 보낸다.
    """
    masker = employer_pseudonymizer(db, employer_id)
    masked = masker.mask(sentence)
    hint = ai_client.split_hint(masked)
    if hint is None:
        hint = _may_have_two_actions(sentence)
    if not hint or not take_ai_split_call(employer_id):
        return []
    context = {
        "business_type": masker.mask(task.business_type or ""),
        "work_environment": masker.mask(task.work_environment or ""),
        "worker_note": "",
        "raw_input": masked,
    }
    try:
        result = ai_client.decompose(masked, context, timeout=_SPLIT_CHECK_TIMEOUT)
    except Exception:  # noqa: BLE001
        logger.warning("편집 문장 나누기 확인 실패 — 나누지 않고 저장한다", exc_info=True)
        return []
    steps = [st for st in result.get("steps") or []
             if isinstance(st, dict) and str(st.get("sentence") or "").strip()]
    if not 2 <= len(steps) <= _MAX_REWRITE_PARTS or any(st.get("split_check") is True for st in steps):
        return []
    return [{
        "sentence": masker.unmask(str(st["sentence"]).strip())[:500],
        "action_type": str(st.get("action_type") or "other")[:20],
        "terms": [masker.unmask(t) for t in _step_terms(st)][:4],
    } for st in steps]


@app.post("/api/tasks/{task_id}/steps/{step_id}/rewrite", response_model=StepRewriteOut)
def rewrite_step(task_id: str, step_id: str, payload: StepRewrite, db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> StepRewriteOut:
    """편집기에서 단계 문장을 고쳐 저장한다. 고친 문장에 동작이 둘이면 경고 대신 그 자리에서 두 단계로 나눈다.

    나눈 경우 응답의 split_step_ids로 화면이 [되돌리기]를 띄우고, 되돌리기는 POST …/steps/merge로
    사업주가 적은 문장(sentence) 한 단계로 합친다. (2a-0) 보낸 직무도 나눈다 — 근로자는 보낸 버전 단계를 보고,
    로그·도움은 버전 단계를 가리키므로 편집 단계 id가 바뀌어도 진행 기록이 끊기지 않는다.
    """
    task = _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")
    sentence = payload.sentence
    if sentence == step.sentence:
        return StepRewriteOut(task=_task_out(task), sentence=sentence)
    parts = _detect_split(db, task, user["sub"], sentence)
    if not parts:
        update_step(task_id, step_id, StepUpdate(sentence=sentence), db, user)
        db.refresh(task)
        return StepRewriteOut(task=_task_out(task), sentence=sentence)
    # 네트워크 호출(그림·음성)을 먼저 끝낸다 — SQLite 쓰기 잠금을 오래 쥐지 않게(직무 생성과 같은 이유).
    # 사업주가 올린 사진은 첫 단계로 넘긴다(지우지 않는다) — [되돌리기]하면 합친 단계로 다시 돌아온다.
    photo = step.symbol_media_id if step.symbol_source == "photo" else None
    prepared = [_prepare_new_step(db, task, user["sub"], part["sentence"], part["action_type"], part["terms"],
                                  photo_media_id=photo if i == 0 else None)
                for i, part in enumerate(parts)]
    new_steps, media_ids = _replace_steps(db, task, user["sub"], [step], prepared)
    db.commit()
    media.release(db, media_ids)
    db.refresh(task)
    return StepRewriteOut(task=_task_out(task), split_step_ids=[s.id for s in new_steps], sentence=sentence)


@app.post("/api/tasks/{task_id}/steps/merge", response_model=TaskOut)
def merge_steps(task_id: str, payload: StepMerge, db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> TaskOut:
    """이어진 단계들을 sentence 한 단계로 합친다 — 편집기에서 저장하며 나눈 것을 [되돌리기]할 때 쓴다.
    합치는 단계에 사업주가 올린 사진이 있으면 그 사진을 붙이고(나눌 때 첫 단계로 넘긴 사진이 돌아온다), 없으면
    그림은 단계 추가와 같은 방법으로 새로 찾는다. 동작 종류는 화면이 기억한 나누기 전 값(action_type)을 쓰고, 없으면
    규칙 분류기(classify_action)로 매긴다.
    (2a-0) 보낸 직무도 합친다(예전 409 해제) — 근로자는 보낸 버전을 보고, 로그·도움은 버전 단계를 가리킨다.
    바뀐 내용은 다음 보내기부터 나간다."""
    task = _owned_task(task_id, user["sub"], db)
    if len(set(payload.step_ids)) != len(payload.step_ids):
        raise HTTPException(status_code=400, detail="같은 단계가 두 번 들어 있습니다.")
    by_id = {s.id: s for s in task.steps}
    if any(sid not in by_id for sid in payload.step_ids):
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")
    run = sorted((by_id[sid] for sid in payload.step_ids), key=lambda s: s.order_index)
    orders = [s.order_index for s in run]
    if orders != list(range(orders[0], orders[0] + len(orders))):
        raise HTTPException(status_code=409, detail="합칠 단계가 붙어 있지 않습니다. 순서가 바뀌었는지 확인해 주세요.")
    photo = next((s.symbol_media_id for s in run if s.symbol_source == "photo" and s.symbol_media_id), None)
    # 화면이 나누기 전 동작 종류를 모르면(단계 추가를 되돌림) 문장 고치기와 같은 규칙 분류기로 다시 매긴다.
    action_type = payload.action_type or ai_client.classify_action(
        employer_pseudonymizer(db, user["sub"]).mask(payload.sentence))
    prepared = [_prepare_new_step(db, task, user["sub"], payload.sentence, action_type, photo_media_id=photo)]
    _, media_ids = _replace_steps(db, task, user["sub"], run, prepared)
    db.commit()
    media.release(db, media_ids)
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
        # 사업주가 후보를 고르거나 검색 결과를 붙였다 = 이 그림을 확인했다.
        step.picture_confirmed = True
    if payload.sentence is not None:
        step_sentence_before = step.sentence
        step.sentence = payload.sentence
        if step.tts_media_id:
            released.append(step.tts_media_id)
        step.tts_media_id = _tts_media_id(db, user["sub"], synthesize_tts(payload.sentence, user["sub"]))
        # 저장된 symbol_query는 옛 문장에 묶여 있다. 비우면 후보 조회가 새 문장에서
        # 검색어를 다시 뽑는다.
        step.symbol_query = ""
        # 동작 계열도 옛 문장의 것이다("상자를 옮기세요"→move를 "바닥을 쓸어주세요"로 고쳐도 move로 남았다).
        # 남겨 두면 후보 재검색이 맞는 그림을 계열 불일치로 깎고, 화면에 틀린 꼬리표가 붙는다. 새 문장으로
        # 직무 분해와 같은 규칙 분류기(AI 하네스 /ai/classify-action, LLM 없음)에 다시 매긴다. 하네스가 죽어 있으면
        # other(벌점 없음·꼬리표 숨김)다. 하네스로 보내는 글은 직무 생성과 같이 근로자 실명을 별칭으로 바꾼다.
        if payload.sentence != step_sentence_before:
            masker = employer_pseudonymizer(db, user["sub"])
            step.action_type = ai_client.classify_action(masker.mask(payload.sentence))
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
        step.picture_confirmed = False
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
    """단계를 삭제하고 남은 단계의 순서를 1부터 다시 매긴다.

    (2a-0) 수행 로그·도움 요청은 지우거나 끊지 않는다 — 버전 단계를 가리키므로 편집 단계를 지워도 기록은 남고,
    지금 하는 근로자는 보낸 버전 그대로 끝까지 한다(결정 5).
    """
    task = _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")
    if len(task.steps) <= 1:
        raise HTTPException(
            status_code=400,
            detail="마지막 단계는 삭제할 수 없습니다. 직무 자체를 삭제하려면 대시보드를 이용하세요.",
        )
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


def _ensure_sendable(task: Task) -> None:
    """보내기 검사(send.ensure_sendable)와 같다: 단계 없음·그림 없음·확인 안 한 자동 그림이면 422(code·step_ids)."""
    send.ensure_sendable(task)


@app.post("/api/tasks/{task_id}/publish", response_model=TaskOut)
def publish_task(task_id: str, db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> TaskOut:
    """직무를 근로자에게 보낼 수 있게 한다(0차 7번: 그림 없는 단계가 있으면 막는다).

    창업자 결정 9: 단계마다 그림 1장. 그림 없는 단계가 근로자 화면에 빈 칸으로 나가면 그 단계를 따라 할 수 없다.
    이미 보낸 직무를 다시 보낼 때도 같은 검사를 한다(보낸 뒤 사진을 지운 경우).
    (2a-0) send-check와 같은 검사다: 확인 안 한 자동 그림(auto_high·choose)도 막는다(422, code·step_ids).
    """
    task = _owned_task(task_id, user["sub"], db)
    _ensure_sendable(task)
    task.status = "published"
    db.commit()
    db.refresh(task)
    return _task_out(task)


@app.post("/api/tasks/{task_id}/steps/{step_id}/picture/confirm", response_model=StepOut)
def confirm_step_picture(task_id: str, step_id: str, db: Session = Depends(get_db),
                         user: dict = Depends(require_employer)) -> StepOut:
    """자동으로 붙은 그림을 사업주가 보고 "이 그림이 맞다"고 확인한다(그림 4상태의 '확인함'). 2차 편집기용."""
    _owned_task(task_id, user["sub"], db)
    step = db.get(Step, step_id)
    if step is None or step.task_id != task_id:
        raise HTTPException(status_code=404, detail="단계를 찾을 수 없습니다.")
    if picture_state(step) == "none":
        raise HTTPException(status_code=422,
                            detail="그림이 없는 단계는 확인할 수 없어요. 먼저 그림을 골라 주세요.")
    step.picture_confirmed = True
    db.commit()
    db.refresh(step)
    return _step_to_out(step)


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
def assign_task(task_id: str, request: Request, payload: AssignRequest = AssignRequest(),
                db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> list[AssignmentOut]:
    """옛 사업주 화면의 배정. (2a-0) 안에서 보내기와 같은 함수(send.send_to_workers, day=today)를 쓴다 — 같은 검사,
    같은 버전 고정, 같은 배정 규칙. 응답 모양은 그대로(근로자마다 배정 하나)."""
    task = _owned_task(task_id, user["sub"], db)
    if send._is_archived(task):
        # (2a-1) 보관한 직무는 보내기와 같은 409(code archived). '게시된 직무만' 400보다 먼저 본다.
        raise send.ApiError(409, send.MSG_ARCHIVED, code="archived", step_ids=[])
    if task.status != "published":
        raise HTTPException(status_code=400, detail="게시된 직무만 배정할 수 있습니다.")
    _ensure_sendable(task)

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

    _, assignments = send.send_to_workers(db, request, user, task, worker_ids, "today")
    return [AssignmentOut(id=a.id, task_id=a.task_id, worker_id=a.worker_id, status=a.status)
            for a in assignments]


# --- 근로자: 내 정보·화면 설정 ---
@app.get("/api/worker/me", response_model=WorkerMeOut)
def worker_me(db: Session = Depends(get_db),
              user: dict = Depends(current_worker)) -> WorkerMeOut:
    """근로자 화면이 시작할 때 부르는 내 정보(이름·사업장 이름·호칭·화면 설정)."""
    worker = db.get(Worker, user["sub"])
    employer = db.get(Employer, worker.employer_id)
    return WorkerMeOut(
        id=worker.id, display_name=worker.display_name,
        workplace_name=(employer.org_name or employer.name) if employer is not None else "",
        # 창업자 결정 1의 기본 '선생님'. (2d) 사업장 설정 호칭(employers.teacher_title).
        teacher_title=workers_admin.teacher_title_of(employer),
        a11y_prefs=parse_a11y_prefs(worker.a11y_prefs),
    )


ACTIVE_HELP_STATES = ("open", "acknowledged")
# 오늘 할 일 폴링마다 쓰지 않도록, 마지막 조회 시각은 이 간격보다 오래됐을 때만 갱신한다(SQLite 쓰기 줄이기).
_LAST_SEEN_MIN_INTERVAL = timedelta(seconds=30)


def _touch_last_seen(db: Session, worker_id: str) -> None:
    worker = db.get(Worker, worker_id)
    if worker is None:
        return
    now = _utcnow()
    last = _naive_utc(worker.last_seen_at)
    if last is not None and now - last < _LAST_SEEN_MIN_INTERVAL:
        return
    worker.last_seen_at = now
    db.commit()


def _active_help(db: Session, assignment_id: str) -> HelpRequest | None:
    return db.scalar(
        select(HelpRequest).where(HelpRequest.assignment_id == assignment_id,
                                  HelpRequest.state.in_(ACTIVE_HELP_STATES))
        .order_by(HelpRequest.created_at.desc()).limit(1)
    )


# --- 근로자: 오늘의 카드 ---
@app.get("/api/worker/me/today", response_model=list[TodayCardOut])
def worker_today(include_done: bool = False, db: Session = Depends(get_db),
                 user: dict = Depends(current_worker)) -> list[TodayCardOut]:
    """오늘 받은 일. 사업주가 보낸 순서(창업자 결정 7)대로, 카드마다 이어서 하기 정보를 붙인다.

    include_done=false(기본)는 예전처럼 끝낸 일을 뺀다. 새 근로자 화면은 true로 불러 끝낸 일도 아래에 보여 준다.
    (2a-0, 결정 5) '오늘'은 배정의 scheduled_day == 현지 오늘이다(내일로 보낸 일은 내일 뜬다). 단계는 배정에 고정된
    버전 단계다 — 사업주가 보낸 직무를 고쳐도 지금 하는 근로자의 화면·진행은 그대로이고, 다음 배정부터 바뀐다.
    처음 돌려주는 배정에는 first_seen_at을 한 번 쓴다(다시 보내기가 이미 받은 배정을 옮기지 않게).
    """
    _touch_last_seen(db, user["sub"])
    today = clock.local_today()
    base = [Assignment.worker_id == user["sub"], Assignment.scheduled_day == today]
    if db.scalar(select(Assignment.id).where(*base, Assignment.first_seen_at.is_(None)).limit(1)) is not None:
        # 받은 시각을 먼저 쓰고(쓰기 잠금을 잡음) 같은 트랜잭션에서 읽는다. 보내기(send)가 그사이 이 배정을
        # 새 버전으로 옮기면, 근로자는 옛 단계 id를 받고 서버는 새 버전을 가리켜 완료 기록이 400으로 버려진다.
        db.execute(update(Assignment).where(*base, Assignment.first_seen_at.is_(None))
                   .values(first_seen_at=clock.utcnow()).execution_options(synchronize_session=False))
        db.expire_all()
    query = select(Assignment).where(*base)
    if not include_done:
        query = query.where(Assignment.status != "done")
    assignments = db.scalars(query.order_by(Assignment.assigned_date, Assignment.id)).all()
    out: list[TodayCardOut] = []
    next_marked = False
    for a in assignments:
        task = db.get(Task, a.task_id)
        if task is None:
            continue
        version = versions.assignment_version(db, a)
        logs = db.scalars(select(PerformanceLog).where(PerformanceLog.assignment_id == a.id,
                                                       PerformanceLog.completed.is_(True))).all()
        done_set = {log.step_id for log in logs}
        steps = versions.assignment_steps(db, a, task)
        done_step_ids = [s.id for s in steps if s.id in done_set]
        resume = next((i for i, s in enumerate(steps) if s.id not in done_set), len(steps))
        if a.status == "done":
            status = "done"
        elif done_step_ids:
            status = "in_progress"
        else:
            status = "new"
        is_next = status != "done" and not next_marked
        next_marked = next_marked or is_next
        completed_at = None
        if status == "done" and logs:
            completed_at = max(_naive_utc(log.completed_at) for log in logs)
        help_row = _active_help(db, a.id)
        out.append(TodayCardOut(
            assignment_id=a.id, task_id=task.id,
            task_title=version.title if version is not None else task.title,
            steps=[versions.worker_step_out(s) for s in steps],
            status=status, done_step_ids=done_step_ids, resume_step_index=resume,
            is_next=is_next, assigned_at=_naive_utc(a.assigned_date), completed_at=completed_at,
            active_help=(ActiveHelpOut(id=help_row.id, state=help_row.state, step_id=help_row.step_id,
                                       created_at=help_row.created_at)
                         if help_row is not None else None),
            task_version_no=version.version_no if version is not None else None,
        ))
    db.commit()
    return out


@app.get("/api/worker/me/history", response_model=list[HistoryCardOut])
def worker_history(db: Session = Depends(get_db),
                   user: dict = Depends(current_worker)) -> list[HistoryCardOut]:
    """근로자 본인이 받았던 일을 전부 최신순으로 돌려준다(오늘 것 포함).

    /api/worker/me/today는 완료된 배정을 목록에서 뺀다(다음 일에 집중하게 하려는 설계)
    — 그 결과 근로자가 끝낸 일을 다시 열어 볼 방법이 없었다. 이 API로 지난 단계별
    그림·문장을 다시 볼 수 있다(완료 처리는 하지 않는 읽기 전용 복습 용도).
    (2a-0) 단계는 배정의 버전 단계, 날짜는 scheduled_day다. 아직 오지 않은 날(내일로 보낸 일)은 빼다.
    """
    assignments = db.scalars(
        select(Assignment)
        .where(Assignment.worker_id == user["sub"], Assignment.scheduled_day <= clock.local_today())
        # 날짜 칸이 scheduled_day이므로 그 날짜로 먼저 묶고(최신 날 먼저), 같은 날 안에서는 늦게 보낸 순서.
        # assigned_date(보낸 시각)로만 정렬하면 미리 보낸 일과 그날 보낸 일이 섞여 날짜 묶음이 갈렸다(2회차 검증).
        .order_by(Assignment.scheduled_day.desc(), Assignment.assigned_date.desc(), Assignment.id.desc())
    ).all()
    out: list[HistoryCardOut] = []
    for a in assignments:
        task = db.get(Task, a.task_id)
        if task is None:
            continue
        version = versions.assignment_version(db, a)
        # 어려움 신호만 남긴 기록(completed=false)은 '한 단계'로 세지 않는다.
        completed_step_ids = set(db.scalars(
            select(PerformanceLog.step_id).where(PerformanceLog.assignment_id == a.id,
                                                 PerformanceLog.completed.is_(True))
        ).all())
        out.append(HistoryCardOut(
            assignment_id=a.id, task_id=task.id,
            task_title=version.title if version is not None else task.title,
            assigned_date=a.scheduled_day.isoformat(),
            status=a.status,
            steps=[
                HistoryStepOut(**versions.worker_step_out(s).model_dump(),
                               completed=s.id in completed_step_ids)
                for s in versions.assignment_steps(db, a, task)
            ],
            task_version_no=version.version_no if version is not None else None,
        ))
    return out


# --- 근로자: 단계 완료 로그(업서트) ---
# 기기 시각이 서버보다 이만큼 넘게 앞서면 믿지 않는다(시계가 틀린 기기).
_CLIENT_CLOCK_SKEW = timedelta(minutes=5)
# 완료 기록이 '몇 초 전에 끝냈다'고 말할 수 있는 가장 긴 시간(_completed_at_server_clock). 넘으면 하루 전으로 본다.
_COMPLETED_AT_MAX_AGE = timedelta(days=1)


def _completed_at_server_clock(payload: PerformanceLogCreate, now: datetime) -> datetime:
    """이 단계를 끝낸 순간을 서버 시계로 옮긴다(늦게 닿은 완료 기록이 어느 도움 요청까지 닫을지 정할 때 쓴다).

    4차 검증: 예전 기준 max(기기 완료 시각, now - 60초)는 기기 시각과 서버 시각을 그대로 비교해서 (1) 기기 시계가
    늦으면 방금 누른 [다 했어요]가 도움을 닫지 못했고 (2) 기록이 60초 넘게 늦게 닿으면 완료 뒤에 부른 도움도 닫았다.
    이제 '보낸 시각 - 끝낸 시각'(둘 다 같은 기기 시계)만큼 서버 수신 시각에서 뺀다. 시계가 틀려도 차이는 맞다.
    """
    done = payload.client_completed_at
    sent = payload.client_sent_at
    if done is None:
        return now
    if sent is None:
        # 보낸 시각이 없는 옛 기기: 기기 완료 시각을 그대로 쓴다(시계 차이는 보정하지 못한다).
        return _clamp_client_time(done, now, None)
    elapsed = _naive_utc(sent) - _naive_utc(done)
    if elapsed < timedelta(0):
        # 끝낸 뒤 기기 시계가 뒤로 갔다(시각 맞춤 등). 순서를 알 수 없으니 방금 끝낸 것으로 본다.
        return now
    # 4차 검증 2회: 차이가 터무니없이 크면(기기 시계를 끝낸 뒤 고쳤거나 일부러 만든 값) 날짜 계산이 넘치지 않게 자른다.
    # 하루 넘게 묵은 완료는 '오늘 부른 도움보다 앞'이라는 뜻만 있으면 된다(도움은 그날 일에서만 연다).
    return now - min(elapsed, _COMPLETED_AT_MAX_AGE)


def _clamp_client_time(value: datetime | None, now: datetime, floor: datetime | None) -> datetime:
    """기기가 보낸 완료 시각을 [배정 시각, 서버 now + 5분] 안으로 자른다. 없으면 서버 now."""
    if value is None:
        return now
    value = _naive_utc(value)
    if value > now + _CLIENT_CLOCK_SKEW:
        return now
    floor = _naive_utc(floor)
    if floor is not None and value < floor:
        return floor
    return value


@app.post("/api/performance-logs", status_code=201, response_model=LogResultOut)
def create_log(payload: PerformanceLogCreate, response: Response, db: Session = Depends(get_db),
               user: dict = Depends(current_worker)) -> LogResultOut:
    """단계 완료(또는 어려움 신호) 기록. 새로 적용하면 201, 중복·늦게 온 옛 기록은 바꾸지 않고 200.

    근로자 기기의 오프라인 대기열은 2xx면 지우고, 400·404·422는 버리고, 401·429·5xx는 다시 보낸다.

    알려진 한계: 같은 단계의 기록 순서는 기기 시각(client_completed_at)으로 정한다. 시계가 크게 늦은 기기가
    나중에 다시 한 기록은 '옛 기록'으로 보고 200으로 버린다(5분 넘게 앞선 시각만 서버 시각으로 바꾼다).
    """
    try:
        return _create_log_once(payload, response, db, user)
    except IntegrityError:
        # 두 기기가 같은 단계의 첫 기록을 동시에 보냈다: 둘 다 "기록 없음"을 보고 넣다가 하나가
        # UNIQUE(assignment_id, step_id)에 걸린다. 되돌리고 한 번 더 하면 이번에는 있는 기록을 찾아
        # 중복·옛 기록 규칙대로 처리한다(예전에는 500이었다, 1차 검증 지적).
        db.rollback()
        return _create_log_once(payload, response, db, user)


def _create_log_once(payload: PerformanceLogCreate, response: Response, db: Session,
                     user: dict) -> LogResultOut:
    a = db.get(Assignment, payload.assignment_id)
    if a is None or a.worker_id != user["sub"]:
        raise HTTPException(status_code=404, detail="배정을 찾을 수 없습니다.")

    # (2a-0) 단계 소속은 배정의 버전으로 본다(vs.version_id == a.task_version_id). 백필한 버전 1은 단계 id가
    # 원래 steps.id와 같아, 0007 이전 기기의 대기열에 남은 기록도 그대로 들어간다.
    if versions.step_of_assignment(db, a, payload.step_id) is None:
        raise HTTPException(status_code=400, detail="이 배정에 속하지 않는 단계입니다.")

    now = _utcnow()
    at = _clamp_client_time(payload.client_completed_at, now, a.assigned_date)

    # (assignment, step) 업서트: 같은 단계를 다시 끝내면 마지막 기록으로 갱신한다.
    log = db.scalar(
        select(PerformanceLog).where(
            PerformanceLog.assignment_id == a.id,
            PerformanceLog.step_id == payload.step_id,
        )
    )
    if log is not None:
        if payload.client_event_id and log.client_event_id == payload.client_event_id:
            # 대기열이 같은 기록을 다시 보냈다(응답을 못 받고 끊긴 경우 등). 한 번만 센다.
            response.status_code = 200
            return LogResultOut(assignment_status=a.status, duplicate=True, applied=False)
        if log.completed_at is not None and at < _naive_utc(log.completed_at):
            # 대기열 순서가 뒤섞여 옛 기록이 늦게 왔다. [이전]으로 돌아가 다시 한 새 값을 옛 값으로 덮지 않는다.
            response.status_code = 200
            return LogResultOut(assignment_status=a.status, duplicate=False, applied=False)
    else:
        log = PerformanceLog(assignment_id=a.id, step_id=payload.step_id, completed=False)
        db.add(log)
    log.duration_sec = payload.duration_sec
    log.replay_count = payload.replay_count
    log.stuck = payload.stuck
    log.completed_at = at
    log.client_event_id = payload.client_event_id
    # 완료는 올리기만 한다. 끝낸 단계에 나중에 어려움 신호(completed=false)가 와도 '안 함'으로 돌아가지 않는다.
    log.completed = bool(log.completed) or payload.completed

    # 완료 판정(버그 수정): 예전에는 "기록이 있는 단계 수 >= 전체 단계 수"였다. 도움 요청이 stuck 기록으로
    # 들어와 마지막 단계에서 [도와주세요]만 눌러도 '다 함'이 됐다. 이제 완료 기록(completed=true)이 배정에 고정된
    # 버전의 모든 단계를 덮을 때만 done이다(2a-0). 사업주가 그사이 단계를 지우거나 더해도 판정은 흔들리지 않는다.
    step_ids = {s.id for s in versions.assignment_steps(db, a)}
    done_ids = set(db.scalars(
        select(PerformanceLog.step_id).where(PerformanceLog.assignment_id == a.id,
                                             PerformanceLog.completed.is_(True))
    ).all())
    if log.completed:
        done_ids.add(payload.step_id)
    if step_ids and step_ids <= done_ids:
        a.status = "done"  # done → 미완료로 되돌리는 일은 없다

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
    if log.completed:
        # 근로자가 [다 했어요]를 눌렀다 = 막혔던 일을 해결했다. 열린 도움 요청을 닫는다(스펙 4.5).
        # 닫는 것은 이 단계에서 부른 요청(또는 단계 없이 부른 요청)뿐이다(2차 검증). 예전에는 배정의 열린 요청을
        # 모두 닫아서, 대기열에 남아 있던 1단계 기록이 늦게 닿으면 2단계에서 방금 부른 요청까지 말없이 닫혔다 —
        # 근로자는 '여기서 기다려요'를 보고 기다리는데 사업주 화면에서는 사라졌다. 직무를 다 끝냈으면 모두 닫는다.
        close = update(HelpRequest).where(
            HelpRequest.assignment_id == a.id, HelpRequest.state.in_(ACTIVE_HELP_STATES),
        )
        if a.status != "done":
            close = close.where(or_(HelpRequest.step_id == payload.step_id, HelpRequest.step_id.is_(None)))
            # 3차 검증: 같은 단계라도 완료보다 뒤에 부른 요청은 닫지 않는다. 대기열에 남아 있던 옛 [다 했어요] 기록이
            # 늦게 닿으면, 근로자가 [이전]으로 그 단계에 돌아와 새로 부른 요청이 말없이 닫혔다(선생님은 못 봤다).
            # 4차 검증: 비교는 서버 시계로 옮긴 완료 순간과 서버가 적은 created_at끼리 한다(_completed_at_server_clock).
            cutoff = _completed_at_server_clock(payload, now)
            close = close.where(HelpRequest.created_at <= cutoff)
        db.execute(close.values(state="resolved", resolution="step_done", resolved_at=now))
    db.commit()
    return LogResultOut(assignment_status=a.status, duplicate=False, applied=True)


# --- 도움 요청(근로자 [도와주세요] → 사업주 화면 알림 띠) ---
_HELP_NOT_FOUND = "도움 요청을 찾을 수 없습니다."
_HELP_FINISHED = "이미 끝난 도움 요청이에요."
_HELP_CANCELLED = "근로자가 이미 취소한 요청이에요."


def notify_help_opened(db: Session, help_request: HelpRequest) -> None:
    """새 도움 요청이 생겼을 때 사업주에게 알린다. 지금은 사업주 화면이 GET /api/employer/help를 폴링한다."""
    # TODO(결정 6): 웹 푸시 — 사업주 구독 기기로 알림
    return None


def _help_out(db: Session, h: HelpRequest) -> HelpOut:
    step = versions.find_step(db, h.step_id)
    return HelpOut(id=h.id, assignment_id=h.assignment_id, step_id=h.step_id,
                   step_order=step.order_index if step is not None else None,
                   state=h.state, resolution=h.resolution, created_at=h.created_at,
                   acknowledged_at=h.acknowledged_at, cancelled_at=h.cancelled_at,
                   resolved_at=h.resolved_at)


def _workers_help(help_id: str, worker_id: str, db: Session) -> HelpRequest:
    h = db.get(HelpRequest, help_id)
    if h is None or h.worker_id != worker_id:
        raise HTTPException(status_code=404, detail=_HELP_NOT_FOUND)
    return h


def _employers_help(help_id: str, employer_id: str, db: Session) -> HelpRequest:
    h = db.get(HelpRequest, help_id)
    if h is None or h.employer_id != employer_id:
        # 남의 사업장 요청도 404(존재 여부를 숨긴다).
        raise HTTPException(status_code=404, detail=_HELP_NOT_FOUND)
    return h


@app.post("/api/worker/help", status_code=201, response_model=HelpOut)
def create_help(payload: HelpCreate, response: Response, db: Session = Depends(get_db),
                user: dict = Depends(current_worker)) -> HelpOut:
    """근로자가 [도와주세요]를 눌렀다. 단계 완료로 세지 않는다(수행 로그에 쓰지 않는다).

    같은 배정에 열린 요청이 있으면 새로 만들지 않고 그 요청을 200으로 돌려준다(여러 번 눌러도 한 건).
    """
    try:
        return _create_help_once(payload, response, db, user)
    except IntegrityError:
        # 같은 누름(client_request_id)의 재전송이나 두 기기가 동시에 불러, 둘 다 "열린 요청 없음"을 보고 넣다가
        # 하나가 unique 색인(0006: 누름 키, 배정당 열린 요청 하나)에 걸렸다. 되돌리고 한 번 더 하면 먼저 들어간
        # 요청을 찾아 돌려준다(2차 검증: 예전에는 열린 요청이 두 건 생겨 [취소]가 한 건만 닫았다).
        db.rollback()
        return _create_help_once(payload, response, db, user)


def _help_assignment(db: Session, payload, user: dict) -> tuple[Assignment, str | None]:
    a = db.get(Assignment, payload.assignment_id)
    if a is None or a.worker_id != user["sub"]:
        raise HTTPException(status_code=404, detail="배정을 찾을 수 없습니다.")
    step_id = payload.step_id or None
    if step_id is not None and versions.step_of_assignment(db, a, step_id) is None:
        raise HTTPException(status_code=400, detail="이 배정에 속하지 않는 단계입니다.")
    return a, step_id


def _help_closed_assignment(a: Assignment) -> bool:
    """다 끝낸 일이나 어제 이전 날의 일인지. 그런 일에서 부른 도움은 사업주 화면에 새 호출로 띄우지 않는다.
    (2a-0) 날은 scheduled_day로 본다."""
    if a.status == "done":
        return True
    return a.scheduled_day is not None and a.scheduled_day < clock.local_today()


def _create_help_once(payload: HelpCreate, response: Response, db: Session, user: dict) -> HelpOut:
    a, step_id = _help_assignment(db, payload, user)
    if payload.client_request_id:
        same = db.scalar(select(HelpRequest).where(
            HelpRequest.assignment_id == a.id,
            HelpRequest.client_request_id == payload.client_request_id,
        ).limit(1))
        if same is not None:
            response.status_code = 200
            return _help_out(db, same)
    if _help_closed_assignment(a):
        # 2차 검증: 예전에는 끝낸 일·어제 일의 배정 id(기록·대기열에 남아 있다)로도 열린 요청이 생겨 사업주 화면에
        # 새 호출로 떴다. 같은 누름의 재전송(위)은 그대로 돌려준다.
        raise HTTPException(status_code=409, detail="이미 끝난 일이에요.")
    active = _active_help(db, a.id)
    if active is not None and active.state == "acknowledged":
        # 선생님이 확인했지만 아직 오지 않았을 때 근로자가 다시 불렀다(새 누름 = 새 client_request_id).
        # 예전에는 확인된 요청을 그대로 돌려줘서 근로자는 '선생님이 확인했어요'를 바로 보고, 사업주 화면에는
        # 새 호출이 뜨지 않았다(1차 검증 지적). 같은 요청을 다시 '열림'으로 되돌리고 부른 시각을 새로 적는다.
        key = f"help:{user['sub']}"
        wait = help_throttle.retry_after(key)
        if wait:
            raise HTTPException(status_code=429, detail="잠깐 기다렸다가 다시 불러 주세요.",
                                headers={"Retry-After": str(wait)})
        active.state = "open"
        active.acknowledged_at = None
        active.created_at = _utcnow()
        active.client_request_id = payload.client_request_id
        if step_id is not None:
            active.step_id = step_id
        db.commit()
        db.refresh(active)
        help_throttle.fail(key)
        notify_help_opened(db, active)
        response.status_code = 200
        return _help_out(db, active)
    if active is not None:
        if step_id is not None and active.step_id != step_id:
            active.step_id = step_id  # 다른 단계에서 다시 불렀다 — 사업주가 지금 단계를 보게 한다
            db.commit()
            db.refresh(active)
        response.status_code = 200
        return _help_out(db, active)
    key = f"help:{user['sub']}"
    wait = help_throttle.retry_after(key)
    if wait:
        raise HTTPException(status_code=429, detail="잠깐 기다렸다가 다시 불러 주세요.",
                            headers={"Retry-After": str(wait)})
    worker = db.get(Worker, user["sub"])
    h = HelpRequest(employer_id=worker.employer_id, worker_id=worker.id, assignment_id=a.id,
                    step_id=step_id, state="open", client_request_id=payload.client_request_id,
                    created_at=_utcnow())
    db.add(h)
    db.commit()
    db.refresh(h)
    help_throttle.fail(key)  # 실패가 아니라 "새 요청 한 건"을 센다
    notify_help_opened(db, h)
    return _help_out(db, h)


@app.get("/api/worker/help/{help_id}", response_model=HelpOut)
def get_help(help_id: str, db: Session = Depends(get_db),
             user: dict = Depends(current_worker)) -> HelpOut:
    """근로자 화면이 '불렀어요' 띠를 보이는 동안 5초마다 불러, 선생님이 확인했는지 본다."""
    return _help_out(db, _workers_help(help_id, user["sub"], db))


@app.post("/api/worker/help/{help_id}/cancel", response_model=HelpOut)
def cancel_help(help_id: str, db: Session = Depends(get_db),
                user: dict = Depends(current_worker)) -> HelpOut:
    """근로자 [취소]. 단계 완료로 세지 않는다. 이미 취소했으면 그대로 200, 이미 해결됐으면 409."""
    h = _workers_help(help_id, user["sub"], db)
    if h.state == "resolved":
        raise HTTPException(status_code=409, detail=_HELP_FINISHED)
    if h.state in ACTIVE_HELP_STATES:
        h.state = "cancelled"
        h.cancelled_at = _utcnow()
        db.commit()
        db.refresh(h)
    return _help_out(db, h)


@app.post("/api/worker/help/cancel-by-client", response_model=HelpOut)
def cancel_help_by_client(payload: HelpCreate, db: Session = Depends(get_db),
                          user: dict = Depends(current_worker)) -> HelpOut:
    """답을 못 받은 누름(client_request_id)을 닫는다(2차 검증).

    근로자 기기는 [도와주세요]를 8초 기다리다 끊는다. 그 요청이 늦게라도 서버에 닿으면, 근로자는 이미 [다 했어요]로
    넘어갔는데 사업주 화면에만 '열린 요청'이 남았다. 기기는 [다 했어요] 때 끊긴 누름의 키로 이것을 부른다.
    요청이 아직 안 닿았으면 그 키로 '취소됨' 행을 먼저 만들어 둔다 — 늦게 닿은 누름은 같은 키라 새로 열리지 않는다.
    """
    if not payload.client_request_id:
        raise HTTPException(status_code=422, detail="client_request_id가 필요합니다.")
    try:
        return _cancel_by_client_once(payload, db, user)
    except IntegrityError:
        db.rollback()  # 늦은 누름이 같은 순간 들어갔다 — 한 번 더 하면 그 행을 찾아 닫는다.
        return _cancel_by_client_once(payload, db, user)


def _cancel_by_client_once(payload: HelpCreate, db: Session, user: dict) -> HelpOut:
    a, step_id = _help_assignment(db, payload, user)
    h = db.scalar(select(HelpRequest).where(
        HelpRequest.assignment_id == a.id,
        HelpRequest.client_request_id == payload.client_request_id,
    ).limit(1))
    now = _utcnow()
    if h is None:
        # 3차 검증: 아직 닿지 않은 누름의 '취소됨' 행을 미리 만드는 길이라, 키만 바꿔 부르면 행이 끝없이 쌓였다.
        # 끝낸 일·지난 일에는 만들지 않고(create_help와 같은 409), 새 행은 도움 요청과 같은 몫(60초 10건)으로 센다.
        if _help_closed_assignment(a):
            raise HTTPException(status_code=409, detail="이미 끝난 일이에요.")
        key = f"help:{user['sub']}"
        wait = help_throttle.retry_after(key)
        if wait:
            raise HTTPException(status_code=429, detail="잠깐 기다렸다가 다시 해 주세요.",
                                headers={"Retry-After": str(wait)})
        help_throttle.fail(key)
        h = HelpRequest(employer_id=db.get(Worker, a.worker_id).employer_id, worker_id=a.worker_id,
                        assignment_id=a.id, step_id=step_id, state="cancelled",
                        client_request_id=payload.client_request_id, created_at=now, cancelled_at=now)
        db.add(h)
    elif h.state in ACTIVE_HELP_STATES:
        h.state = "cancelled"
        h.cancelled_at = now
    db.commit()
    db.refresh(h)
    return _help_out(db, h)


@app.get("/api/employer/help", response_model=list[EmployerHelpOut])
def employer_help(request: Request, state: Literal["active", "open", "today"] = "active",
                  db: Session = Depends(get_db),
                  user: dict = Depends(require_employer)) -> list[EmployerHelpOut]:
    """사업주 화면 도움 알림 띠. active(기본: open+acknowledged) / open / today(오늘 생긴 전부). 최신순 50건."""
    query = select(HelpRequest).where(HelpRequest.employer_id == user["sub"])
    if state == "active":
        query = query.where(HelpRequest.state.in_(ACTIVE_HELP_STATES))
    elif state == "open":
        query = query.where(HelpRequest.state == "open")
    else:
        query = query.where(HelpRequest.created_at >= local_day_start_utc().replace(tzinfo=None))
    rows = db.scalars(query.order_by(HelpRequest.created_at.desc()).limit(50)).all()
    out: list[EmployerHelpOut] = []
    for h in rows:
        worker = db.get(Worker, h.worker_id)
        assignment = db.get(Assignment, h.assignment_id)
        if worker is None or assignment is None:
            continue
        task = db.get(Task, assignment.task_id)
        # (2a-0) 도움은 버전 단계를 가리킨다. 문장·순서·썸네일도 근로자가 본 그 단계의 것이다.
        step = versions.find_step(db, h.step_id)
        step_out = versions.worker_step_out(step) if step is not None else None
        out.append(EmployerHelpOut(
            id=h.id, state=h.state, created_at=h.created_at, acknowledged_at=h.acknowledged_at,
            worker_id=worker.id, worker_name=worker.display_name,
            assignment_id=assignment.id, task_id=assignment.task_id,
            task_title=task.title if task is not None else "",
            step_id=step.id if step is not None else None,
            step_order=step.order_index if step is not None else None,
            step_sentence=step.sentence if step is not None else None,
            step_symbol_url=step_out.symbol_url if step_out is not None else None,
        ))
    # 근로자 이름이 실리므로 근로자마다 열람 기록을 남긴다(5초 폴링은 privacy.DEDUPED_ACTIONS가 묶는다).
    # 빈 목록은 개인정보를 보여 주지 않으므로 남기지 않는다(2차 검증: 예전에는 worker_id 없는 행이 1분에 하나씩 쌓였다).
    if out:
        record_access_for_workers(db, request, user, "help.list", [o.worker_id for o in out])
    return out


@app.post("/api/employer/help/{help_id}/acknowledge", response_model=HelpOut)
def acknowledge_help(help_id: str, db: Session = Depends(get_db),
                     user: dict = Depends(require_employer)) -> HelpOut:
    """사업주 [확인했어요]. 근로자 화면 띠가 '선생님이 확인했어요'로 바뀐다."""
    h = _employers_help(help_id, user["sub"], db)
    if h.state == "cancelled":
        raise HTTPException(status_code=409, detail=_HELP_CANCELLED)
    if h.state == "resolved":
        raise HTTPException(status_code=409, detail=_HELP_FINISHED)
    if h.state == "open":
        h.state = "acknowledged"
        h.acknowledged_at = _utcnow()
        db.commit()
        db.refresh(h)
    return _help_out(db, h)


@app.post("/api/employer/help/{help_id}/resolve", response_model=HelpOut)
def resolve_help(help_id: str, db: Session = Depends(get_db),
                 user: dict = Depends(require_employer)) -> HelpOut:
    """사업주 [도와줬어요]. 이미 해결됐으면 그대로 200, 근로자가 취소했으면 409."""
    h = _employers_help(help_id, user["sub"], db)
    if h.state == "cancelled":
        raise HTTPException(status_code=409, detail=_HELP_CANCELLED)
    if h.state in ACTIVE_HELP_STATES:
        h.state = "resolved"
        h.resolution = "employer"
        h.resolved_at = _utcnow()
        db.commit()
        db.refresh(h)
    return _help_out(db, h)


# --- 사업주: 대시보드 집계 ---
def _log_worker_ids(logs, db: Session) -> set[str]:
    """수행 로그들이 어느 근로자의 것인지(접근 감사용)."""
    assignment_ids = {log.assignment_id for log in logs}
    if not assignment_ids:
        return set()
    return set(db.scalars(
        select(Assignment.worker_id).where(Assignment.id.in_(assignment_ids))
    ).all())


def _task_assignments(task_id: str, worker_id: str | None, db: Session) -> list[Assignment]:
    query = select(Assignment).where(Assignment.task_id == task_id)
    if worker_id:
        query = query.where(Assignment.worker_id == worker_id)
    return list(db.scalars(query.order_by(Assignment.assigned_date, Assignment.id)).all())


def _parse_view_day(date: str | None):
    """대시보드·코칭의 ?date=YYYY-MM-DD(달력에서 고른 날). 없으면 None."""
    if not date:
        return None
    try:
        return datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=422, detail="날짜를 다시 골라 주세요.") from None


def _shown_assignments(assignments: list[Assignment], worker_id: str | None, day=None) -> list[Assignment]:
    """대시보드·코칭이 셀 배정(contract §1.6). 근로자를 고르지 않았으면 모두(직무 전체 집계).

    근로자를 고르면 배정 하나만 센다 — 그 배정의 기록만, 그 배정의 고정 버전 단계에 맞춰서. 예전처럼 그 근로자의
    모든 배정 기록을 단계 키로 합치면 (1) 내일로 보낸 배정(아직 시작 전)의 단계가 오늘 하는 중인 배정 대신 보이고
    (2) 어제 못 끝낸 배정의 기록이 오늘 새로 받은 배정에 겹쳐 '이미 한 단계'로 셌다(1회차 검증).
    고르는 배정: 오늘까지의 날(scheduled_day <= 오늘) 중 가장 늦은 날의, 가장 늦게 보낸 배정(오늘 하는 중인 일은
    다시 보내도 같은 배정에 남으므로 이것이 된다). 오늘까지 배정이 없고 앞날 배정만 있으면 가장 가까운 앞날 배정.
    day(달력에서 고른 날)를 주면 그날(scheduled_day == day) 배정 중 가장 늦게 보낸 배정, 없으면 빈 목록. 어제 못
    끝낸 일을 오늘 다시 보내 새 배정이 생겨도, 어제를 고르면 어제 배정의 기록이 보여야 한다(2회차 검증).
    """
    if not worker_id or not assignments:
        return assignments
    today = clock.local_today()
    order = lambda a: (a.scheduled_day or today, a.assigned_date, a.id)  # noqa: E731
    if day is not None:
        on_day = [a for a in assignments if (a.scheduled_day or today) == day]
        return [max(on_day, key=order)] if on_day else []
    due = [a for a in assignments if (a.scheduled_day or today) <= today]
    if due:
        return [max(due, key=order)]
    return [min(assignments, key=order)]


def _dashboard_steps(task: Task, assignments: list[Assignment], worker_id: str | None, db: Session) -> list:
    """대시보드·코칭의 단계 목록(contract §1.6). 근로자를 고르면 _shown_assignments가 고른 배정의 고정 버전 단계(하는
    중에 지운 단계의 기록도 보인다), 아니면 마지막으로 보낸 버전, 보낸 적이 없으면 편집 단계."""
    if worker_id and assignments:
        return versions.assignment_steps(db, assignments[-1], task)
    v = versions.latest_version(db, task)
    return list(v.steps) if v is not None else list(task.steps)


def _logs_by_step(assignments: list[Assignment], db: Session) -> dict[str, PerformanceLog]:
    """배정들의 수행 로그를 단계 키(versions.step_key: 버전을 넘어 같은 단계면 같은 키)로 모은다.

    배정은 보낸 순서로 정렬돼 있고, 같은 키면 늦게 보낸 배정의 기록이 이긴다. 한 직무를 여러 근로자에게 배정한
    경우(1:N) worker_id 없이 모으면 한 명분만 남으므로, 대시보드는 항상 근로자를 지정해 호출한다.
    """
    assignment_ids = [a.id for a in assignments]
    if not assignment_ids:
        return {}
    logs = db.scalars(
        select(PerformanceLog).where(PerformanceLog.assignment_id.in_(assignment_ids))
    ).all()
    order = {aid: i for i, aid in enumerate(assignment_ids)}
    steps = versions.find_steps(db, {log.step_id for log in logs})
    out: dict[str, PerformanceLog] = {}
    for log in sorted(logs, key=lambda x: order.get(x.assignment_id, 0)):
        st = steps.get(log.step_id)
        out[versions.step_key(st) if st is not None else log.step_id] = log
    return out


def _help_step_ids(assignments: list[Assignment], db: Session) -> set[str]:
    """도움 요청이 한 번이라도 있었던 단계 키. 대시보드·코칭의 '막힘'에 더한다.

    예전에는 [도와주세요]가 stuck=true 수행 로그였다. 도움 요청을 따로 두면서도 사업주 화면에는 지금처럼 보이게 한다.
    """
    assignment_ids = [a.id for a in assignments]
    if not assignment_ids:
        return set()
    ids = set(db.scalars(select(HelpRequest.step_id).where(HelpRequest.assignment_id.in_(assignment_ids),
                                                          HelpRequest.step_id.is_not(None))).all())
    steps = versions.find_steps(db, ids)
    return {versions.step_key(steps[i]) if i in steps else i for i in ids}


def _log_done(log: PerformanceLog | None) -> bool:
    return log is not None and bool(log.completed)


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
            access_code=decrypt_access_code(worker.employer_id, worker.access_code_cipher),
            access_code_hint=worker.access_code_hint, status=a.status,
        ))
    # 이 목록에는 여러 근로자의 이름·진행 상태가 실린다. 누구의 정보가 보였는지 남기려고 근로자마다 기록한다.
    record_access_for_workers(db, request, user, "dashboard.workers", [o.worker_id for o in out])
    return out


@app.get("/api/dashboard/tasks/{task_id}", response_model=DashboardOut)
def dashboard(task_id: str, request: Request, worker_id: str | None = None,
              date: str | None = None,
              db: Session = Depends(get_db),
              user: dict = Depends(require_employer)) -> DashboardOut:
    task = _owned_task(task_id, user["sub"], db)
    if worker_id:
        # 다른 사업장 근로자 id로 감사 행이 남지 않게, 기록 전에 소유를 확인한다(404 규칙 통일).
        _owned_worker(worker_id, user["sub"], db)
    assignments = _shown_assignments(_task_assignments(task_id, worker_id, db), worker_id,
                                     _parse_view_day(date))
    logs_by_step = _logs_by_step(assignments, db)
    # 근로자별 수행 기록 열람. 3초 폴링은 privacy.record_access가 짧은 창 안에서 한 줄로 합친다.
    if worker_id:
        record_access(db, request, user, "dashboard.view", worker_id)
    else:
        # 근로자를 고르지 않은 집계 화면에도 여러 근로자의 수행 기록이 섞여 보인다. worker_id=None 한 줄로는
        # 누구의 기록이 보였는지 알 수 없으므로, 실제로 화면에 실린 기록의 근로자마다 남긴다.
        record_access_for_workers(db, request, user, "dashboard.view",
                                  _log_worker_ids(logs_by_step.values(), db))

    help_steps = _help_step_ids(assignments, db)
    steps = _dashboard_steps(task, assignments, worker_id, db)
    step_stats: list[StepStat] = []
    stuck_steps: list[int] = []
    completed = 0
    for s in steps:
        key = versions.step_key(s)
        log = logs_by_step.get(key)
        done = _log_done(log)
        if done:
            completed += 1
        stuck = bool(log and log.stuck) or key in help_steps
        if stuck:
            stuck_steps.append(s.order_index)
        step_stats.append(StepStat(
            order=s.order_index, sentence=s.sentence, completed=done,
            duration_sec=log.duration_sec if log else 0.0,
            replay_count=log.replay_count if log else 0,
            stuck=stuck,
        ))

    total = len(steps)
    rate = round(completed / total * 100, 1) if total else 0.0
    return DashboardOut(
        task_id=task.id, task_title=task.title, total_steps=total,
        completed_steps=completed, completion_rate=rate,
        stuck_steps=stuck_steps, steps=step_stats,
    )


@app.get("/api/dashboard/tasks/{task_id}/coaching", response_model=CoachingOut)
def task_coaching(task_id: str, request: Request, worker_id: str | None = None,
              date: str | None = None,
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
    assignments = _shown_assignments(_task_assignments(task_id, worker_id, db), worker_id,
                                     _parse_view_day(date))
    logs_by_step = _logs_by_step(assignments, db)

    included_query = select(Assignment.worker_id).where(Assignment.task_id == task_id)
    if worker_id:
        included_query = included_query.where(Assignment.worker_id == worker_id)
    included = sorted(set(db.scalars(included_query).all()))
    consented = workers_with_active_consent(db, included)
    allow_llm = all(w in consented for w in included)

    masker = employer_pseudonymizer(db, user["sub"])
    help_steps = _help_step_ids(assignments, db)
    steps_payload = []
    for s in _dashboard_steps(task, assignments, worker_id, db):
        key = versions.step_key(s)
        log = logs_by_step.get(key)
        steps_payload.append({
            "order": s.order_index,
            "sentence": masker.mask(s.sentence),
            "action_type": s.action_type,
            "completed": _log_done(log),
            "stuck": bool(log and log.stuck) or key in help_steps,
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
    step.picture_confirmed = True  # 사업주가 직접 올린 사진
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
    step.picture_confirmed = False
    db.commit()
    media.release(db, [previous])
    db.refresh(step)
    return _step_to_out(step)


# (2a-0) 보내기 검사·보내기·받는 사람(send.py). 새 라우트는 APIRouter 모듈에 두고 여기서는 include만 한다.
app.include_router(send.router)
app.include_router(task_list.router)
app.include_router(workers_admin.router)
