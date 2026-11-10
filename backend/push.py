"""웹 푸시(2c, contract §5.2): 도움 요청이 생기면 사업주 기기에 알린다.

- 키: VAPID_PUBLIC_KEY(공개 키, base64url), VAPID_PRIVATE_KEY_FILE(개인 키 PEM 파일 경로), VAPID_SUBJECT(연락처,
  기본 mailto). 공개 키나 개인 키 파일이 없으면 enabled=false이고 아무것도 보내지 않는다. 키는 manage.py vapid-keys로 만든다.
- 내용: 제목 '잡카드', 내용 '도움 요청이 있어요'(근로자 이름 없음 — 잠금 화면에 뜬다), 누르면 /m#help. 문자 메시지는 없다.
- 보내기는 요청 처리 밖(작은 스레드 풀)에서 한다. 도움 생성은 푸시 결과와 상관없이 늘 201이다.
  푸시 서비스가 410·404를 주면 그 구독을 지우고, 나머지 실패는 기록만 남기고 무시한다.
- 이 모듈은 main을 import하지 않는다(main이 include하고 notify_help_opened가 notify_help를 부른다).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

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
URL_HELP = "/m#help"
TTL_SEC = 300
TIMEOUT_SEC = 10
# 한 사업장의 구독 상한. 넘으면 가장 오래된 것부터 지운다(브라우저를 바꿀 때마다 쌓이지 않게).
MAX_SUBSCRIPTIONS = 20
GONE_STATUS = (404, 410)

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push")
_vapid_lock = threading.Lock()
_vapid_cache: dict[str, object] = {}


def public_key() -> str | None:
    return (os.getenv("VAPID_PUBLIC_KEY") or "").strip() or None


def _private_key_file() -> str | None:
    path = (os.getenv("VAPID_PRIVATE_KEY_FILE") or "").strip()
    return path if path and os.path.isfile(path) else None


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
        subs = db.scalars(select(PushSubscription).where(PushSubscription.employer_id == employer_id)).all()
        for sub in subs:
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


def notify_help(employer_id: str | None) -> None:
    """도움 요청이 열렸다(새 요청 또는 확인한 요청을 다시 부름). 키가 없으면 아무것도 하지 않는다."""
    if not employer_id or not enabled():
        return
    try:
        _submit(send_all, employer_id, help_payload())
    except Exception:  # noqa: BLE001 — 스레드 풀이 닫힌 경우 등. 도움 요청은 그대로 201이다.
        logger.exception("웹 푸시를 맡기지 못했습니다")


# --- API -----------------------------------------------------------------------------------

_MSG_ENDPOINT = "알림 주소가 올바르지 않아요. 알림을 다시 켜 주세요."


def _check_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip()
    u = urlparse(endpoint)
    if u.scheme != "https" or not u.netloc:
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
