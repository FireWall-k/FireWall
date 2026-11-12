"""라우터 모듈이 함께 쓰는 인증 의존성(2c). main을 import하지 않는다."""
from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from auth import code_fingerprint, get_current_user, require_worker
from database import get_db
from models import Worker


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


def any_user(user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """근로자·사업주 토큰 모두 받는다(측정 이벤트). 근로자 토큰은 current_worker와 같은 검사를 한다."""
    if user.get("role") == "worker":
        return current_worker(user, db)
    if user.get("role") != "employer":
        raise HTTPException(status_code=403, detail="권한이 없습니다.")
    return user
