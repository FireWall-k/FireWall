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
from dataclasses import dataclass

import llm
import step_split
from schemas import DecomposeResult, Keyword, Step
from taxonomy import VALID_ACTION_TYPES, VALID_JOBS, infer_job_text

logger = logging.getLogger("ai_harness.decompose")

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


_CONN_PATTERN = r"\s*(?:%s)[\s,]+" % "|".join(re.escape(c) for c in _SEQ_CONNECTIVES)


def _sentence_spans(text: str) -> list[tuple[str, str]]:
    """문장부호로 자른 (문장, 끝 문장부호까지 붙인 원문 문장) 목록. 원문 문장은 [합치기]가 되돌릴 글이다."""
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"[^.!?\n]+[.!?]*", text):
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
    """원문 조각(_split_steps가 자른 절·문장)과 규칙 동작 세기 결과."""
    text: str
    plan: step_split.SplitOutcome
    sentence: int = 0          # 몇 번째 원문 문장에서 나왔나(0부터) — split_group 단위
    sentence_text: str = ""    # 그 원문 문장(끝 문장부호 포함) — source_text


def clauses_of(text: str) -> list[Clause]:
    """원문 → 조각마다 규칙 판정(자동 분할·나누기 제안·그대로). 평가 도구도 이 함수를 쓴다.

    _split_steps는 문장부호를 떼므로, 원문에서 조각 바로 뒤에 물음표가 있었는지 따로 알려 준다 — 물음
    ("상자를 접어서 넣을까요?")을 지시로 바꿔 나누지 않게.
    """
    out: list[Clause] = []
    cursor = 0
    for si, (sentence, raw_sentence) in enumerate(_sentence_spans(text)):
        for chunk in _split_sentence(sentence):
            idx = text.find(chunk, cursor)
            question = False
            if idx >= 0:
                cursor = idx + len(chunk)
                question = text[cursor:cursor + 3].lstrip().startswith(("?", "？"))
            out.append(Clause(chunk, step_split.split_clause(chunk, question=question), si, raw_sentence))
    return out


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
        if plan.auto and len(plan.steps) >= 2:
            pieces = [(_plain(p), False) for p in plan.steps]
        elif plan.suggestion and len(plan.suggestion) >= 2:
            pieces = [(_plain(p), True) for p in plan.suggestion]
        else:
            pieces = [(cl.text, plan.actions >= 2)]
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
        srcs.append(s.get("src"))

    if not steps:
        raise ValueError("LLM 응답에서 유효한 단계를 만들지 못했습니다.")
    if clauses:
        steps = _reconcile(steps, _align(steps, srcs, clauses), clauses)
    title = str(raw.get("task_title") or steps[0].sentence)[:40]
    job = str(raw.get("job") or "unknown")
    if job not in VALID_JOBS:
        job = "unknown"
    return DecomposeResult(task_title=title, job=job, steps=steps)


def _bigrams(text: str) -> set[str]:
    t = re.sub(r"[^가-힣A-Za-z0-9]", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def _align(steps: list[Step], srcs: list[object], clauses: list[Clause]) -> list[int]:
    """GPT 단계마다 원문 조각 번호(0부터). GPT가 준 src(1부터)가 온전하면(범위 안·순서대로) 그대로 쓰고,
    아니면 글자 겹침이 가장 큰 조각으로 정하되 순서는 되돌아가지 않게 한다."""
    n = len(clauses)
    if n == 1:
        return [0] * len(steps)
    try:
        idx = [int(x) - 1 for x in srcs]  # type: ignore[call-overload]
        if all(0 <= k < n for k in idx) and idx == sorted(idx):
            return idx
    except (TypeError, ValueError):
        pass
    grams = [_bigrams(c.text) for c in clauses]
    out: list[int] = []
    prev = 0
    for st in steps:
        g = _bigrams(st.sentence + " " + " ".join(st.symbol_query))
        scores = [len(g & cg) / max(1, len(g)) for cg in grams]
        best = max(range(prev, n), key=lambda k: scores[k])
        if scores[best] == 0:
            best = prev
        out.append(best)
        prev = best
    return out


def _merge(group: list[Step], clause: Clause) -> Step:
    """GPT가 근거 없이 나눈 단계들을 원문 조각 한 단계로 되돌린다. 문장은 사업주가 쓴 원문 조각이고(입력 화면에서
    바로 고칠 수 있다), 그림 검색어는 마지막 단계(대개 시킬 일의 본동작) 것을 쓴다."""
    last = group[-1]
    flags = list(dict.fromkeys(f for st in group for f in st.safety_flags))
    whole = clause.sentence_text.rstrip(".!?").strip() == clause.text
    sentence = clause.sentence_text if whole else clause.text
    if not sentence.endswith((".", "!", "?")):
        sentence += "."
    return Step(
        order=1, sentence=sentence, keywords=last.keywords,
        symbol_query=last.symbol_query, action_type=last.action_type, safety_flags=flags,
    )


def _reconcile(steps: list[Step], where: list[int], clauses: list[Clause]) -> list[Step]:
    """원문 조각마다 GPT 단계 수(g)와 규칙 동작 수(r)를 맞춰 본다.

    - g == r: 그대로(확실).
    - g > r, r ≤ 1: GPT 과분할(대상 나열을 물건별로, 방법·이동 동사를 따로, 원문에 없는 동작 추가). 한 단계로
      합친다. 규칙이 세지 않고 넘긴 동사(방법·보조 용언 묶음 "채워 넣다")가 있으면 합친 판단이 낱말 목록에
      기댄 것이라 split_check를 켠다. 동사가 정말 하나뿐이면(나열·추가 동작) 확실하므로 끈다.
    - g > r ≥ 2: 어디를 합칠지 정할 수 없다 — GPT 분할을 두고 split_check.
    - g < r: GPT가 덜 나눴을 수 있다 — GPT 결과를 두고 split_check(규칙은 조건·방법 절을 더 세는 쪽으로 틀린다).
    끝으로 원문 문장 단위로 split_group·source_text를 단다(_assign_groups).
    """
    out: list[Step] = []
    sentence_of: list[int] = []
    for k, clause in enumerate(clauses):
        mine = [st for st, w in zip(steps, where) if w == k]
        if not mine:
            continue
        g, r = len(mine), max(1, clause.plan.actions)
        if g > r and r == 1:
            merged = _merge(mine, clause)
            merged.split_check = clause.plan.hidden_verbs > 0
            mine = [merged]
        else:
            # 수가 같아도 나눌지가 말뜻에 기대는 꼴(이동 앞 동작·따옴표 속 말)이면 한 번 보게 한다.
            # (g == r == 1인데 규칙이 넘긴 동사가 있는 경우까지 켜면 dev 정답셋에서 노란 문장이 13 → 65로 늘고
            # 잡는 오답은 3개뿐이라 켜지 않는다.)
            sure = g == r and not (g >= 2 and clause.plan.soft_boundary)
            for st in mine:
                st.split_check = not sure
        out.extend(mine)
        sentence_of.extend([clause.sentence] * len(mine))
    for i, st in enumerate(out, start=1):
        st.order = i
    _assign_groups(out, sentence_of, clauses)
    return out


def decompose(raw_input: str, context: dict) -> DecomposeResult:
    """원문을 단계 배열로 분해한다.

    LLM이 설정돼 있으면 맥락적응 분해를 시도하고, 실패하면 규칙 기반으로 폴백한다.
    빈 입력은 main.py 가드레일에서 걸러진다.
    """
    if llm.llm_available():
        try:
            clauses = clauses_of(raw_input.strip())
            result = _build_from_llm(llm.llm_decompose(raw_input, context, [c.text for c in clauses]),
                                     clauses)
            logger.info("decompose via LLM: %s steps", len(result.steps))
            return result
        except Exception as e:  # noqa: BLE001 - LLM 실패 시 규칙 기반으로 폴백
            logger.warning("LLM decompose 실패, 규칙 기반 폴백: %s", e)

    return _rule_decompose(raw_input, context)
