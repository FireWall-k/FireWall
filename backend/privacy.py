"""개인정보 보호 도구 (Phase 0.2).

- Pseudonymizer: AI 하네스(→ 해외 LLM·임베딩)로 보내기 전에 근로자 실명을 "근로자 A" 같은 별칭으로 바꾸고,
  응답에서 다시 실명으로 되돌린다. 매핑은 요청 하나 안에서만 쓰고 저장하지 않는다.
- 동의: 근로자별 동의 기록(WorkerConsent) 중 AI 처리 동의가 살아 있는지 확인한다.
- 접근 감사: 사업주가 근로자 개인 데이터를 볼 때 AccessAuditLog에 한 줄 남긴다.

무엇이 어디로 가는지는 docs/privacy/data-map.md에 정리돼 있다. 여기를 바꾸면 그 문서도 고친다.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from models import AccessAuditLog, Worker, WorkerConsent
from ratelimit import client_ip

logger = logging.getLogger("jobcard.privacy")

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


# 이름 앞뒤 경계. 표시 이름을 단순 부분 문자열로 바꾸면 "하나" 같은 이름이 "하나씩"·"하나하나"의 낱말까지
# 별칭으로 바꿔 LLM 분해 입력과 그림 검색 질의를 망가뜨린다("컵을 근로자 A씩 꺼내서…").
# 그래서 이름 바로 앞에 글자가 붙어 있지 않고, 이름 뒤가 끝·공백·구두점이거나 호칭·조사로 끝날 때만 바꾼다.
_WORD_CHAR = r"[가-힣A-Za-z0-9]"
# 이름 뒤에 붙는 호칭과 애칭 접사("길동이가"의 '이'). 호칭은 "하나 씨"처럼 띄어 써도 이름이 분명하다.
_HONORIFIC = r"(?:선생님|씨|님)"
_NAME_SUFFIX = r"(?:씨|님|이)"
# 자주 쓰는 조사. 길이가 긴 것부터 둬야 "에게서"가 "에게"+"서"로 잘려 경계 검사에 걸리지 않는다.
_PARTICLES = sorted([
    "이", "가", "은", "는", "을", "를", "의", "도", "만", "와", "과", "랑", "이랑", "하고",
    "에게", "에게서", "한테", "한테서", "께", "께서", "아", "야", "에", "로", "으로", "처럼",
    "보다", "부터", "까지", "이나", "나", "이랑", "이에요", "예요", "이고", "고", "이며", "며",
], key=len, reverse=True)
_PARTICLE = "(?:" + "|".join(_PARTICLES) + ")"
_STRICT_TAIL = rf"(?:{_NAME_SUFFIX}?{_PARTICLE}?)(?!{_WORD_CHAR})"
# 일반 낱말·수사와 글자가 같은 이름. 이런 이름은 "컵 하나 꺼내세요"처럼 경계 규칙을 지켜도 낱말과
# 구분할 수 없으므로 "하나 씨"·"하나님께"처럼 호칭이 붙은 경우만 바꾼다. 사업주 화면에도 경고한다
# (WorkerOut.name_ambiguous). 목록에 없는 2음절 이름도 낱말과 겹칠 수 있어 문서에 한계로 적었다.
COMMON_WORD_NAMES = frozenset({
    "하나", "한나", "보람", "나라", "슬기", "한결", "사랑", "기쁨", "다솜", "하늘", "바다", "누리",
    "가람", "나래", "다운", "마루", "새봄", "여름", "가을", "겨울", "소망", "은혜", "믿음", "소리",
    "노을", "구름", "바람", "이슬", "단비", "아름", "한빛", "빛나", "초롱", "미소", "진주", "보배",
    "우리", "다정", "행복", "희망", "평화", "자유", "정의", "한울", "새벽", "아침", "온유", "가온",
    "나리", "수정", "지혜", "용기", "마음", "한별", "은별", "별", "봄", "샘", "솔", "결", "빛",
    "참", "꽃", "다올", "새롬", "한솔", "푸름", "고운", "예쁨", "든솔", "단아", "현명", "성실",
})
# LLM이 별칭을 "근로자A"·"근로자  A"처럼 띄어쓰기만 바꿔 돌려주는 경우까지 되돌린다.
# 알파벳을 끝까지 한 덩어리로 읽어야 "근로자 AA"를 "근로자 A"로 잘못 되돌리지 않는다.
_ALIAS_RE = re.compile(r"근로자\s*([A-Z]+)(?![A-Za-z])")


def is_ambiguous_name(name: str) -> bool:
    """일반 낱말과 같아 호칭이 붙은 경우만 가릴 수 있는 이름인지(사업주 화면 경고용)."""
    return (name or "").strip() in COMMON_WORD_NAMES


class Pseudonymizer:
    """요청 하나 안에서 실명 ↔ 별칭을 안정적으로 바꾼다.

    한계(문서화):
    - 등록된 표시 이름과 글자가 똑같을 때만 바꾼다. 성을 뺀 이름("길동 씨")이나 별명은 못 잡는다 —
      사업주 화면에 "AI에 보낼 문장에는 이름 대신 '근로자'라고 써 달라"고 안내한다.
    - 반대로 이름이 아닌 낱말을 바꾸지 않으려고 경계(앞은 글자가 아니고, 뒤는 호칭·조사·끝)를 둔다.
      그래도 "하나가 남았다"처럼 낱말 + 조사 꼴은 바꿀 수 있어, 일반 낱말과 같은 이름은 호칭이
      붙은 경우만 바꾼다(COMMON_WORD_NAMES).
    """

    def __init__(self, names: list[str]):
        self._to_alias: dict[str, str] = {}
        for name in names:
            name = (name or "").strip()
            too_short = len(name) < _MIN_NAME_LEN and name not in COMMON_WORD_NAMES
            if too_short or name.lower() in _GENERIC_NAMES or name in self._to_alias:
                continue
            self._to_alias[name] = _alias(len(self._to_alias))
        self._to_name = {a: n for n, a in self._to_alias.items()}
        # 긴 것부터 맞춰야 "김근로"와 "김근"이 함께 있을 때 짧은 쪽이 긴 이름의 일부를 먼저 먹지 않는다.
        self._mask_re = self._pattern(self._to_alias)

    @staticmethod
    def _pattern(keys: dict[str, str]) -> re.Pattern | None:
        if not keys:
            return None
        alts = []
        for k in sorted(keys, key=len, reverse=True):
            if k in COMMON_WORD_NAMES:
                tail = rf"(?=\s?{_HONORIFIC})"
            else:
                tail = rf"(?={_STRICT_TAIL})"
            alts.append(rf"(?<!{_WORD_CHAR}){re.escape(k)}{tail}")
        return re.compile("|".join(alts))

    def mask(self, text: str) -> str:
        if not self._mask_re or not text:
            return text
        return self._mask_re.sub(lambda m: self._to_alias[m.group(0)], text)

    def unmask(self, text: str) -> str:
        if not text or "근로자" not in text:
            return text
        leftovers: list[str] = []

        def _restore(m: re.Match) -> str:
            name = self._to_name.get(f"근로자 {m.group(1)}")
            if name is not None:
                return name
            # 이 요청에서 만든 적 없는 별칭(LLM이 지어낸 "근로자 C" 등). 그대로 두면 근로자 화면·TTS에
            # 별칭이 나가므로 일반 낱말 "근로자"로 바꾸고 경고를 남긴다.
            leftovers.append(m.group(0))
            return "근로자"

        out = _ALIAS_RE.sub(_restore, text)
        if leftovers:
            logger.warning("AI 응답에 되돌릴 수 없는 별칭이 있어 '근로자'로 바꿨습니다: %s", leftovers)
        return out

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
# 묶기는 화면이 저절로 되풀이하는 조회에만 쓴다. 내보내기·삭제·동의 기록·수정은 사람이 한 번씩 하는
# 행위라 60초 안에 두 번 했어도 두 줄이 남아야 한다(두 번 내보냈다는 사실 자체가 감사 대상).
DEDUPED_ACTIONS = frozenset({
    "dashboard.view", "dashboard.workers", "worker.list", "worker.history", "worker.consents",
    "coaching.view",
})


def _utcnow_naive() -> datetime:
    # SQLite DateTime은 시간대를 저장하지 않는다. 비교는 UTC 기준 naive 값끼리 한다.
    return datetime.now(timezone.utc).replace(tzinfo=None)


def record_access(db: Session, request: Request, user: dict, action: str,
                  worker_id: str | None = None, *, commit: bool = True) -> None:
    """근로자 개인 데이터 열람 기록을 남긴다. 이름 등 식별 정보는 담지 않는다(worker_id만).

    commit=False면 호출한 쪽 트랜잭션(예: 근로자 삭제)에 함께 실린다.
    """
    ip = client_ip(request)
    if AUDIT_DEDUPE_SECONDS > 0 and action in DEDUPED_ACTIONS:
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
