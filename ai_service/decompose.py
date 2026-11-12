"""규칙 기반 분해기 (LLM 자리표시자).

스켈레톤 단계에서는 실제 LLM 대신 규칙으로 단계를 만든다. 중요한 건 *출력의 모양*과
*검증 흐름*이다. M2에서 이 함수 내부만 LLM 호출+프롬프트로 교체하면 바깥 계약은 유지된다.

평가 반영 — 분할 규칙 개선:
- 기존: 모든 쉼표에서 분할 → 나열형 문장("사과, 배, 귤")이 깨졌다.
- 변경: (1) 문장부호, (2) 순서 접속어(그리고/그다음/그 후/이후 등),
        (3) 순차 연결어미+쉼표("~하고," "~한 뒤," "~한 후," "~한 다음,")에서만 분할.
        단순 나열 쉼표는 분할하지 않아 한 단계로 유지한다.
- 2026-11-09 입력 화면 단계 나누기: 한 단계 = 동작 하나 = 그림 한 장. 나누기는 사업주가 지시문을 입력한 그 자리에서
        끝낸다. GPT가 나누고(llm_decompose), 규칙 동작 세기(step_split.split_clause)가 원문 조각마다 GPT 분할을
        검산한다(_reconcile). 규칙이 "동작 하나"라고 보는데 GPT가 나눴으면 한 단계로 되돌리고, 둘이 어긋나는데
        어느 쪽이 맞는지 낱말 목록만으로 정할 수 없으면 split_check(노란 표시)를 붙인다. 단계마다 split_group·
        split_check·source_text를 채운다(schemas.Step). 규칙 경로(LLM 없음)도 같은 필드를 채운다.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

import llm
import local_aac
import step_split
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


# 도구에 따라 동작이 갈리는 동사. "카트를 밀어 주세요"는 옮기기(move)지만 "청소기로 바닥을 밀어주세요"·
# "대걸레로 미세요"는 청소다 — 인덱스에서 밀다는 move로 모여 있어 청소 문장에 move가 붙고, 맞는 청소 그림이
# 동사 계열 벌점을 받았다. 문장에 청소 도구가 있으면 그 도구의 계열로 본다.
_TOOL_DEPENDENT_LEMMAS = frozenset({"밀다", "돌리다"})
_TOOL_CLASSES = {
    "청소기": "clean", "걸레": "clean", "밀대": "clean", "빗자루": "clean", "청소포": "clean",
}
_TOOL_PARTICLES = ("으로", "로", "를", "을", "는", "은", "도", "가", "이", "와", "과")


def _tool_class(words: list[str]) -> str | None:
    """문장에 든 청소 도구의 계열("대걸레로" → 대걸레 → 걸레 → clean). 없으면 None."""
    for word in words:
        stems = {word} | {word[: -len(p)] for p in _TOOL_PARTICLES if word.endswith(p) and len(word) > len(p)}
        for stem in stems:
            for tool, cls in _TOOL_CLASSES.items():
                if stem.endswith(tool):
                    return cls
    return None


def _guess_action(sentence: str) -> str:
    """지시문이 시키는 동작의 계열. 모르는·갈리는 동사가 있거나 동사들의 계열이 다르면 other."""
    lemmas = local_aac._verb_lemmas(sentence)
    table = _lemma_classes()
    words = re.findall(r"[가-힣]+", sentence)
    tool_cls = _tool_class(words)
    # 모르는 동사는 other로 센다. 아는 동사만 보고 정하면 "손을 씻고 장갑을 끼세요"가 '씻다'만 보고
    # clean이 된다 — 두 동작 중 하나만 맞는 꼬리표도 근로자에게는 틀린 꼬리표다.
    classes = {
        tool_cls if (l in _TOOL_DEPENDENT_LEMMAS and tool_cls) else table.get(l, "other")
        for l in lemmas if l not in _LIGHT_LEMMAS
    }
    if not classes and words and words[-1].startswith(("하", "해")):
        # 분석기는 '하다'를 할 일로 세지 않는다(빈 집합). 서술어가 '하다'면 동작은 앞의 명사에 있다.
        classes = {cls for w in words for noun, cls in _HADA_NOUN_CLASSES.items() if w.startswith(noun)}
    if len(classes) == 1:
        return classes.pop()
    return "other"


# 그림 검색어가 못 되는 말 — 순서 접속어(그리고·그다음)와, 동사 뒤 보조 용언 '주다'("짜 주세요"의 '주세요').
# 이 말만 남으면 그림 검색에 근거가 없다(2차 검증). "손님께 영수증을 주세요"의 '주세요'는 본동사라 남긴다.
_KEYWORD_STOP = frozenset({"먼저"}) | frozenset(w for c in _SEQ_CONNECTIVES for w in c.split())
_AUX_GIVE = frozenset({"주세요", "줘요", "주십시오"})
_GIVE_ARGS = ("을", "를", "에게", "께", "한테")


def _extract_keywords(sentence: str) -> list[Keyword]:
    words = re.findall(r"[가-힣A-Za-z0-9]+", sentence)
    keywords: list[Keyword] = []
    for k, w in enumerate(words):
        if len(w) < 2 or w in _KEYWORD_STOP:
            continue
        if w in _AUX_GIVE and k > 0 and not words[k - 1].endswith(_GIVE_ARGS):
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


_CONN_PATTERN = r"\s*(?:%s)[\s,]+" % "|".join(re.escape(c) for c in _SEQ_CONNECTIVES)


# 문장 끝 — 숫자 사이의 점("2.5L")은 소수점이라 문장 끝이 아니다.
_SENTENCE_RE = re.compile(r"(?:[^.!?\n]|(?<=\d)\.(?=\d))+[.!?]*")


def _sentence_spans(text: str) -> list[tuple[str, str]]:
    """문장부호로 자른 (문장, 끝 문장부호까지 붙인 원문 문장) 목록. 원문 문장은 [합치기]가 되돌릴 글이다."""
    out: list[tuple[str, str]] = []
    for m in _SENTENCE_RE.finditer(text):
        sentence = m.group().strip().rstrip(".!?").strip()
        if sentence:
            out.append((sentence, m.group().strip()))
    return out


def _split_sentence(sentence: str) -> list[str]:
    """한 문장을 순서 접속어(앞뒤 공백/쉼표 허용)와 순차 연결어미+쉼표에서 자른다(형용사 '~고'는 제외)."""
    chunks: list[str] = []
    for part in re.split(_CONN_PATTERN, sentence):
        part = part.strip()
        if part:
            chunks.extend(_split_sequential(part))
    return chunks


def _split_steps(text: str) -> list[str]:
    """직무 원문을 단계 문자열 리스트로 분할한다(개선된 규칙)."""
    return [c for sentence, _ in _sentence_spans(text) for c in _split_sentence(sentence)]


@dataclass
class Clause:
    """원문 조각(규칙 동작 세기 단위)과 규칙 판정 결과."""
    text: str
    plan: step_split.SplitOutcome
    sentence: int = 0          # 몇 번째 원문 문장에서 나왔나(0부터) — split_group 단위
    sentence_text: str = ""    # 그 원문 문장(끝 문장부호 포함) — source_text
    # GPT에 보여 주는 '원문 조각'(src 번호 단위). 대개 [text]다. 쉼표('~고,')에서 자른 조각을 떼어 놓으면 뜻이
    # 바뀌는 절은 한 Clause로 묶되, GPT에는 전과 같은 쉼표 조각을 보여 준다(같은 입력 → 응답 캐시가 그대로 맞는다).
    pieces: list[str] = field(default_factory=list)
    # 규칙 경로에서 이 조각을 보여 줄 지시형 문장("물기를 닦은 후," → "물기를 닦으세요."). None이면 조각 그대로.
    rule_text: str | None = None
    rule_check: bool = False   # 규칙 경로에서 이 조각에 노란 줄(쉼표에서 잘랐지만 지시형 문장을 못 만들었다)
    # 사업주가 쉼표·순서 접속어로 끊어 썼는데 뜻 검사에 걸려 자르지 않은 문장(규칙 경로에서 한 번 보게 한다).
    cut_refused: bool = False


def _comma_cut_ok(whole: step_split.SplitOutcome, pieces: list[str]) -> tuple[list[str | None], bool] | None:
    """'~고,' '~(으)ㄴ 다음,' '~후,'에서 자른 조각을 따로 단계로 둬도 되는가. 되면 (조각마다 지시형 문장, 확실한가)를
    돌려준다. 지시형 문장을 못 만든 조각은 None(조각 그대로 보이고 노란 줄).

    쉼표가 있어도 문장 전체를 규칙 동작 세기에 넣어 본다(입력 화면 나누기 1차 검증). 쉼표 조각을 먼저 떼면
    "컵을 씻지 말고, 바로 버리세요" → "컵을 씻지 말고." 같은 부정 조각, "손님이 나가고," 같은 다른 사람의 일,
    "컵을 헹군 다음."처럼 끝나지 않은 조각이 노란 표시 없이 따로 단계가 됐다. 전체 판정이 동작 수 = 조각 수이고
    지시형 문장을 만들 수 있을 때만(부정·다른 주어·실수·물음이 있으면 문장을 만들지 않는다) 쉼표에서 자른다.
    앞 동사가 일부러 하는 일 목록 밖(분류하다)이라 제안을 내지 않은 문장도, 사업주가 쉼표로 끊어 썼으므로 자른다
    (comma_draft).
    """
    if whole.actions != len(pieces):
        return None
    steps = whole.steps if whole.auto else (whole.suggestion or whole.comma_draft)
    if steps and len(steps) == len(pieces):
        return list(steps), True
    # 문장은 못 만들었지만(문법 검사 실패) 뜻 위험은 없다 — 조각 그대로 나누고 사업주가 한 번 본다.
    if whole.draft_blockers is not None and set(whole.draft_blockers) <= step_split.COMMA_OK_BLOCKERS:
        return [None] * len(pieces), False
    return None


def _more_cut_ok(whole: step_split.SplitOutcome, text: str) -> bool:
    """동작이 조각보다 많은 문장("서류를 넣고 복사한 뒤, 클립으로 묶어 놓으세요")을 쉼표·접속어에서 잘라도 되는가 —
    부정이 없고, 앞 절들의 뜻 검사(다른 주어·실수·물음·'빼고')가 쉼표로 끊어 쓴 문장에서 막지 않는 것뿐일 때."""
    if step_split.has_negation(text):
        return False
    return whole.draft_blockers is not None and set(whole.draft_blockers) <= step_split.COMMA_OK_BLOCKERS


def _conn_groups(sentence: str) -> list[tuple[str, list[str]]]:
    """문장을 순서 접속어(그리고·그다음)에서 자른 부분들을 묶는다. 앞부분이 이미 끝난 지시("닦으세요 그리고 …")면
    거기서 묶음을 닫고, 끝나지 않은 연결형("손을 씻고 그다음 …")이면 뒤 부분과 한 묶음이다 — 쉼표 조각처럼
    문장 전체로 뜻을 검사해야 한다(입력 화면 나누기 2차 검증). (원문 그대로의 묶음 글, 부분 목록)."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in re.finditer(_CONN_PATTERN, sentence):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(sentence)))
    groups: list[tuple[str, list[str]]] = []
    cur: list[str] = []
    g_start: int | None = None
    for k, (a, b) in enumerate(spans):
        part = sentence[a:b].strip()
        if part:
            if g_start is None:
                g_start = a
            cur.append(part)
        last = k == len(spans) - 1
        if cur and (last or part.endswith(("요", "다"))):
            groups.append((sentence[g_start:b].strip(), cur))
            cur, g_start = [], None
    return groups


def clauses_of(text: str) -> list[Clause]:
    """원문 → 조각마다 규칙 판정(자동 분할·나누기 제안·그대로). 평가 도구도 이 함수를 쓴다.

    문장부호에서 자르고, 순서 접속어(그리고·그다음)·'~고,' 같은 쉼표에서 끊긴 조각은 문장 전체를 규칙 동작
    세기에 넣어 본 뒤(_comma_cut_ok) 될 때만 따로 둔다. 접속어 조각을 먼저 떼면 "컵은 씻지 말고 그다음 선반에
    올리세요" → "컵은 씻지 말고."(부정), "손님이 나가고 그리고 …" → "손님이 나가고."(남의 일), "먼저 손을 씻고
    그다음 …" → "먼저 손을 씻고."(끝나지 않은 말)가 노란 표시 없이 단계가 됐다(2차 검증). 동작이 조각보다 많으면
    뜻 위험이 없을 때만 조각마다 노란 줄로 자르고(_more_cut_ok), 끝나지 않은 조각은 지시형으로 맺어(finish_piece)
    그 안에서 다시 나눈다.
    _split_steps는 문장부호를 떼므로, 원문에서 조각 바로 뒤에 물음표가 있었는지 따로 알려 준다 — 물음
    ("상자를 접어서 넣을까요?")을 지시로 바꿔 나누지 않게.
    GPT에 보여 주는 원문 조각(pieces)은 언제나 쉼표·접속어 조각 그대로다(응답 캐시·src 번호가 그대로 맞는다).
    """
    out: list[Clause] = []
    cursor = 0

    def question_after(chunk: str) -> bool:
        nonlocal cursor
        idx = text.find(chunk, cursor)
        if idx < 0:
            return False
        cursor = idx + len(chunk)
        return text[cursor:cursor + 3].lstrip().startswith(("?", "？"))

    for si, (sentence, raw_sentence) in enumerate(_sentence_spans(text)):
        for group_text, parts in _conn_groups(sentence):
            pieces = [c for part in parts for c in _split_sequential(part)]
            asks = [question_after(chunk) for chunk in pieces]
            if len(pieces) < 2:
                out.extend(Clause(chunk, step_split.split_clause(chunk, question=ask), si, raw_sentence,
                                  pieces=[chunk]) for chunk, ask in zip(pieces, asks))
                continue
            whole_text = parts[0] if len(parts) == 1 else ", ".join(pieces)
            whole = step_split.split_clause(whole_text, question=asks[-1])
            cut = _comma_cut_ok(whole, pieces)
            if cut is None and whole.actions > len(pieces) and _more_cut_ok(whole, whole_text):
                last = len(pieces) - 1
                for k, (chunk, ask) in enumerate(zip(pieces, asks)):
                    shown = None if k == last else step_split.finish_piece(chunk)
                    out.append(Clause(chunk, step_split.split_clause(shown or chunk, question=ask), si,
                                      raw_sentence, pieces=[chunk], rule_text=shown, rule_check=True))
                continue
            if cut is None:
                out.append(Clause(group_text, whole, si, raw_sentence, pieces=pieces, cut_refused=True))
                continue
            texts, sure = cut
            last = len(pieces) - 1
            for k, (chunk, ask, shown) in enumerate(zip(pieces, asks, texts)):
                if shown is None and k != last:
                    shown = step_split.finish_piece(chunk)
                out.append(Clause(chunk, step_split.split_clause(chunk, question=ask), si, raw_sentence,
                                  pieces=[chunk], rule_text=shown, rule_check=not sure))
    return out


def gpt_pieces(clauses: list[Clause]) -> list[str]:
    """GPT 사용자 메시지의 '원문 조각' 목록(단계마다 src로 이 번호를 받는다)."""
    return [p for c in clauses for p in (c.pieces or [c.text])]


def _assign_groups(steps: list[Step], sentence_of: list[int], clauses: list[Clause]) -> None:
    """원문 문장 하나에서 단계가 둘 이상 나왔으면 그 단계들에 같은 split_group과 원문 문장(source_text)을 단다.
    한 문장이 한 단계로 남았으면 None. 번호는 1부터, 나뉜 문장마다 하나씩."""
    raw = {c.sentence: c.sentence_text for c in clauses}
    count: dict[int, int] = {}
    for si in sentence_of:
        count[si] = count.get(si, 0) + 1
    ids: dict[int, int] = {}
    for st, si in zip(steps, sentence_of):
        if count[si] >= 2:
            ids.setdefault(si, len(ids) + 1)
            st.split_group, st.source_text = ids[si], raw.get(si)
        else:
            st.split_group, st.source_text = None, None


def plan_steps(text: str) -> list[step_split.SplitOutcome]:
    return [c.plan for c in clauses_of(text)]


def _as_sentence(chunk: str) -> str:
    return chunk if chunk.endswith(("요", "다", ".", "!", "?")) else chunk + "."


def _plain(sentence: str) -> str:
    """분할기가 만든 문장('…세요.')을 다른 단계와 같은 모양으로(문장부호로 나눈 조각은 마침표가 없다)."""
    return sentence[:-1] if sentence.endswith("요.") else sentence


# 방법 동사로 세지 않지만, 앞 동작이면 그 자체가 따로 손일인 때가 많은 동사(벨을 누르고 기다리다, 물을 따라서
# 갖다 드리다). 규칙 경로에서 한 단계로 남으면 노란 줄을 켠다.
_HAND_MANNER = frozenset({"누르다", "따르다"})


def _rule_decompose(raw_input: str, context: dict) -> DecomposeResult:
    """규칙 기반 분해(LLM 미사용/실패 시 폴백).

    조각마다 step_split이 확실한 꼴만 자동으로 나눈다(같은 split_group, source_text=원문 조각). 확실하지 않지만
    나누기 제안(plan.suggestion)이 있으면 제안대로 나누고 split_check를 켠다 — 입력 화면에서 노란 줄로 보이고,
    틀렸으면 사업주가 [합치기]로 되돌린다(GPT가 안 될 때 여러 동작이 한 줄로 남지 않게). 제안도 없이 동작이
    둘 이상인 조각은 한 단계로 두고 split_check를 켠다 — 사업주가 [더 나누기]로 나눈다.
    """
    text = raw_input.strip()
    clauses = clauses_of(text)

    steps: list[Step] = []
    sentence_of: list[int] = []
    for cl in clauses:
        plan = cl.plan
        if cl.rule_text is not None and not cl.rule_check:
            pieces = [(_plain(cl.rule_text), False)]
        elif plan.auto and len(plan.steps) >= 2:
            pieces = [(_plain(p), cl.rule_check) for p in plan.steps]
        elif plan.suggestion and len(plan.suggestion) >= 2:
            pieces = [(_plain(p), True) for p in plan.suggestion]
        elif cl.rule_text is not None:
            pieces = [(_plain(cl.rule_text), True)]
        elif cl.rule_check:
            pieces = [(cl.text, True)]
        else:
            # 동작이 둘 이상인데 못 나눴거나, 방법 동사로 본 앞 동작이 따로 그림이 필요할 수 있는 동사(누르고 기다리다·
            # 따라서 갖다 드리다)거나, 사전에 없는 동사가 '-ㄴ 뒤' 앞에 있거나, 사업주가 끊어 쓴 곳을 뜻 검사 때문에
            # 자르지 않았으면 노란 줄로 한 번 보게 한다.
            pieces = [(cl.text, plan.actions >= 2 or bool(plan.hidden_lemmas & _HAND_MANNER)
                       or plan.unparsed_verbs > 0 or cl.cut_refused)]
        for chunk, check in pieces:
            steps.append(Step(
                order=len(steps) + 1,
                sentence=_as_sentence(chunk),
                keywords=_extract_keywords(chunk),
                action_type=_guess_action(chunk),
                safety_flags=[],
                split_check=check,
            ))
            sentence_of.append(cl.sentence)
    _assign_groups(steps, sentence_of, clauses)

    chunks = [c.text for c in clauses]
    title = (chunks[0][:20] if chunks else "직무")
    job_text = " ".join(str(context.get(k, "")) for k in ("job", "business_type", "work_environment"))
    return DecomposeResult(task_title=title, job=infer_job_text(job_text + " " + raw_input), steps=steps)


_VALID_ACTIONS = VALID_ACTION_TYPES
_MAX_STEPS = 10
_MAX_SENTENCE = 120


def _build_from_llm(raw: dict, clauses: list[Clause] | None = None) -> DecomposeResult:
    """LLM JSON → DecomposeResult. 가드레일: 형식/길이/개수 정규화 후 통과.

    clauses(원문 조각)가 있으면 규칙 동작 세기로 GPT 분할을 검산하고 단계 나누기 필드를 채운다(_reconcile).
    """
    raw_steps = raw.get("steps") or []
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("LLM 응답에 steps가 없습니다.")

    steps: list[Step] = []
    srcs: list[object] = []
    bad_form: set[int] = set()
    # 사업주 원문의 말투. 원문 문장이 모두 '~해요'면 GPT가 '~세요'로 바꾼 단계 문장을 되돌린다(step_split.restyle).
    styles = {step_split.text_style(c.sentence_text or c.text) for c in clauses or []}
    style = styles.pop() if len(styles) == 1 else None
    for i, s in enumerate(raw_steps[:_MAX_STEPS], start=1):
        sentence = str(s.get("sentence", "")).strip()
        if not sentence:
            continue
        sentence = sentence[:_MAX_SENTENCE]
        # GPT가 쓴 틀린 지시형('눌러세요'·'알려세요')을 바로잡는다. 못 고치면 노란 줄(근로자는 이 문장을 그대로 듣는다).
        sentence, form_ok = step_split.fix_polite(sentence)
        sentence = step_split.restyle(sentence, style)
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
        srcs.append(s.get("src"))
        if not form_ok:
            bad_form.add(id(steps[-1]))

    if not steps:
        raise ValueError("LLM 응답에서 유효한 단계를 만들지 못했습니다.")
    if clauses:
        steps = _reconcile(steps, _align(steps, srcs, clauses), clauses)
    for st in steps:
        # 검산이 문장을 원문으로 바꿨으면(조건 되살리기) 다시 본다.
        if id(st) in bad_form and not step_split.fix_polite(st.sentence)[1]:
            st.split_check = True
    title = str(raw.get("task_title") or steps[0].sentence)[:40]
    job = str(raw.get("job") or "unknown")
    if job not in VALID_JOBS:
        job = "unknown"
    return DecomposeResult(task_title=title, job=job, steps=steps)


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[^가-힣A-Za-z0-9]", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


# 끝맺음에서 나오는 두 글자 — 어느 문장과도 겹쳐 '같은 일'의 근거가 못 된다("바닥을 쓰세요"와 "의자를 넣으세요").
_ENDING_GRAMS = frozenset({"세요", "으세", "하세", "주세", "어요", "아요", "해요", "워요", "와요", "하다", "해주", "어주"})


def _overlap(st: Step, text: str) -> float:
    """단계(문장 + 그림 검색어)와 원문 글의 글자 겹침 비율(끝맺음 글자는 빼고)."""
    g = _bigrams(st.sentence + " " + " ".join(st.symbol_query)) - _ENDING_GRAMS
    return len(g & _bigrams(text)) / max(1, len(g))


# 조사·끝맺음 글자 — 원문에 기댄 단계인지 볼 때 뺀다.
_FUNCTION_CHARS = frozenset("을를은는이가에의도로고서세요다하으주어아해")


def _grounded(st: Step, text: str) -> bool:
    """단계(문장 + 그림 검색어)가 원문 글과 내용 글자를 하나라도 나누는가. GPT는 조사·어미를 바꿔 쓰므로("옷은 개어서"
    → "옷을 개세요") 두 글자 겹침이 아니라 글자로 본다. 하나도 없으면 원문에 없는 일이다("바닥을 쓰세요")."""
    mine = set(re.sub(r"[^가-힣A-Za-z0-9]", "", st.sentence + "".join(st.symbol_query))) - _FUNCTION_CHARS
    return bool(mine & set(text))


def _align(steps: list[Step], srcs: list[object], clauses: list[Clause]) -> list[int]:
    """GPT 단계마다 원문 조각(Clause) 번호(0부터).

    GPT의 src는 '원문 조각'(gpt_pieces, 1부터) 번호다. src가 온전하면(범위 안·순서대로·모든 조각에 단계가 하나
    이상) 그대로 쓴다. 범위 안·순서대로여도 단계가 하나도 없는 조각이 있으면 버린다 — "상자를 접고, 테이프를
    붙이세요"에 [1, 1]을 주면 테이프 단계가 접기 조각 밑에서 합쳐져 사라졌다(1차 검증). 그때는 글자 겹침이 가장 큰
    Clause로 정하되 순서는 되돌아가지 않게 한다(어디와도 겹치지 않는 단계는 앞 단계와 같은 Clause).
    """
    owner = [k for k, c in enumerate(clauses) for _ in (c.pieces or [c.text])]
    n = len(clauses)
    if n == 1:
        return [0] * len(steps)
    try:
        idx = [int(x) - 1 for x in srcs]  # type: ignore[call-overload]
        if (all(0 <= k < len(owner) for k in idx) and idx == sorted(idx)
                and set(idx) == set(range(len(owner)))):
            return [owner[k] for k in idx]
    except (TypeError, ValueError):
        pass
    out: list[int] = []
    prev = 0
    for st in steps:
        scores = [_overlap(st, c.text) for c in clauses]
        best = max(range(prev, n), key=lambda k: scores[k])
        if scores[best] == 0:
            best = prev
        out.append(best)
        prev = best
    return out


def _merge(group: list[Step], clause: Clause) -> tuple[Step, bool]:
    """GPT가 근거 없이 나눈 단계들을 원문 조각 한 단계로 되돌린다. 문장은 사업주가 쓴 원문 조각이고(입력 화면에서
    바로 고칠 수 있다), 그림 검색어는 마지막 단계(대개 시킬 일의 본동작) 것을 쓰되, 그 단계가 원문 조각과 글자가 전혀
    겹치지 않으면(GPT가 원문에 없는 일을 덧붙였다) 가장 많이 겹치는 단계 것을 쓴다. 고른 단계도 원문과 겹치지 않으면
    (그림이 다른 일의 것일 수 있다) 두 번째 값이 False다."""
    scores = [_overlap(st, clause.text) for st in group]
    pick = len(group) - 1
    if not _grounded(group[pick], clause.text):
        pick = max(range(len(group)), key=lambda i: (_grounded(group[i], clause.text), scores[i], i))
    best = group[pick]
    flags = list(dict.fromkeys(f for st in group for f in st.safety_flags))
    whole = clause.sentence_text.rstrip(".!?").strip() == clause.text
    sentence = clause.sentence_text if whole else clause.text
    if not sentence.endswith((".", "!", "?")):
        sentence += "."
    return Step(
        order=1, sentence=sentence, keywords=best.keywords,
        symbol_query=best.symbol_query, action_type=best.action_type, safety_flags=flags,
    ), _grounded(best, clause.text)


def _head_verb(st: Step) -> str:
    """단계의 동사(그림 검색어 마지막 낱말, 없으면 문장 마지막 낱말의 앞 두 글자)."""
    q = (st.symbol_query or [st.sentence])[0].split()
    return q[-1][:2] if q else ""


def _merge_is_sure(mine: list[Step], plan: step_split.SplitOutcome, text: str) -> bool:
    """규칙은 동작 하나, GPT는 여럿일 때 확인 없이 합쳐도 되는가 — 규칙이 GPT의 남는 단계를 꼴로 설명할 때만
    (입력 화면 나누기 1차 검증: 규칙이 '정리를 하고'·'맡아 보고'를 못 세서 맞는 GPT 분할을 말없이 합쳤다).
    - 세지 않은 동사(방법·보조 용언·형식 동사 하다·조건절 속 동사)가 있으면 확실하지 않다.
    - 규칙이 꼴로 알아본 한 동작 — 대상 나열(물건별로 나눴다)·갈라 담기·'-며' 동시 동작·부정("만지지 말고 부르세요"의
      시킬 일은 하나), 또는 GPT 단계가 모두 같은 동사(같은 일을 물건마다)면 확실하다.
    - 그 밖(GPT가 다른 동사를 더 냈는데 규칙이 그 근거를 못 찾음)은 확실하지 않다."""
    if plan.hidden_verbs > 0:
        return False
    if plan.list_object or plan.sorted_into or plan.with_joined or step_split.has_negation(text):
        return True
    return len({_head_verb(st) for st in mine}) == 1


def _keep_condition(mine: list[Step], clause: Clause, one: bool) -> None:
    """원문 조각 앞의 조건·때 절("출근하면", "고객이 화장실을 쓰고 있으면")을 GPT 단계 문장이 모두 잃었으면 되살린다
    (2차 검증: 조건 절이 있는 26문장 중 24문장에서 조건이 노란 표시 없이 빠졌다 — "밖에서 기다리세요"만 남으면 근로자는
    언제 기다리는지 모른다). 한 동작 조각이 원문 문장 그대로면 사업주가 쓴 원문을 쓰고(받는 사람·도구도 지킨다), 아니면
    첫 단계 앞에 조건 절을 붙인다. 그림 검색어는 그대로다."""
    prefix = step_split.condition_prefix(clause.text)
    if prefix is None or any(step_split.has_condition(st.sentence) for st in mine):
        return
    first = mine[0]
    whole = clause.sentence_text.rstrip(".!?").strip() == clause.text
    if one and whole:
        first.sentence = clause.sentence_text if clause.sentence_text.endswith((".", "!", "?"))             else clause.sentence_text + "."
    else:
        first.sentence = f"{prefix} {first.sentence}"[:_MAX_SENTENCE]


def _reconcile(steps: list[Step], where: list[int], clauses: list[Clause]) -> list[Step]:
    """원문 조각마다 GPT 단계 수(g)와 규칙 동작 수(r)를 맞춰 본다.

    - g == r: 그대로(확실). 다만 앞 동작이 이동이거나 따옴표 속 말이 있거나(soft_boundary) 부정이 든 문장을 나눴으면
      split_check.
    - g > r, r ≤ 1: GPT 과분할(대상 나열을 물건별로, 방법·이동 동사를 따로, 원문에 없는 동작 추가). 한 단계로
      합친다. 규칙이 그 판단을 꼴로 설명할 때만(_merge_is_sure) 확실하고, 아니면 split_check.
    - g > r ≥ 2: 어디를 합칠지 정할 수 없다 — GPT 분할을 두고 split_check.
    - g < r: GPT가 덜 나눴을 수 있다 — GPT 결과를 두고 split_check(규칙은 조건·방법 절을 더 세는 쪽으로 틀린다).
    - 단계가 하나도 없는 조각이 있으면(GPT가 원문 일을 빠뜨렸거나 옆 조각과 한 단계로 묶었다) 그 원문 문장의 모든
      단계에, 원문 조각과 글자가 전혀 겹치지 않는 단계(원문에 없는 일·엉뚱한 그림 검색어)에는 split_check.
    끝으로 원문 문장 단위로 split_group·source_text를 단다(_assign_groups).
    """
    out: list[Step] = []
    sentence_of: list[int] = []
    dropped: set[int] = set()
    for k, clause in enumerate(clauses):
        mine = [st for st, w in zip(steps, where) if w == k]
        if not mine:
            dropped.add(clause.sentence)
            continue
        g, r = len(mine), max(1, clause.plan.actions)
        if g > r and r == 1:
            merged, grounded = _merge(mine, clause)
            merged.split_check = not (grounded and _merge_is_sure(mine, clause.plan, clause.text))
            mine = [merged]
        else:
            # 수가 같아도 나눌지가 말뜻에 기대는 꼴(이동 앞 동작·따옴표 속 말·부정)이면 한 번 보게 한다.
            # (g == r == 1인데 규칙이 넘긴 동사가 있는 경우까지 켜면 dev 정답셋에서 노란 문장이 13 → 65로 늘고
            # 잡는 오답은 3개뿐이라 켜지 않는다.)
            soft = clause.plan.soft_boundary or clause.plan.reason == "negation"
            sure = g == r and not (g >= 2 and soft)
            for st in mine:
                st.split_check = not sure or not _grounded(st, clause.text)
            _keep_condition(mine, clause, g == r == 1)
        out.extend(mine)
        sentence_of.extend([clause.sentence] * len(mine))
    for st, si in zip(out, sentence_of):
        if si in dropped:
            st.split_check = True
    for i, st in enumerate(out, start=1):
        st.order = i
    _assign_groups(out, sentence_of, clauses)
    return out


def may_split(sentence: str) -> dict:
    """문장 하나에 동작이 둘 이상일 수 있는가(규칙만). 조각이 둘 이상이거나, 센 동작이 둘 이상이거나, 세지 않았지만
    따로 하는 동작일 수 있는 동사(방법 동사 '-고/-어서'·사전에 없는 '-ㄴ 뒤' 동사·형식 동사·조건에 묶인 동사)가 있으면
    True. 보조 용언 묶음("쓸어 주세요")만 있는 문장은 False다."""
    clauses = clauses_of(sentence.strip())
    actions = sum(max(1, c.plan.actions) for c in clauses) if clauses else 1
    unsure = any(c.plan.hidden_lemmas or c.plan.unparsed_verbs or c.plan.unseen_verbs or c.plan.reason
                 or c.plan.suggestion
                 or c.cut_refused for c in clauses)
    return {"may_split": len(clauses) >= 2 or actions >= 2 or bool(unsure), "actions": actions}


def decompose(raw_input: str, context: dict) -> DecomposeResult:
    """원문을 단계 배열로 분해한다.

    LLM이 설정돼 있으면 맥락적응 분해를 시도하고, 실패하면 규칙 기반으로 폴백한다.
    빈 입력은 main.py 가드레일에서 걸러진다.
    """
    if llm.llm_available():
        try:
            clauses = clauses_of(raw_input.strip())
            result = _build_from_llm(llm.llm_decompose(raw_input, context, gpt_pieces(clauses)),
                                     clauses)
            logger.info("decompose via LLM: %s steps", len(result.steps))
            return result
        except Exception as e:  # noqa: BLE001 - LLM 실패 시 규칙 기반으로 폴백
            logger.warning("LLM decompose 실패, 규칙 기반 폴백: %s", e)

    return _rule_decompose(raw_input, context)
