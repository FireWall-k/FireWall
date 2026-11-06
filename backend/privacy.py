"""개인정보 보호 도구 (Phase 0.2).

- Pseudonymizer: AI 하네스(→ 해외 LLM·임베딩)로 보내기 전에 근로자 실명을 "근로자 A" 같은 별칭으로 바꾸고,
  응답에서 다시 실명으로 되돌린다. 매핑은 요청 하나 안에서만 쓰고 저장하지 않는다.
- 동의: 근로자별 동의 기록(WorkerConsent) 중 AI 처리 동의가 살아 있는지 확인한다.
- 접근 감사: 사업주가 근로자 개인 데이터를 볼 때 AccessAuditLog에 한 줄 남긴다.

무엇이 어디로 가는지는 docs/privacy/data-map.md에 정리돼 있다. 여기를 바꾸면 그 문서도 고친다.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import AccessAuditLog, Worker, WorkerConsent
from ratelimit import client_ip

# 동의 종류. 개인정보 처리방침(docs/privacy/개인정보처리방침.md)의 항목과 1:1로 맞춘다.
#   personal_info : 서비스 제공을 위한 개인정보 수집·이용(이름, 수행 기록)
#   ai_processing : AI 코칭을 위한 처리 위탁·국외 이전(OpenAI, 미국) — 이게 있어야 LLM 경로를 쓴다
CONSENT_PERSONAL_INFO = "personal_info"
CONSENT_AI_PROCESSING = "ai_processing"
CONSENT_TYPES = (CONSENT_PERSONAL_INFO, CONSENT_AI_PROCESSING)
CONSENT_SUBJECTS = ("self", "guardian")


def policy_version() -> str:
    """동의를 받을 때 보여 준 개인정보 처리방침 버전. 방침을 고치면 올리고, 동의 기록에 함께 남긴다."""
    return os.getenv("PRIVACY_POLICY_VERSION", "2026-11-07-draft").strip() or "2026-11-07-draft"


# --- 실명 → 별칭 --------------------------------------------------------------

# 이름으로 보지 않는 값. 기본 이름 "근로자"까지 바꾸면 "근로자 휴게실" 같은 문장이 망가지고,
# 별칭("근로자 A")과도 섞인다.
_GENERIC_NAMES = {"근로자", "직원", "알바", "worker"}
_MIN_NAME_LEN = 2


def _alias(i: int) -> str:
    # A..Z, 그다음 AA, AB … (스프레드시트 열 이름과 같은 방식). 사업장 근로자가 26명을 넘어도 겹치지 않는다.
    letters = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        letters = chr(ord("A") + r) + letters
    return f"근로자 {letters}"


class Pseudonymizer:
    """요청 하나 안에서 실명 ↔ 별칭을 안정적으로 바꾼다.

    한계(문서화): 등록된 표시 이름과 글자가 똑같을 때만 바꾼다. 성을 뺀 이름("길동 씨")이나 별명은
    못 잡는다 — 사업주 화면에 "AI에 보낼 문장에는 이름 대신 '근로자'라고 써 달라"고 안내한다.
    """

    def __init__(self, names: list[str]):
        self._to_alias: dict[str, str] = {}
        for name in names:
            name = (name or "").strip()
            if len(name) < _MIN_NAME_LEN or name.lower() in _GENERIC_NAMES or name in self._to_alias:
                continue
            self._to_alias[name] = _alias(len(self._to_alias))
        self._to_name = {a: n for n, a in self._to_alias.items()}
        # 긴 것부터 맞춰야 "김근로"와 "김근"이 함께 있을 때 짧은 쪽이 긴 이름의 일부를 먼저 먹지 않는다.
        # 별칭도 마찬가지("근로자 AA"를 "근로자 A"로 잘못 되돌리지 않게).
        self._mask_re = self._pattern(self._to_alias)
        self._unmask_re = self._pattern(self._to_name)

    @staticmethod
    def _pattern(keys: dict[str, str]) -> re.Pattern | None:
        if not keys:
            return None
        return re.compile("|".join(re.escape(k) for k in sorted(keys, key=len, reverse=True)))

    def mask(self, text: str) -> str:
        if not self._mask_re or not text:
            return text
        return self._mask_re.sub(lambda m: self._to_alias[m.group(0)], text)

    def unmask(self, text: str) -> str:
        if not self._unmask_re or not text:
            return text
        return self._unmask_re.sub(lambda m: self._to_name[m.group(0)], text)

    def mask_obj(self, obj: Any) -> Any:
        return _walk(obj, self.mask)

    def unmask_obj(self, obj: Any) -> Any:
        return _walk(obj, self.unmask)


def _walk(obj: Any, fn) -> Any:
    if isinstance(obj, str):
        return fn(obj)
    if isinstance(obj, dict):
        return {k: _walk(v, fn) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_walk(v, fn) for v in obj]
    return obj


def employer_pseudonymizer(db: Session, employer_id: str) -> Pseudonymizer:
    """사업장 근로자 전원의 이름을 등록 순서대로 별칭에 묶는다.

    직무 원문·제목·문장에는 어느 근로자 이름이든 들어갈 수 있으므로, 대상 근로자 한 명이 아니라 전원을 바꾼다.
    """
    names = db.scalars(
        select(Worker.display_name).where(Worker.employer_id == employer_id)
        .order_by(Worker.created_at, Worker.id)
    ).all()
    return Pseudonymizer(list(names))


# --- 동의 ---------------------------------------------------------------------

def has_active_consent(db: Session, worker_id: str, consent_type: str = CONSENT_AI_PROCESSING) -> bool:
    return db.scalar(select(WorkerConsent.id).where(
        WorkerConsent.worker_id == worker_id,
        WorkerConsent.consent_type == consent_type,
        WorkerConsent.revoked_at.is_(None),
    ).limit(1)) is not None


def workers_with_active_consent(db: Session, worker_ids: list[str],
                                consent_type: str = CONSENT_AI_PROCESSING) -> set[str]:
    if not worker_ids:
        return set()
    return set(db.scalars(select(WorkerConsent.worker_id).where(
        WorkerConsent.worker_id.in_(worker_ids),
        WorkerConsent.consent_type == consent_type,
        WorkerConsent.revoked_at.is_(None),
    )).all())


# --- 접근 감사 -----------------------------------------------------------------

# 같은 사람이 같은 근로자의 같은 화면을 이 시간 안에 다시 보면 새 줄을 쓰지 않는다.
# 대시보드가 3초마다 폴링하므로, 매번 쓰면 화면 하나 열어 둔 것만으로 하루 수만 줄이 쌓인다.
AUDIT_DEDUPE_SECONDS = int(os.getenv("ACCESS_AUDIT_DEDUPE_SECONDS", "60"))


def _utcnow_naive() -> datetime:
    # SQLite DateTime은 시간대를 저장하지 않는다. 비교는 UTC 기준 naive 값끼리 한다.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_access(db: Session, request: Request, user: dict, action: str,
                  worker_id: str | None = None, *, commit: bool = True) -> None:
    """근로자 개인 데이터 열람 기록을 남긴다. 이름 등 식별 정보는 담지 않는다(worker_id만).

    commit=False면 호출한 쪽 트랜잭션(예: 근로자 삭제)에 함께 실린다.
    """
    ip = client_ip(request)
    if AUDIT_DEDUPE_SECONDS > 0:
        since = _utcnow_naive() - timedelta(seconds=AUDIT_DEDUPE_SECONDS)
        q = select(AccessAuditLog.id).where(
            AccessAuditLog.actor_id == user["sub"],
            AccessAuditLog.action == action,
            AccessAuditLog.request_ip == ip,
            AccessAuditLog.at >= since,
        )
        q = q.where(AccessAuditLog.worker_id.is_(None) if worker_id is None
                    else AccessAuditLog.worker_id == worker_id)
        if db.scalar(q.limit(1)) is not None:
            return
    db.add(AccessAuditLog(actor_id=user["sub"], actor_role=user.get("role", "employer"),
                          action=action, worker_id=worker_id, at=_utcnow_naive(), request_ip=ip))
    if commit:
        db.commit()
