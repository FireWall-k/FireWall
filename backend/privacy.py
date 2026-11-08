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
# 그래서 이름 바로 앞에 글자가 붙어 있지 않고, 이름 뒤가 끝·공백·구두점이거나 호칭·조사·어미로 끝날 때만 바꾼다.
# 단, 이 경계 규칙은 낱말과 헷갈릴 수 있는 이름(2음절 한글 이름, COMMON_WORD_NAMES)에만 쓴다.
# 경계 규칙은 "목록에 있는 꼴만 이름으로 본다"는 허용 목록이라, 목록에 없는 꼴("김민지에겐", "김민지라서",
# "팀장김민지가", "김민지와박지수")은 실명이 그대로 해외 LLM으로 갔다(3차 검증 지적: fail-open).
# 3음절 이상 한글 이름이나 띄어쓰기가 든 이름은 일반 낱말과 겹칠 일이 거의 없으므로, 앞뒤를 보지 않고
# 부분 문자열로 모두 바꾼다(fail-closed). 낱말을 잘못 가리는 손해(분해 품질)가 실명 유출보다 훨씬 작다.
_WORD_CHAR = r"[가-힣A-Za-z0-9]"
# 이름 뒤에 붙는 호칭과 애칭 접사("길동이가"의 '이'). 호칭은 "하나 씨"처럼 띄어 써도 이름이 분명하다.
_HONORIFIC = r"(?:선생님|씨|님)"
# 이름 뒤에 올 수 있는 조각(호칭·접사·조사·보조사·서술격 어미). 한국어는 이것들이 겹쳐 붙는다
# ("김민지에게는"="에게"+"는", "김민지님께서는"="님"+"께서"+"는", "김민지는요"="는"+"요").
# 예전에는 접사 하나 + 조사 하나까지만 봐서 겹친 꼴의 실명이 그대로 해외 LLM으로 갔다(검증 지적).
# 그래서 이 조각이 몇 개(_MAX_TAIL_PIECES까지) 이어진 뒤 낱말이 끝나면 이름으로 본다.
# 목록에 없는 조각으로 이어지면("민지동") 다른 낱말로 보고 바꾸지 않는다 — 그래서 목록은 넉넉히 둔다.
# (이 허용 목록은 이제 2음절 한글 이름에만 쓴다. 3음절 이상 이름은 앞뒤와 상관없이 바꾼다 — _needs_boundary.)
_TAIL_PIECES = sorted({
    # 호칭·접사·복수
    "씨", "님", "이", "선생님", "쌤", "양", "군", "들", "네",
    # 격조사
    "가", "은", "는", "을", "를", "의", "에", "에서", "에게", "에게서", "한테", "한테서", "께", "께서",
    "더러", "보고", "로", "으로", "와", "과", "랑", "이랑", "하고", "아", "야", "여", "이여",
    # 보조사
    "도", "만", "요", "이요", "처럼", "같이", "만큼", "보다", "부터", "까지", "마다", "대로", "조차", "마저",
    "밖에", "뿐", "야말로", "이야말로", "나", "이나", "나마", "이나마", "라도", "이라도", "든", "이든",
    "든지", "이든지", "라고", "이라고", "라는", "이라는", "라면", "이라면",
    # 서술격 조사 '이다'의 활용("김민지예요", "김민지였어요", "김민지이고")
    "다", "이다", "입니다", "이에요", "예요", "에요", "이야", "이고", "고", "이며", "며", "이지", "지",
    "이죠", "죠", "지요", "인데", "인", "이니", "니", "였", "이었", "어", "어요", "었", "던", "습니다",
    # 줄임꼴·구어체(3차 검증에서 2음절 이름의 누출 꼴로 확인됨: "민지에겐", "민지라서", "민지면" …).
    # 3음절 이상 이름은 이 목록과 상관없이 가려지지만, 2음절 이름은 여전히 이 목록에 기댄다.
    "에겐", "한텐", "께선", "에선", "엔", "론", "으론", "로는", "으로는", "이란", "란", "라서", "이라서",
    "면", "이면", "일", "잖아", "이잖아", "잖아요", "이잖아요", "래", "이래", "래요", "이래요", "라", "이라",
    "이니까", "니까", "이므로", "므로", "임", "꺼", "거", "것", "이신", "신", "이세요", "세요", "이시", "시",
    "인지", "이랑은", "이지만", "지만", "이거나", "거나", "이니까요", "니까요", "께도", "에겐요",
}, key=len, reverse=True)  # 긴 것부터 둬야 "에게서"가 "에게"+"서"로 잘려 경계 검사에 걸리지 않는다.
_TAIL_PIECE = "(?:" + "|".join(_TAIL_PIECES) + ")"
_MAX_TAIL_PIECES = 4
_STRICT_TAIL = rf"(?:{_TAIL_PIECE}){{0,{_MAX_TAIL_PIECES}}}(?!{_WORD_CHAR})"
_LATIN_RE = re.compile(r"[A-Za-z]")
_HANGUL_RE = re.compile(r"[가-힣]")
_HANGUL_SYLLABLES_FOR_SUBSTRING = 3
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


def _needs_boundary(name: str) -> bool:
    """경계 규칙(앞 글자·뒤 조각 허용 목록)으로만 가려야 하는 이름인지.

    True: 2음절 이하 한글 이름, COMMON_WORD_NAMES — 부분 문자열로 바꾸면 일반 낱말이 망가진다.
    False: 3음절 이상 한글 이름, 띄어쓰기가 든 이름 — 앞뒤와 상관없이 모두 바꾼다(fail-closed).
    성(姓)으로 시작하는 2음절 이름은 일부러 경계 규칙에 남겼다. "정리"·"이상"·"조금"·"한번"처럼 성으로
    시작하는 2음절 낱말이 많아, 부분 문자열로 바꾸면 분해 입력이 크게 망가진다.
    라틴 문자 이름은 이 함수와 별개로 라틴 글자 경계만 본다(_pattern 참고).
    """
    if name in COMMON_WORD_NAMES:
        return True
    if re.search(r"\s", name):
        return False
    return len(_HANGUL_RE.findall(name)) < _HANGUL_SYLLABLES_FOR_SUBSTRING


def is_ambiguous_name(name: str) -> bool:
    """일반 낱말과 같아 호칭이 붙은 경우만 가릴 수 있는 이름인지(사업주 화면 경고용)."""
    return (name or "").strip() in COMMON_WORD_NAMES


class Pseudonymizer:
    """요청 하나 안에서 실명 ↔ 별칭을 안정적으로 바꾼다.

    한계(문서화):
    - 등록된 표시 이름과 글자가 똑같을 때만 바꾼다. 성을 뺀 이름("길동 씨")이나 별명은 못 잡는다 —
      사업주 화면에 "AI에 보낼 문장에는 이름 대신 '근로자'라고 써 달라"고 안내한다.
    - 3음절 이상 한글 이름·띄어쓰기가 든 이름은 앞뒤를 보지 않고 부분 문자열로 모두 바꾼다(fail-closed).
      그래서 "홍길동동"처럼 이름을 품은 다른 낱말도 바뀐다 — 분해 품질이 조금 나빠질 수 있지만 실명은 나가지 않는다.
    - 2음절 한글 이름은 이름이 아닌 낱말을 바꾸지 않으려고 경계(앞은 글자가 아니고, 뒤는 끝이거나 호칭·조사·어미
      조각이 이어지다 끝남 — _TAIL_PIECES)를 둔다. 목록에 없는 조각이 붙은 꼴은 놓칠 수 있다(남은 위험).
      그래도 "하나가 남았다"처럼 낱말 + 조사 꼴은 바꿀 수 있어, 일반 낱말과 같은 이름은 호칭이
      붙은 경우만 바꾼다(COMMON_WORD_NAMES).
    - 라틴 문자 이름은 앞뒤에 라틴 글자가 붙지 않았을 때 바꾼다("Johnson"은 그대로, "John에겐"은 바꾼다).
    - 되돌리기(unmask)는 이 요청에서 mask()가 실제로 만든 별칭만 실명으로 되돌린다. 사업주가 원문에 직접 쓴
      "근로자 B" 같은 글은 그대로 둔다(3차 검증 지적: 사업주 글이 몰래 바뀌었다).
    """

    def __init__(self, names: list[str]):
        self._to_alias: dict[str, str] = {}
        for name in names:
            name = (name or "").strip()
            too_short = len(name) < _MIN_NAME_LEN and name not in COMMON_WORD_NAMES
            # 라틴 문자 이름은 대소문자만 다른 것("John"/"john")을 같은 사람으로 본다 — 패턴이 대소문자를
            # 가리지 않으므로 별칭을 둘 만들어 봐야 한쪽만 쓰인다.
            if _LATIN_RE.search(name):
                seen = name.lower() in {n.lower() for n in self._to_alias}
            else:
                seen = name in self._to_alias
            if too_short or name.lower() in _GENERIC_NAMES or seen:
                continue
            self._to_alias[name] = _alias(len(self._to_alias))
        self._to_name = {a: n for n, a in self._to_alias.items()}
        # 라틴 문자 이름은 대소문자를 가리지 않고 맞춘다("John"으로 등록해도 문장에는 "john"이 올 수 있다).
        # 맞은 글자 그대로는 _to_alias에 없으므로 소문자 키로 찾는다.
        self._to_alias_ci = {n.lower(): a for n, a in self._to_alias.items() if _LATIN_RE.search(n)}
        # 긴 것부터 맞춰야 "김근로"와 "김근"이 함께 있을 때 짧은 쪽이 긴 이름의 일부를 먼저 먹지 않는다.
        self._mask_re = self._pattern(self._to_alias)
        # 이 요청에서 mask()가 실제로 만든 별칭과, 가리기 전 원문에 사업주가 직접 쓴 별칭 모양의 글.
        # unmask()는 앞의 것만 실명으로 되돌리고, 뒤의 것은 사업주 글이므로 손대지 않는다.
        self._produced: set[str] = set()
        self._written: set[str] = set()

    @staticmethod
    def _pattern(keys: dict[str, str]) -> re.Pattern | None:
        if not keys:
            return None
        alts = []
        for k in sorted(keys, key=len, reverse=True):
            name = re.escape(k)
            if _LATIN_RE.search(k):
                name = rf"(?i:{name})"
            if k in COMMON_WORD_NAMES:
                alts.append(rf"(?<!{_WORD_CHAR}){name}(?=\s?{_HONORIFIC})")
            elif not _needs_boundary(k):
                # 낱말과 헷갈릴 일이 없는 이름: 앞뒤를 보지 않는다. 다만 라틴 글자로 시작·끝나는 이름은
                # 그 끝에서만 라틴 글자 경계를 본다("Kim 민수"가 "Kimchi"에 걸리지 않게).
                pre = r"(?<![A-Za-z])" if _LATIN_RE.match(k) else ""
                post = r"(?![A-Za-z])" if _LATIN_RE.search(k[-1]) else ""
                alts.append(rf"{pre}{name}{post}")
            elif _LATIN_RE.search(k) and not _HANGUL_RE.search(k):
                # 라틴 문자 이름: 한국어 조사는 바로 붙어 쓰므로("John에겐") 라틴 글자 경계만 본다.
                alts.append(rf"(?<![A-Za-z0-9]){name}(?![A-Za-z0-9])")
            else:
                alts.append(rf"(?<!{_WORD_CHAR}){name}(?={_STRICT_TAIL})")
        return re.compile("|".join(alts))

    def _alias_for(self, matched: str) -> str:
        alias = self._to_alias.get(matched)
        return alias if alias is not None else self._to_alias_ci[matched.lower()]

    def mask(self, text: str) -> str:
        if not text:
            return text
        if "근로자" in text:
            self._written.update(_alias_key(m) for m in _ALIAS_RE.finditer(text))
        if not self._mask_re:
            return text

        def _sub(m: re.Match) -> str:
            alias = self._alias_for(m.group(0))
            self._produced.add(alias)
            return alias

        return self._mask_re.sub(_sub, text)

    def unmask(self, text: str) -> str:
        if not text or "근로자" not in text:
            return text
        leftovers: list[str] = []

        def _restore(m: re.Match) -> str:
            key = _alias_key(m)
            if key in self._produced:
                return self._to_name[key]
            # 사업주가 원문에 직접 쓴 글("근로자 B")이 응답에 그대로 돌아온 것. 사업주 글이므로 바꾸지 않는다.
            if key in self._written:
                return m.group(0)
            # 이 요청에서 만든 적 없는 별칭(LLM이 지어낸 "근로자 C", 이번 요청 원문에 없던 근로자의 별칭 등).
            # 그대로 두면 근로자 화면·TTS에 별칭이 나가므로 일반 낱말 "근로자"로 바꾸고 경고를 남긴다.
            # 원문에 없던 근로자의 별칭을 실명으로 되돌리지 않는 것은, LLM이 지어낸 글자가 우연히 다른 근로자의
            # 별칭과 같을 때 엉뚱한 실명이 화면에 나가지 않게 하려는 것이다.
            # 단 알파벳 한 글자일 때만 그렇게 본다. "근로자 ID"·"근로자 OK"·"근로자 TV"처럼 두 글자 이상의
            # 대문자는 평범한 문장일 가능성이 훨씬 커서, 지우면 코칭·분해 결과가 망가진다(검증 지적).
            # 두 글자 별칭(근로자 AA…)은 이 요청에서 실제로 만든 것만 위에서 되돌린다.
            if len(m.group(1)) != 1:
                return m.group(0)
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


def _alias_key(m: re.Match) -> str:
    # "근로자A"·"근로자  A"처럼 띄어쓰기만 다른 꼴도 같은 별칭으로 본다.
    return f"근로자 {m.group(1)}"


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
    # 사업주 화면 도움 알림 띠가 5초마다 부른다(근로자 이름이 실린다).
    "help.list",
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


def record_access_for_workers(db: Session, request: Request, user: dict, action: str,
                              worker_ids, *, commit: bool = True) -> None:
    """여러 근로자의 기록이 함께 보이는 화면(집계 대시보드·배정 근로자 목록·집계 코칭)의 열람 기록.

    worker_id=None 한 줄만 남기면 "누구의 기록을 봤는지"를 나중에 추적할 수 없다(검증 지적). 화면에 실린
    근로자마다 한 줄씩 남긴다. 실린 근로자가 없으면 열람 사실만 남게 worker_id=None 한 줄을 쓴다.
    폴링 묶기(DEDUPED_ACTIONS)는 근로자별로 따로 적용된다.
    """
    ids = sorted({w for w in worker_ids if w})
    if not ids:
        record_access(db, request, user, action, None, commit=commit)
        return
    for wid in ids:
        record_access(db, request, user, action, wid, commit=False)
    if commit:
        db.commit()
