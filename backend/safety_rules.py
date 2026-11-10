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

# 어절 끝에 붙는 조사(긴 것부터). '커터칼로'→'커터칼', '세제를'→'세제'.
_JOSA = ("으로는", "에서는", "이랑", "에서", "으로", "에게", "하고", "까지", "부터", "처럼", "이나",
         "은", "는", "이", "가", "을", "를", "에", "로", "와", "과", "도", "만", "랑", "나", "의")
_WORD_RE = re.compile(r"[가-힣A-Za-z0-9]+")
# 조심 낱말이 들어 있지만 다른 뜻인 말(어절 안에 들어 있으면 그 어절은 걸지 않는다).
# 칼슘·칼라·칼집(음식에 칼집 낸)·불만·사다리꼴·가위표처럼 흔한 말에 '조심해요' 띠가 붙지 않게 한다 — 자동 표시는
# 사업주 확인 없이 근로자에게 가므로(창업자 결정) 거짓 양성도 그대로 근로자 화면에 뜬다.
_NOT_HAZARD = ("칼로리", "칼국수", "가위바위보", "칼슘", "칼라", "칼집", "칼퇴", "칼칼", "불만", "불만족",
               "사다리꼴", "가위표", "세제곱", "전기세")
# '불'로 끝나는 불 합성어(가스불·장작불…). '이불'처럼 불이 아닌 말은 넣지 않는다(목록에 있는 것만 받는다).
_FIRE_COMPOUNDS = ("가스불", "장작불", "촛불", "모닥불", "숯불", "연탄불", "화롯불", "불꽃", "불길")


def _stem(word: str) -> str:
    for j in _JOSA:
        if len(word) > len(j) and word.endswith(j):
            return word[: -len(j)]
    return word


def _hits_word(word: str) -> str | None:
    if any(x in word for x in _NOT_HAZARD):
        return None
    stem = _stem(word)
    # '뜨거운'은 활용형까지: 뜨거- 줄기(뜨거운·뜨거워요·뜨거우니)와 뜨겁- 줄기(뜨겁다·뜨겁게·뜨겁습니다).
    if word.startswith(("뜨거", "뜨겁")):
        return "뜨거운"
    # '불'은 그 낱말 하나일 때와 정해 둔 불 합성어만(불량·불판·이불 같은 다른 말에 걸리지 않게).
    if stem == "불" or any(word.startswith(c) for c in _FIRE_COMPOUNDS):
        return "불"
    for kw in ("칼날", "칼", "가위", "세제", "락스", "기계", "사다리", "전기"):
        if kw in stem:
            return kw
    return None


def matched_keyword(sentence: str) -> str | None:
    """문장에서 처음 걸린 조심 낱말(없으면 None)."""
    for word in _WORD_RE.findall(sentence or ""):
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
