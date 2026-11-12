"""단계 '조심해요' 자동 제안(2b-1, contract §3.3).

- ai_service가 단계의 safety_flags(위험 요소 글)를 주면 그것을 따르고, 없으면 아래 낱말 10개로 정한다.
  사업주 화면에는 '✦ 자동 제안'(보라)으로 보이고, 사업주 확인 없이 근로자에게 간다(창업자 결정: 보내기를 막지 않음).
  보내기 시트는 '✦ 자동으로 켠 조심 표시가 N개 있어요' 경고로 알린다(send.send_check의 auto_caution).
- 사업주가 스위치를 바꾸면 source='manual'이고, 그 뒤 문장을 고쳐도 자동으로 다시 정하지 않는다.
- 근로자 응답에는 flag만 간다(source·note는 사업주 화면용).
- 규칙만 쓴다(유료 모델 호출 없음). 이 모듈은 main을 import하지 않는다.
"""
from __future__ import annotations

import re

# contract §3.3의 낱말 10개. 순서는 화면·시험에서 그대로 쓴다.
KEYWORDS: tuple[str, ...] = ("칼", "가위", "뜨거운", "불", "세제", "락스", "기계", "칼날", "사다리", "전기")

SOURCE_AUTO = "auto"
SOURCE_MANUAL = "manual"

# 어절 끝에 붙는 조사(긴 것부터). '커터칼로'→'커터칼', '세제를'→'세제', '불에는'→'불'.
_JOSA = ("으로는", "에서는", "이에요", "에는", "에도", "보다", "한테", "이랑", "에서", "으로", "에게", "하고",
         "까지", "부터", "처럼", "이나", "이야", "이요",
         "은", "는", "이", "가", "을", "를", "에", "엔", "로", "와", "과", "도", "만", "랑", "나", "의")
_WORD_RE = re.compile(r"[가-힣A-Za-z0-9]+")
# 조심 낱말이 들어 있지만 다른 뜻인 말. 조사를 한 번 뗀 줄기 안에 들어 있으면 그 어절은 걸지 않는다.
# 칼슘·칼라·칼집(음식에 칼집 낸)·불만·사다리꼴·가위표처럼 흔한 말에 '조심해요' 띠가 붙지 않게 한다 — 자동 표시는
# 사업주 확인 없이 근로자에게 가므로(창업자 결정) 거짓 양성도 그대로 근로자 화면에 뜬다.
# (2회차 검증) 어절 전체가 아니라 줄기로 본다: '가스불만'(가스불+만)·'불만 끄고'(불+만)를 놓치지 않게.
_NOT_HAZARD = ("칼로리", "칼국수", "가위바위보", "칼슘", "칼라", "칼집", "칼퇴", "칼칼", "불만", "불만족",
               "사다리꼴", "가위표", "세제곱", "전기세", "불가")
# (3회차 검증) 불 합성어(모닥불가·숯불가 = 모닥불 곁)는 위 거름말('불가')보다 먼저 본다.
# 위 거름말로 시작하지만 진짜 위험 낱말인 말(전기세탁기 ⊃ 전기세).
_HAZARD_OVERRIDES = ("전기세탁", "전기세척")
# 조사 없이 홀로 쓰여 '불+만/가/과'로 읽히는 말. 그대로면 다른 뜻(불만 접수·출입 불가·불과 5분)이라 걸지 않는다.
# 단 '불만 끄고'처럼 다음 어절이 불을 다루는 말이면 '불'+조사 '만'이다(matched_keyword가 본다).
_BARE_NOT_FIRE = ("불만", "불가", "불과")
# '때'(불을 때다)는 활용형으로만 받는다 — '불만 때문에'의 '때문'을 불 다루는 말로 보지 않게(3회차 검증).
_FIRE_VERBS = ("끄", "꺼", "켜", "켠", "붙", "피우", "피워", "조심",
               "때요", "때고", "때면", "때서", "때야", "때세요", "때주", "땐다", "땠", "때워", "때우")
# 불 합성어(가스불·장작불·불씨·불조심…). '이불'·'불량'처럼 불이 아닌 말은 넣지 않는다(목록에 있는 것만 받는다).
_FIRE_COMPOUNDS = ("가스불", "장작불", "촛불", "모닥불", "숯불", "연탄불", "화롯불", "난롯불", "불꽃", "불길",
                   "불조심", "불씨", "불붙", "불티", "불끄", "불꺼", "불켜", "불켠")


def _stem(word: str) -> str:
    for j in _JOSA:
        if len(word) > len(j) and word.endswith(j):
            return word[: -len(j)]
    return word


def _hits_word(word: str) -> str | None:
    stem = _stem(word)
    if word in _BARE_NOT_FIRE:
        return None
    if any(word.startswith(c) for c in _FIRE_COMPOUNDS):
        return "불"
    if any(x in stem for x in _NOT_HAZARD) and not any(stem.startswith(o) for o in _HAZARD_OVERRIDES):
        return None
    # '뜨거운'은 활용형까지: 뜨거- 줄기(뜨거운·뜨거워요·뜨거우니)와 뜨겁- 줄기(뜨겁다·뜨겁게·뜨겁습니다).
    if word.startswith(("뜨거", "뜨겁")):
        return "뜨거운"
    # '불'은 그 낱말 하나일 때와 정해 둔 불 합성어만(불량·불판·이불 같은 다른 말에 걸리지 않게).
    if stem == "불":
        return "불"
    for kw in ("칼날", "칼", "가위", "세제", "락스", "기계", "사다리", "전기"):
        if kw in stem:
            return kw
    return None


def matched_keyword(sentence: str) -> str | None:
    """문장에서 처음 걸린 조심 낱말(없으면 None)."""
    words = _WORD_RE.findall(sentence or "")
    for i, word in enumerate(words):
        if word in _BARE_NOT_FIRE and i + 1 < len(words) and words[i + 1].startswith(_FIRE_VERBS):
            return "불"  # '불만 끄고 나가요' — 불 + 조사 '만'
        hit = _hits_word(word)
        if hit:
            return hit
    return None


def auto_flag(sentence: str, ai_flags=None) -> bool:
    """자동 제안: ai_service의 safety_flags가 있으면 그것, 없으면 낱말 규칙."""
    if isinstance(ai_flags, list) and any(str(f).strip() for f in ai_flags):
        return True
    return matched_keyword(sentence) is not None


def apply_auto(step, sentence: str, ai_flags=None) -> None:
    """사업주가 직접 정하지 않은 단계(source != manual)에 자동 제안을 다시 매긴다."""
    if getattr(step, "safety_source", "") == SOURCE_MANUAL:
        return
    flag = auto_flag(sentence, ai_flags)
    step.safety_flag = flag
    step.safety_source = SOURCE_AUTO if flag else ""


def is_unconfirmed_auto(step) -> bool:
    """보내기 시트 auto_caution 경고에 세는 단계: 자동으로 켰고 사업주가 아직 손대지 않음."""
    return bool(step.safety_flag) and (step.safety_source or "") == SOURCE_AUTO
