"""인증/인가 (표준 라이브러리만 사용, 추가 의존성 없음).

- 비밀번호: pbkdf2_hmac(sha256, 200k) 해시 + 랜덤 솔트
- 토큰: HMAC-SHA256 서명 JSON (sub, role, exp)
- FastAPI 의존성: get_current_user / require_employer / require_worker

운영 주의: JOBCARD_SECRET를 반드시 강한 랜덤 값으로 설정한다(운영은 Docker secret 파일 →
JOBCARD_SECRET_FILE, secret_env.py·docs/security/secrets.md).
기본값은 개발 전용이며, 미설정 상태로는 운영 기동을 막는다(PROD 가드).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import threading
import time

from fastapi import Depends, Header, HTTPException

from secret_env import read_secret

_DEV_SECRET = "dev-insecure-secret-change-me"


_MIN_PROD_SECRET_LEN = 32


def is_production() -> bool:
    return os.getenv("JOBCARD_ENV", "dev").strip().lower() in {"prod", "production"}


# 프로세스가 처음 읽은 JOBCARD_SECRET. 예전에는 토큰 검증·접속 코드 해시·서명 URL을 만들 때마다
# 비밀값 파일(/run/secrets/jobcard_secret)을 다시 열었다 — 요청마다 디스크 I/O가 생기고, 운영자가 파일을
# 고쳐 쓰는 순간(잠깐 빈 파일)에는 요청마다 다른 키(개발용 기본 키 포함)로 서명할 수 있었다.
# 그래서 기동 시(lifespan의 check_production_config) 한 번 읽어 둔다. 키 교체는 재시작으로 반영된다
# (docs/security/secrets.md 3절: `docker compose up -d --force-recreate backend`).
_secret_cache: str | None = None
_secret_lock = threading.Lock()


def reset_secret_cache() -> None:
    """캐시를 비워 다음 호출이 다시 읽게 한다. 테스트(환경변수·파일을 바꾸는 경우) 전용 훅이다.
    운영 코드는 부르지 않는다 — 실행 중 키 교체는 지원하지 않는다(위 주석)."""
    global _secret_cache
    with _secret_lock:
        _secret_cache = None


def _load_secret() -> str:
    # docker-compose의 "${JOBCARD_SECRET:-}"처럼 빈 값으로 넘어오면 '설정 안 함'과 같다.
    # 빈 문자열을 그대로 HMAC 키로 쓰면 누구나 토큰을 위조할 수 있다.
    # JOBCARD_SECRET_FILE(/run/secrets/jobcard_secret)이 환경변수보다 우선한다(secret_env.py 참고).
    secret = read_secret("JOBCARD_SECRET").strip() or _DEV_SECRET
    if is_production() and (secret == _DEV_SECRET or len(secret) < _MIN_PROD_SECRET_LEN):
        raise RuntimeError(
            f"운영 환경에서는 JOBCARD_SECRET를 {_MIN_PROD_SECRET_LEN}자 이상의 무작위 값으로 설정해야 합니다. "
            "예: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    return secret


def _secret() -> str:
    global _secret_cache
    cached = _secret_cache
    if cached is not None:
        return cached
    with _secret_lock:
        if _secret_cache is None:
            # 운영 가드에 걸리면 예외가 나고 캐시하지 않는다 — 다음 호출도 다시 실패한다.
            _secret_cache = _load_secret()
        return _secret_cache


def check_production_config() -> None:
    """기동 시 비밀값을 한 번 읽어 캐시하고 검사한다(첫 로그인 때가 아니라 서버가 뜰 때 실패하게).

    예전에는 운영에서만 불렀다. 개발에서도 여기서 읽어 두어 첫 요청이 파일 I/O·오류를 떠안지 않게 한다.
    """
    _secret()


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


def make_token(sub: str, role: str, ttl: int = TOKEN_TTL_SEC, extra: dict | None = None) -> str:
    payload = {**(extra or {}), "sub": sub, "role": role, "exp": int(time.time()) + ttl}
    body = _b64e(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    return f"{body}.{_sign(body)}"


def hash_access_code(employer_id: str, access_code: str) -> str:
    """근로자 접속 코드의 저장용 해시(hex 64자). 평문 코드는 DB에 남기지 않는다.

    - 접속 코드는 4~12자리 숫자라 경우의 수가 작다. 솔트 없는 sha256이면 DB가 새는 순간 전부
      복원되므로 서버 시크릿(JOBCARD_SECRET)으로 HMAC한다. 시크릿 없이 DB만으로는 복원할 수 없다.
    - employer_id를 섞는 이유: 같은 코드라도 사업장마다 해시가 달라져, 해시 값만 보고 "두 사업장이
      같은 코드를 쓴다"를 알 수 없다. unique 제약도 (employer_id, 해시)로 건다.
    - 로그인 때마다 같은 값을 다시 계산해 조회하므로 pbkdf2 같은 느린 해시를 쓰지 않는다
      (조회 키여야 한다). 대입 방어는 로그인 시도 제한(ratelimit)이 맡는다.
    - JOBCARD_SECRET를 바꾸면 모든 해시가 맞지 않게 된다 → 근로자 접속 코드를 모두 재발급해야 한다.
    """
    return hmac.new(_secret().encode("utf-8"), f"{employer_id}:{access_code}".encode("utf-8"),
                    hashlib.sha256).hexdigest()


def code_fingerprint(access_code_hash: str) -> str:
    """근로자 토큰에 넣는 접속 코드 지문. 코드를 재발급하면 지문이 바뀌어 예전 토큰이 무효가 된다.

    토큰 본문은 서명만 될 뿐 누구나 읽을 수 있다. 평문 해시(sha256(code))를 넣으면 6자리 코드는
    100만 번 대입으로 바로 복원되므로, 서버 시크릿으로 HMAC한 값을 넣는다.
    평문 코드를 더 이상 저장하지 않으므로 저장된 해시(hash_access_code)에서 지문을 만든다.
    DB 해시를 그대로 토큰에 싣지 않고 한 번 더 HMAC해 잘라 쓴다(토큰 = 저장 값 노출이 되지 않게).
    """
    digest = hmac.new(_secret().encode("utf-8"), f"worker-code:{access_code_hash}".encode("utf-8"),
                      hashlib.sha256).digest()
    return _b64e(digest[:12])


def media_signature(media_id: str, exp: int) -> str:
    """사진·TTS 서명 URL의 서명(media.py). HMAC(JOBCARD_SECRET, "media:<id>:<exp>").

    "media:" 접두로 용도를 나눈다 — 같은 키로 만드는 토큰 서명·접속 코드 해시와 입력 모양이 겹쳐
    한쪽 값을 다른 쪽 서명으로 재사용하는 일이 없게 한다. JOBCARD_SECRET를 바꾸면 발급된 URL은
    모두 무효가 되지만, 화면이 다시 조회하면 새 URL을 받으므로 문제가 없다.
    """
    return _b64e(hmac.new(_secret().encode("utf-8"), f"media:{media_id}:{exp}".encode("utf-8"),
                          hashlib.sha256).digest())


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
