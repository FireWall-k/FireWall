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
from collections import Counter, defaultdict
from functools import lru_cache

import llm
import local_aac
from schemas import DecomposeResult, Keyword, Step
from taxonomy import VALID_ACTION_TYPES, VALID_JOBS, infer_job_text

logger = logging.getLogger("ai_harness.decompose")

# 키워드 품사 추정용 동사 어간 힌트(_extract_keywords). 동작 분류(_guess_action)에는 쓰지 않는다 —
# 부분 문자열로 맞추면 "접으세요"의 '세'(세다)·"보관"의 '보'(보다)·"입력"의 '입'(입다)처럼 어미·명사
# 조각이 동작으로 잡힌다(아래 _guess_action 설명 참고).
_ACTION_HINTS = {
    "assemble": ["조립", "결합", "끼우", "연결", "체결", "조이", "맞추", "고정", "부착", "교체"],
    "wear": ["착용", "입", "신", "보안경", "작업모", "장갑"],
    "operate": ["누르", "켜", "끄", "작동", "스위치", "버튼"],
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


# ---- 동작 분류(action_type) ------------------------------------------------------
# 예전 규칙은 힌트 글자가 문장 어디에든 있으면 그 동작으로 봤다. 그래서 거의 모든 지시문 끝의
# "-세요"에 든 '세'(세다)가 observe로 잡혔다 — "박스 바닥 덮개를 접으세요"·"테이프를 붙이세요"가
# 모두 '확인하기'였고, "포장된 상자를 카트에 놓으세요"는 꾸미는 말 '포장된'의 '포장' 때문에 pack이
# 됐다. "입력하세요"는 '입'(입다) 때문에 wear였다. 이 값은 근로자 화면의 동작 꼬리표와 그림 검색의
# 동사 계열 벌점(local_aac._verb_class_penalty)에 그대로 쓰여, 틀린 꼬리표와 맞는 그림 감점을 낳았다.
#
# 지금은 그림 검색과 같은 동사 분석기(local_aac._verb_lemmas: 어미를 확인해 '할 일'의 동사 원형만
# 뽑는다)로 동사를 찾고, 그림 인덱스가 그 동사에 붙인 verb_class로 분류한다. 인덱스와 같은 축을 쓰므로
# 분류와 그림의 동작 계열이 어긋나지 않는다. 확실하지 않으면 other — 화면은 other면 꼬리표를 숨긴다.

# 인덱스에서 한 동사의 verb_class가 이 비율 이상 한쪽으로 모여야 그 계열로 본다. '넣다'(pack 25 /
# move 22 / assemble 6…)·'붙이다'(other 14 / assemble 4 / pack 3…)처럼 갈리는 동사는 other로 둔다 —
# 틀린 계열은 그림 감점(0.85)과 틀린 꼬리표를 낳지만, other는 아무것도 깎지 않는다.
_CLASS_MIN_SHARE = 0.75
_CLASS_MIN_COUNT = 2

# 인덱스 frame.verb에 없지만 지시문에 흔한 동사. 뜻이 한 계열로만 읽히는 것만 둔다(쓰다·들다처럼
# 여러 뜻인 동사는 넣지 않는다).
_EXTRA_VERB_CLASSES = {
    "포장하다": "pack", "밀봉하다": "pack", "싸다": "pack",
    "씻다": "clean", "청소하다": "clean", "쓸다": "clean", "헹구다": "clean", "소독하다": "clean",
    "버리다": "clean",
    "쌓다": "stack", "적재하다": "stack",
    "분류하다": "sort", "나누다": "sort", "구분하다": "sort",
    "옮기다": "move", "꺼내다": "move", "가져오다": "move", "놓다": "move",
    "확인하다": "observe", "점검하다": "observe", "살펴보다": "observe", "세다": "observe",
    "보다": "observe", "읽다": "observe", "검사하다": "observe",
    "착용하다": "wear", "입다": "wear", "신다": "wear", "벗다": "wear",
    "누르다": "operate", "켜다": "operate", "끄다": "operate", "입력하다": "operate",
    "조립하다": "assemble", "끼우다": "assemble", "조이다": "assemble", "체결하다": "assemble",
}

# "청소를 하세요"처럼 동작이 명사에 있고 동사가 '하다'뿐일 때만 보는 명사 힌트(어절 앞부분 일치).
_HADA_NOUN_CLASSES = {
    "청소": "clean", "포장": "pack", "분류": "sort", "정리": "sort", "확인": "observe",
    "점검": "observe", "조립": "assemble", "착용": "wear", "적재": "stack",
}
_LIGHT_LEMMAS = frozenset({"하다", "되다", "있다"})


@lru_cache(maxsize=1)
def _lemma_classes() -> dict[str, str]:
    """동사 원형 → 동작 계열. 그림 인덱스의 frame.verb/verb_class에서 만든다(갈리는 동사는 other)."""
    counts: dict[str, Counter] = defaultdict(Counter)
    try:
        index = local_aac.load_index()
    except Exception:  # noqa: BLE001 - 인덱스가 없어도 분해는 돌아야 한다(보충 표만 쓴다)
        index = {}
    for entry in index.values():
        frame = entry.get("frame") or {}
        verb, verb_class = frame.get("verb"), frame.get("verb_class")
        if verb and verb_class in VALID_ACTION_TYPES:
            counts[local_aac._normalize_lemma(verb)][verb_class] += 1
    table: dict[str, str] = {}
    for lemma, counter in counts.items():
        cls, n = counter.most_common(1)[0]
        total = sum(counter.values())
        if total < _CLASS_MIN_COUNT:
            continue  # 그림 한 장으로는 판단하지 않는다(보충 표가 있으면 그걸 쓴다).
        table[lemma] = cls if n / total >= _CLASS_MIN_SHARE else "other"
    for lemma, cls in _EXTRA_VERB_CLASSES.items():
        table.setdefault(lemma, cls)
    return table


def _guess_action(sentence: str) -> str:
    """지시문이 시키는 동작의 계열. 모르는·갈리는 동사가 있거나 동사들의 계열이 다르면 other."""
    lemmas = local_aac._verb_lemmas(sentence)
    table = _lemma_classes()
    # 모르는 동사는 other로 센다. 아는 동사만 보고 정하면 "손을 씻고 장갑을 끼세요"가 '씻다'만 보고
    # clean이 된다 — 두 동작 중 하나만 맞는 꼬리표도 근로자에게는 틀린 꼬리표다.
    classes = {table.get(l, "other") for l in lemmas if l not in _LIGHT_LEMMAS}
    words = re.findall(r"[가-힣]+", sentence)
    if not classes and words and words[-1].startswith(("하", "해")):
        # 분석기는 '하다'를 할 일로 세지 않는다(빈 집합). 서술어가 '하다'면 동작은 앞의 명사에 있다.
        classes = {cls for w in words for noun, cls in _HADA_NOUN_CLASSES.items() if w.startswith(noun)}
    if len(classes) == 1:
        return classes.pop()
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
    job_text = " ".join(str(context.get(k, "")) for k in ("job", "business_type", "work_environment"))
    return DecomposeResult(task_title=title, job=infer_job_text(job_text + " " + raw_input), steps=steps)


_VALID_ACTIONS = VALID_ACTION_TYPES
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
    job = str(raw.get("job") or "unknown")
    if job not in VALID_JOBS:
        job = "unknown"
    return DecomposeResult(task_title=title, job=job, steps=steps)


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
