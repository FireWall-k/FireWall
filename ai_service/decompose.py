"""규칙 기반 분해기 (LLM 자리표시자).

스켈레톤 단계에서는 실제 LLM 대신 규칙으로 단계를 만든다. 중요한 건 *출력의 모양*과
*검증 흐름*이다. M2에서 이 함수 내부만 LLM 호출+프롬프트로 교체하면 바깥 계약은 유지된다.

평가 반영 — 분할 규칙 개선:
- 기존: 모든 쉼표에서 분할 → 나열형 문장("사과, 배, 귤")이 깨졌다.
- 변경: (1) 문장부호, (2) 순서 접속어(그리고/그다음/그 후/이후 등),
        (3) 순차 연결어미+쉼표("~하고," "~한 뒤," "~한 후," "~한 다음,")에서만 분할.
        단순 나열 쉼표는 분할하지 않아 한 단계로 유지한다.
"""
from __future__ import annotations

import logging
import re

import llm
from schemas import DecomposeResult, Keyword, Step

logger = logging.getLogger("ai_harness.decompose")

_ACTION_HINTS = {
    "move": ["옮기", "옮겨", "이동", "넣", "빼", "꺼내", "가져"],
    "stack": ["쌓", "적재", "포개"],
    "sort": ["분류", "나누", "구분", "정리"],
    "pack": ["담", "포장", "싸"],
    "clean": ["닦", "청소", "씻", "치우"],
    "observe": ["보", "확인", "살펴", "점검", "세"],
}

# 순서를 나타내는 접속어(단독 구분자). 긴 표현을 먼저 둬야 부분매칭을 막는다.
_SEQ_CONNECTIVES = [
    "그리고 나서", "그러고 나서", "그런 다음", "그 다음에", "그다음에",
    "그 다음", "그다음", "그 후에", "그후에", "그 후", "그후",
    "그리고", "이후에", "그러고", "다음으로",
]

# "~고," 앞이 동작 동사가 아니라 형용사면 나열로 보고 분할하지 않는다.
# (예: "깨끗하고, 빠르게" 는 한 단계로 유지. "분류하고, 옮겨" 는 분할.)
_ADJ_STEMS = {
    "깨끗", "튼튼", "조용", "깔끔", "안전", "빠르", "느리", "단단", "부드럽",
    "따뜻", "차갑", "무겁", "가볍", "크", "작", "많", "적", "좋", "나쁘",
    "예쁘", "더럽", "넓", "좁", "높", "낮", "두껍", "얇", "밝", "어둡",
    "정확", "확실", "꼼꼼", "신선",
}

# "~고," 외의 순차 종결(쉼표가 있어야 단순 나열과 구분된다).
_SEQ_SUFFIXES = ("고", "뒤", "후", "다음")


def _guess_action(sentence: str) -> str:
    for action, hints in _ACTION_HINTS.items():
        if any(h in sentence for h in hints):
            return action
    return "other"


def _extract_keywords(sentence: str) -> list[Keyword]:
    words = re.findall(r"[가-힣A-Za-z0-9]+", sentence)
    keywords: list[Keyword] = []
    for w in words:
        if len(w) < 2:
            continue
        pos = "verb" if any(h in w for hs in _ACTION_HINTS.values() for h in hs) else "noun"
        keywords.append(Keyword(term=w, pos=pos))
    return keywords[:4]


def _is_adjective_go(word: str) -> bool:
    """'~고'로 끝나는 단어가 형용사 연결인지 추정한다(분할 억제용)."""
    stem = word[:-1] if word.endswith("고") else word
    if stem.endswith("하"):  # 깨끗하-, 정확하-
        stem = stem[:-1]
    return stem in _ADJ_STEMS


def _split_sequential(clause: str) -> list[str]:
    """절을 순차 경계('~고,' '~뒤,' '~후,' '~다음,')에서 분할한다.

    쉼표 앞 단어가 순차 종결이어야만 분할하고, 형용사 '~고'는 나열로 보고 유지한다.
    단순 나열 쉼표("사과, 배, 귤")는 어느 규칙에도 안 걸려 한 단계로 남는다.
    """
    pieces: list[str] = []
    start = 0
    for m in re.finditer(r",\s*", clause):
        before = clause[:m.start()].rstrip()
        last = re.search(r"[가-힣]+$", before)
        if not last:
            continue
        word = last.group(0)
        suffix = next((s for s in _SEQ_SUFFIXES if word.endswith(s)), None)
        if suffix is None:
            continue
        if suffix == "고" and _is_adjective_go(word):
            continue  # 형용사 연결 → 나열로 유지
        pieces.append(clause[start:m.start()].strip().strip(","))
        start = m.end()
    pieces.append(clause[start:].strip().strip(","))
    return [p for p in pieces if p]


def _split_steps(text: str) -> list[str]:
    """직무 원문을 단계 문자열 리스트로 분할한다(개선된 규칙)."""
    # 1) 문장부호로 1차 분할
    sentences = re.split(r"[.!?\n]+", text)

    # 2) 순서 접속어로 분할(앞뒤 공백/쉼표 허용)
    conn_pattern = r"\s*(?:%s)[\s,]+" % "|".join(re.escape(c) for c in _SEQ_CONNECTIVES)

    chunks: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        for part in re.split(conn_pattern, sentence):
            part = part.strip()
            if not part:
                continue
            # 3) 순차 연결어미 + 쉼표에서 분할(형용사 '~고'는 제외)
            chunks.extend(_split_sequential(part))
    return chunks


def _rule_decompose(raw_input: str, context: dict) -> DecomposeResult:
    """규칙 기반 분해(LLM 미사용/실패 시 폴백)."""
    text = raw_input.strip()
    chunks = _split_steps(text)

    steps: list[Step] = []
    for i, chunk in enumerate(chunks, start=1):
        sentence = chunk if chunk.endswith(("요", "다", ".", "!", "?")) else chunk + "."
        steps.append(Step(
            order=i,
            sentence=sentence,
            keywords=_extract_keywords(chunk),
            action_type=_guess_action(chunk),
            safety_flags=[],
        ))

    title = (chunks[0][:20] if chunks else "직무")
    return DecomposeResult(task_title=title, steps=steps)


_VALID_ACTIONS = {"observe", "move", "stack", "sort", "pack", "clean", "other"}
_MAX_STEPS = 10
_MAX_SENTENCE = 120


def _build_from_llm(raw: dict) -> DecomposeResult:
    """LLM JSON → DecomposeResult. 가드레일: 형식/길이/개수 정규화 후 통과."""
    raw_steps = raw.get("steps") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("LLM 응답에 steps가 없습니다.")

    steps: list[Step] = []
    for i, s in enumerate(raw_steps[:_MAX_STEPS], start=1):
        sentence = str(s.get("sentence", "")).strip()
        if not sentence:
            continue
        sentence = sentence[:_MAX_SENTENCE]
        action = s.get("action_type", "other")
        if action not in _VALID_ACTIONS:
            action = "other"
        symbol_query = [str(t).strip() for t in (s.get("symbol_query") or []) if str(t).strip()][:3]
        flags = [str(f).strip() for f in (s.get("safety_flags") or []) if str(f).strip()]
        keywords = [Keyword(term=t, pos="noun") for t in symbol_query] or _extract_keywords(sentence)
        steps.append(Step(
            order=i, sentence=sentence, keywords=keywords,
            symbol_query=symbol_query, action_type=action, safety_flags=flags,
        ))

    if not steps:
        raise ValueError("LLM 응답에서 유효한 단계를 만들지 못했습니다.")
    title = str(raw.get("task_title") or steps[0].sentence)[:40]
    return DecomposeResult(task_title=title, steps=steps)


def decompose(raw_input: str, context: dict) -> DecomposeResult:
    """원문을 단계 배열로 분해한다.

    LLM이 설정돼 있으면 맥락적응 분해를 시도하고, 실패하면 규칙 기반으로 폴백한다.
    빈 입력은 main.py 가드레일에서 걸러진다.
    """
    if llm.llm_available():
        try:
            result = _build_from_llm(llm.llm_decompose(raw_input, context))
            logger.info("decompose via LLM: %s steps", len(result.steps))
            return result
        except Exception as e:  # noqa: BLE001 - LLM 실패 시 규칙 기반으로 폴백
            logger.warning("LLM decompose 실패, 규칙 기반 폴백: %s", e)

    return _rule_decompose(raw_input, context)
