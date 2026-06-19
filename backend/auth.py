"""인증/인가 (표준 라이브러리만 사용, 추가 의존성 없음).

- 비밀번호: pbkdf2_hmac(sha256, 200k) 해시 + 랜덤 솔트
- 토큰: HMAC-SHA256 서명 JSON (sub, role, exp)
- FastAPI 의존성: get_current_user / require_employer / require_worker

운영 주의: JOBCARD_SECRET 환경변수를 반드시 강한 랜덤 값으로 설정한다.
기본값은 개발 전용이며, 미설정 상태로는 운영 기동을 막는다(PROD 가드).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

from fastapi import Depends, Header, HTTPException

_DEV_SECRET = "dev-insecure-secret-change-me"


def _secret() -> str:
    secret = os.getenv("JOBCARD_SECRET", _DEV_SECRET)
    if os.getenv("JOBCARD_ENV", "dev").lower() in {"prod", "production"} and secret == _DEV_SECRET:
        raise RuntimeError("운영 환경에서는 JOBCARD_SECRET를 반드시 설정해야 합니다.")
    return secret


TOKEN_TTL_SEC = int(os.getenv("JOBCARD_TOKEN_TTL", "86400"))


# --- 비밀번호 해시 -----------------------------------------------------------
def hash_password(password: str, *, _salt: bytes | None = None) -> str:
    salt = _salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 200_000)
    except Exception:  # noqa: BLE001 - 잘못된 형식이면 인증 실패로 처리
        return False
    return hmac.compare_digest(dk.hex(), dk_hex)


# --- 토큰 --------------------------------------------------------------------
def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(body: str) -> str:
    return _b64e(hmac.new(_secret().encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest())


def make_token(sub: str, role: str, ttl: int = TOKEN_TTL_SEC) -> str:
    payload = {"sub": sub, "role": role, "exp": int(time.time()) + ttl}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def verify_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(body)):
            return None
        payload = json.loads(_b64d(body))
        if int(payload["exp"]) < int(time.time()):
            return None
        return payload
    except Exception:  # noqa: BLE001 - 변조/만료/형식오류는 모두 무효 토큰
        return None


# --- FastAPI 의존성 ----------------------------------------------------------
def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="로그인이 필요합니다.")
    payload = verify_token(authorization[len("Bearer "):].strip())
    if payload is None:
        raise HTTPException(status_code=401, detail="토큰이 유효하지 않거나 만료되었습니다.")
    return payload


def require_employer(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "employer":
        raise HTTPException(status_code=403, detail="사업주 권한이 필요합니다.")
    return user


def require_worker(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "worker":
        raise HTTPException(status_code=403, detail="근로자 권한이 필요합니다.")
    return user
