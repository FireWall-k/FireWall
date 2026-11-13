"""웹 푸시(2c, contract §5.2): 도움 요청이 생기면 사업주 기기에 알린다.

- 키: VAPID_PUBLIC_KEY(공개 키, base64url), VAPID_PRIVATE_KEY_FILE(개인 키 PEM 파일 경로), VAPID_SUBJECT(연락처,
  기본 mailto). 공개 키나 개인 키 파일이 없으면 enabled=false이고 아무것도 보내지 않는다. 키는 manage.py vapid-keys로 만든다.
- 내용: 제목 '잡카드', 내용 '도움 요청이 있어요'(근로자 이름 없음 — 잠금 화면에 뜬다), 누르면 /manager#help. 문자 메시지는 없다.
- 보내기는 요청 처리 밖(작은 스레드 풀)에서 한다. 도움 생성은 푸시 결과와 상관없이 늘 201이다.
  사업장마다 한 번에 하나만 돈다. 도는 중에 또 부르면 '한 번 더'만 표시하고 끝난 뒤 한 번 더 돈다 — 한 사업장의
  느린 구독이 풀을 독차지해 다른 사업장 푸시를 늦추지 못하게 한다. 구독 하나는 연결 3초·읽기 5초, 한 번 도는 데
  ROUND_BUDGET_SEC(30초)를 넘으면 남은 구독은 이번에 건너뛴다(최근에 성공한 구독부터 보낸다).
- 구독 주소는 알려진 푸시 서비스 호스트(PUSH_HOST_SUFFIXES)의 https 443만 받는다. 서버가 내부 주소로 POST를
  보내게 하지 못하게 한다(SSRF).
  푸시 서비스가 410·404를 주면 그 구독을 지우고, 나머지 실패는 기록만 남기고 무시한다.
- 이 모듈은 main을 import하지 않는다(main이 include하고 notify_help_opened가 notify_help를 부른다).
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from urllib3.util import parse_url

import clock
from auth import require_employer
from database import SessionLocal, get_db
from models import PushSubscription
from schemas import PushConfigOut, PushSubscriptionIn, PushUnsubscribeIn

try:  # pywebpush==2.5.0(requirements.txt). 없으면 푸시만 꺼진다(도움 띠는 그대로).
    from pywebpush import WebPushException, webpush
except ImportError:  # pragma: no cover - 설치본에는 있다
    webpush = None

    class WebPushException(Exception):  # type: ignore[no-redef]
        response = None

logger = logging.getLogger("jobcard.push")
router = APIRouter()

TITLE = "잡카드"
BODY_HELP = "도움 요청이 있어요"
URL_HELP = "/manager#help"
TTL_SEC = 300
# requests의 (연결, 읽기) 시간 제한. 읽기는 받을 때마다 다시 세므로 한 번 도는 전체 상한(ROUND_BUDGET_SEC)도 둔다.
TIMEOUT_SEC = (3, 5)
ROUND_BUDGET_SEC = 30.0
# 한 사업장의 구독 상한. 넘으면 가장 오래된 것부터 지운다(브라우저를 바꿀 때마다 쌓이지 않게).
MAX_SUBSCRIPTIONS = 20
GONE_STATUS = (404, 410)

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="push")
# 사업장마다 도는 중인지·끝나고 한 번 더 돌지(도는 중에 새 도움이 열림).
_round_lock = threading.Lock()
_running: set[str] = set()
_again: set[str] = set()
_vapid_lock = threading.Lock()
_vapid_cache: dict[str, object] = {}


def public_key() -> str | None:
    return (os.getenv("VAPID_PUBLIC_KEY") or "").strip() or None


def _private_key_file() -> str | None:
    """개인 키 파일 경로. 없거나 비어 있으면(init-secrets가 만든 빈 자리, 공백만 있어도) None — 웹 푸시를 끈다."""
    path = (os.getenv("VAPID_PRIVATE_KEY_FILE") or "").strip()
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, "rb") as f:
            blank = not f.read(4096).strip(b" \t\r\n\xef\xbb\xbf")
    except OSError:
        return None
    return None if blank else path


def enabled() -> bool:
    return webpush is not None and public_key() is not None and _private_key_file() is not None


def _subject() -> str:
    return (os.getenv("VAPID_SUBJECT") or "mailto:jobcard@example.com").strip()


def _vapid():
    """개인 키 파일을 한 번만 읽는다(파일 경로가 바뀌면 다시 읽는다). 키 내용은 기록에 남기지 않는다."""
    from py_vapid import Vapid
    path = _private_key_file()
    with _vapid_lock:
        if path not in _vapid_cache:
            _vapid_cache.clear()
            _vapid_cache[path] = Vapid.from_file(path)
        return _vapid_cache[path]


def help_payload() -> str:
    return json.dumps({"title": TITLE, "body": BODY_HELP, "url": URL_HELP}, ensure_ascii=False)


def _status_of(exc: Exception) -> int | None:
    resp = getattr(exc, "response", None)
    return getattr(resp, "status_code", None)


def send_one(sub: PushSubscription, data: str) -> None:
    """구독 하나에 보낸다. 실패하면 WebPushException(또는 네트워크 예외)을 올린다."""
    webpush(
        subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
        data=data,
        vapid_private_key=_vapid(),
        # webpush가 이 사전에 aud·exp를 써 넣으므로 보낼 때마다 새로 만든다.
        vapid_claims={"sub": _subject()},
        ttl=TTL_SEC,
        timeout=TIMEOUT_SEC,
    )


def send_all(employer_id: str, data: str) -> dict:
    """사업장 구독마다 보낸다. 410·404는 구독을 지운다. 결과 수를 돌려준다(시험·기록용)."""
    sent = gone = failed = 0
    with SessionLocal() as db:
        subs = db.scalars(select(PushSubscription).where(PushSubscription.employer_id == employer_id)
                          .order_by(PushSubscription.last_ok_at.is_(None), PushSubscription.last_ok_at.desc(),
                                    PushSubscription.created_at.desc())).all()
        deadline = time.monotonic() + ROUND_BUDGET_SEC
        for sub in subs:
            if time.monotonic() > deadline:
                failed += 1
                continue
            try:
                send_one(sub, data)
            except Exception as exc:  # noqa: BLE001 — 어떤 실패도 도움 요청을 막지 않는다
                if _status_of(exc) in GONE_STATUS:
                    db.delete(sub)
                    gone += 1
                else:
                    failed += 1
                    logger.warning("웹 푸시 실패(사업장 %s, 상태 %s): %s", employer_id, _status_of(exc),
                                   type(exc).__name__)
                continue
            sub.last_ok_at = clock.utcnow()
            sent += 1
        db.commit()
    return {"sent": sent, "gone": gone, "failed": failed}


def _submit(fn, *args) -> None:
    """요청 처리 밖에서 돌린다. 시험은 이 함수를 바꿔 바로 돌린다."""
    _executor.submit(_safe, fn, *args)


def _safe(fn, *args) -> None:
    try:
        fn(*args)
    except Exception:  # noqa: BLE001
        logger.exception("웹 푸시 작업이 실패했습니다")


def _run_rounds(employer_id: str, data: str) -> None:
    """한 사업장의 보내기를 돈다. 도는 중에 또 불렸으면 끝난 뒤 한 번 더 돈다(여러 번 불려도 한 번으로 합친다)."""
    try:
        while True:
            try:
                send_all(employer_id, data)
            except Exception:  # noqa: BLE001
                logger.exception("웹 푸시 작업이 실패했습니다")
            with _round_lock:
                if employer_id not in _again:
                    _running.discard(employer_id)
                    return
                _again.discard(employer_id)
    except BaseException:
        with _round_lock:
            _running.discard(employer_id)
            _again.discard(employer_id)
        raise


def notify_help(employer_id: str | None) -> None:
    """도움 요청이 열렸다(새 요청 또는 확인한 요청을 다시 부름). 키가 없으면 아무것도 하지 않는다."""
    if not employer_id or not enabled():
        return
    with _round_lock:
        if employer_id in _running:
            _again.add(employer_id)
            return
        _running.add(employer_id)
    try:
        _submit(_run_rounds, employer_id, help_payload())
    except Exception:  # noqa: BLE001 — 스레드 풀이 닫힌 경우 등. 도움 요청은 그대로 201이다.
        with _round_lock:
            _running.discard(employer_id)
            _again.discard(employer_id)
        logger.exception("웹 푸시를 맡기지 못했습니다")


# --- API -----------------------------------------------------------------------------------

_MSG_ENDPOINT = "알림 주소가 올바르지 않아요. 알림을 다시 켜 주세요."


# 브라우저가 주는 푸시 서비스 호스트(정확히 같거나 '.'+접미사로 끝남). 그 밖의 주소(사설·루프백·링크 로컬 IP,
# localhost, 다른 도메인)는 받지 않는다 — 서버가 그 주소로 POST를 보내게 되기 때문이다.
PUSH_HOST_SUFFIXES = (
    "fcm.googleapis.com",            # Chrome·Edge(안드로이드 포함)·삼성 인터넷
    "push.services.mozilla.com",     # Firefox (updates.push.services.mozilla.com)
    "notify.windows.com",            # 예전 Edge(WNS)
    "push.apple.com",                # Safari (web.push.apple.com)
)


_BAD_URL_CHARS = re.compile(r"[\\\s\x00-\x1f\x7f-\x9f]")  # 백슬래시·공백·제어 문자
_HOST_RE = re.compile(r"[A-Za-z0-9.-]+")


def _allowed_host(host: str) -> bool:
    host = host.lower().rstrip(".")
    return any(host == suf or host.endswith("." + suf) for suf in PUSH_HOST_SUFFIXES)


def _check_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip()
    try:
        u = urlparse(endpoint)
        port = u.port
    except ValueError:
        raise HTTPException(status_code=422, detail=_MSG_ENDPOINT) from None
    host = u.hostname or ""
    # 백슬래시·공백·제어 문자가 있으면 urlparse와 실제로 보내는 urllib3가 호스트를 서로 다르게 읽을 수 있다
    # (예: 'https://127.0.0.1\.fcm.googleapis.com/x' → urllib3는 127.0.0.1에 연결). 그래서 아예 받지 않는다.
    if _BAD_URL_CHARS.search(endpoint) or not _HOST_RE.fullmatch(host):
        raise HTTPException(status_code=422, detail=_MSG_ENDPOINT)
    if (u.scheme != "https" or not host or u.username is not None or u.password is not None
            or port not in (None, 443) or not _allowed_host(host)):
        raise HTTPException(status_code=422, detail=_MSG_ENDPOINT)
    # 실제로 연결할 호스트(urllib3 기준)도 같아야 한다
    try:
        real = parse_url(endpoint)
    except Exception:  # noqa: BLE001 - urllib3 LocationParseError 등
        raise HTTPException(status_code=422, detail=_MSG_ENDPOINT) from None
    if (real.host or "").lower() != host.lower() or real.port not in (None, 443) or real.auth is not None:
        raise HTTPException(status_code=422, detail=_MSG_ENDPOINT)
    return endpoint


@router.get("/api/employer/push-config", response_model=PushConfigOut)
def push_config(user: dict = Depends(require_employer)) -> PushConfigOut:
    on = enabled()
    return PushConfigOut(enabled=on, public_key=public_key() if on else None)


@router.post("/api/employer/push-subscriptions", status_code=201)
def subscribe(payload: PushSubscriptionIn, request: Request, db: Session = Depends(get_db),
              user: dict = Depends(require_employer)) -> dict:
    """구독 저장(같은 주소면 갱신). 다른 사업장이 쓰던 주소면 이 사업장으로 옮긴다(같은 기기에서 계정을 바꿈)."""
    endpoint = _check_endpoint(payload.endpoint)
    sub = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == endpoint))
    if sub is None:
        sub = PushSubscription(endpoint=endpoint, created_at=clock.utcnow())
        db.add(sub)
    sub.employer_id = user["sub"]
    sub.p256dh = payload.keys.p256dh
    sub.auth = payload.keys.auth
    sub.user_agent = (request.headers.get("user-agent") or "")[:200]
    db.flush()
    ids = db.scalars(select(PushSubscription.id).where(PushSubscription.employer_id == user["sub"])
                     .order_by(PushSubscription.created_at.desc(), PushSubscription.id)).all()
    old = [i for i in ids if i != sub.id][MAX_SUBSCRIPTIONS - 1:]
    if old:
        db.execute(delete(PushSubscription).where(PushSubscription.id.in_(old)))
    db.commit()
    return {"ok": True}


@router.delete("/api/employer/push-subscriptions", status_code=204)
def unsubscribe(payload: PushUnsubscribeIn, db: Session = Depends(get_db),
                user: dict = Depends(require_employer)) -> Response:
    """이 사업장의 그 주소만 지운다(없어도 204)."""
    db.execute(delete(PushSubscription).where(PushSubscription.endpoint == payload.endpoint.strip(),
                                              PushSubscription.employer_id == user["sub"]))
    db.commit()
    return Response(status_code=204)
