from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

_JOB_ALIASES: dict[str, tuple[str, ...]] = {
    "assembly": (
        "assembly",
        "조립",
        "제조",
        "부품",
        "생산",
    ),
    "cafe": (
        "cafe",
        "카페",
        "커피",
        "음료",
        "바리스타",
    ),
    "cleaning": (
        "cleaning",
        "청소",
        "세탁",
        "세차",
        "환경미화",
    ),
    "packaging": (
        "packaging",
        "포장",
        "패킹",
        "박스포장",
    ),
    "retail": (
        "retail",
        "마트",
        "매장",
        "소매",
        "피킹",
        "계산",
    ),
    "serving": (
        "serving",
        "서빙",
        "배식",
        "식당",
        "음식점",
        "홀서빙",
    ),
    "display": (
        "display",
        "진열",
        "상품진열",
        "매대",
        "진열대",
    ),
    "delivery": (
        "delivery",
        "배송",
        "배달",
        "택배",
        "배송원",
        "배달원",
    ),
    "gas": (
        "gas",
        "주유",
        "주유소",
        "주유원",
        "주유작업",
    ),
}

_PARTICLES = (
    "으로", "에서", "에게", "까지", "부터", "처럼", "보다", "하고", "이며", "이며",
    "을", "를", "이", "가", "은", "는", "에", "의", "와", "과", "도", "만", "로",
)


def _default_data_dir() -> Path:
    # ai_service/local_aac.py -> repository root/data/aac for local execution.
    return Path(__file__).resolve().parent.parent / "data" / "aac"


def get_data_dir() -> Path:
    return Path(os.getenv("AAC_DATA_DIR", str(_default_data_dir()))).resolve()


def _normalize(text: str) -> str:
    return " ".join(_TOKEN_RE.findall(text.lower()))


def _stem_token(token: str) -> str:
    value = token
    for p in _PARTICLES:
        if len(value) > len(p) + 1 and value.endswith(p):
            value = value[: -len(p)]
            break
    # Common polite/statement endings from task sentences.
    for ending in ("하세요", "해주세요", "합니다", "하십시오", "한다", "해요", "세요", "니다", "다"):
        if len(value) > len(ending) + 1 and value.endswith(ending):
            value = value[: -len(ending)]
            break
    return value


def _tokens(text: str) -> set[str]:
    return {_stem_token(t) for t in _TOKEN_RE.findall(text.lower()) if len(_stem_token(t)) >= 2}


def _bigrams(text: str) -> set[str]:
    compact = _normalize(text).replace(" ", "")
    if len(compact) < 2:
        return {compact} if compact else set()
    return {compact[i : i + 2] for i in range(len(compact) - 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# 어간 끝 모음이 어미와 만나 줄어드는 형태. '세우-'+'어' → '세워', '하-'+'여' → '해'.
_STEM_CONTRACTIONS = {"우": "워", "오": "와", "이": "여", "하": "해", "리": "려", "기": "겨"}


def _stem_variants(stem: str) -> tuple[str, ...]:
    """어간의 표면형 후보. 활용형에서 어간을 찾아내기 위한 것이다."""
    if not stem:
        return ()
    contracted = _STEM_CONTRACTIONS.get(stem[-1])
    if contracted:
        return (stem, stem[:-1] + contracted)
    return (stem,)


@lru_cache(maxsize=1)
def _verb_stem_map() -> tuple[tuple[str, str], ...]:
    """(어간 표면형, 원형) 목록. 긴 어간이 먼저 오도록 정렬한다.

    인덱스에 있는 동사만 대상으로 하는 닫힌 사전이다. 일반적인 한국어 형태소 분석
    없이도, 우리가 실제로 쓰는 300여 개 동사에 대해서는 활용형에서 원형을 되찾을 수 있다.
    """
    lemmas: set[str] = set()
    for entry in load_index().values():
        verb = (entry.get("frame") or {}).get("verb")
        if verb:
            lemmas.add(verb)
        # 검색어에도 '갈다', '비질하다' 같은 원형이 들어 있다('갈다'는 두 글자다).
        for word in entry.get("keywords_ko", []):
            if isinstance(word, str) and word.endswith("다") and len(word) >= 2:
                lemmas.add(word)

    pairs: set[tuple[str, str]] = set()
    for lemma in lemmas:
        stem = lemma[:-1]  # '다'를 뗀다
        if len(stem) < 1:
            continue
        for surface in _stem_variants(stem):
            pairs.add((surface, lemma))
    # 긴 어간 우선 — '준비하'가 '준'보다 먼저 걸려야 한다.
    return tuple(sorted(pairs, key=lambda p: -len(p[0])))


def _verb_lemmas(text: str) -> set[str]:
    """활용형 문장에서 동사 원형을 뽑는다.

    "원두를 갈아주세요" → {'갈다'}. 자산 쪽 검색어는 원형('갈다')이라 이 변환이 없으면
    질의 토큰('갈아주')과 영영 만나지 못한다 — 인덱스를 만들어도 아무 효과가 없다.
    """
    found: set[str] = set()
    for word in _TOKEN_RE.findall(text):
        for surface, lemma in _verb_stem_map():
            # 어간만 덜렁 있는 게 아니라 뒤에 어미가 붙어 있어야 동사로 본다.
            if len(word) <= len(surface) or not word.startswith(surface):
                continue
            # 한 글자 어간('갈','개')은 아무 단어에나 걸리기 쉽다. 어미가 두 글자 이상
            # 붙어 있을 때만 인정한다('갈아주세요'는 통과, '갈색'은 탈락).
            if len(surface) == 1 and len(word) < 3:
                continue
            found.add(lemma)
            break  # 가장 긴 어간 하나만
    return found


# 같은 도구를 부르는 다른 이름. 질의와 자산 라벨이 다른 단어를 쓰면 못 만난다
# ("대걸레로 닦으세요" vs "밀대로 바닥을 닦는다"). 그룹 안의 단어는 서로 같은 것으로 본다.
# 애매한 단어는 넣지 않는다('걸레'는 대걸레도 행주도 될 수 있어 제외).
_TOOL_SYNONYMS: tuple[frozenset[str], ...] = (
    frozenset({"대걸레", "밀대"}),
    frozenset({"수세미", "스펀지", "스폰지"}),
    frozenset({"빗자루", "비"}),
    frozenset({"행주", "마른행주"}),
    frozenset({"솔", "브러시"}),
)
_TOOL_SYNONYM_MAP: dict[str, frozenset[str]] = {
    word: group for group in _TOOL_SYNONYMS for word in group
}


def _expand_tools(words: set[str]) -> set[str]:
    """도구 이름을 동의어까지 넓힌다. {'대걸레'} -> {'대걸레', '밀대'}."""
    out = set(words)
    for w in words:
        out |= _TOOL_SYNONYM_MAP.get(w, frozenset())
    return out


def infer_job(context: dict | None = None, query: str = "") -> str | None:
    ctx = context or {}
    haystack = " ".join(
        str(ctx.get(key, ""))
        for key in (
            "business_type",
            "work_environment",
            "job",
            "job_hint",
        )
    ) + " " + query
    norm = _normalize(haystack)
    scores: list[tuple[int, str]] = []
    for job, aliases in _JOB_ALIASES.items():
        count = sum(1 for alias in aliases if alias.lower() in norm)
        if count:
            scores.append((count, job))
    return max(scores)[1] if scores else None


def _canonical_job(value: str) -> str | None:
    """명시적으로 전달된 직무명을 내부 canonical job으로 바꾼다."""
    norm = _normalize(value)
    if not norm:
        return None
    if norm in _JOB_ALIASES:
        return norm

    for job, aliases in _JOB_ALIASES.items():
        for alias in aliases:
            alias_norm = _normalize(alias)
            if alias_norm and (norm == alias_norm or alias_norm in norm):
                return job
    return None


def _explicit_job(context: dict | None) -> str | None:
    """context.job이 명시됐을 때만 hard gate에 사용할 직무를 돌려준다.

    business_type/work_environment/query에서 추론한 직무는 오분류 가능성이 있으므로
    hard gate에 쓰지 않고 기존처럼 약한 선호 신호로만 사용한다.
    """
    ctx = context or {}
    return _canonical_job(str(ctx.get("job") or ""))


_NEGATIVE_PATTERNS = (
    "하지 않는다",
    "하지않는다",
    "하지 마세요",
    "하지마세요",
    "하지 말",
    "하지말",
    "지 않는다",
    "지않는다",
    "지 마세요",
    "지마세요",
    "지 말",
    "지말",
    "않는다",
    "않아요",
    "말아 주세요",
    "말아주세요",
    "금지",
)


def _is_negative_text(text: str) -> bool:
    """금지/부정 지시인지 가볍게 판별한다."""
    normalized = " ".join(str(text or "").strip().split())
    return any(pattern in normalized for pattern in _NEGATIVE_PATTERNS)


@lru_cache(maxsize=1)
def load_index() -> dict[str, dict]:
    """구조화 인덱스(aac_index.json)를 id -> 항목으로 읽는다.

    scripts/build_aac_index.py 가 만드는 파생 데이터다. 없어도 동작해야 한다 —
    원본 자산만으로도 예전처럼 라벨 유사도 매칭은 된다(품질은 떨어진다).
    """
    path = get_data_dir() / "aac_index.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {e["id"]: e for e in payload.get("entries", [])}


@lru_cache(maxsize=1)
def load_assets() -> list[dict]:
    path = get_data_dir() / "aac_assets.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets = payload.get("assets", [])
    index = load_index()
    for asset in assets:
        label = str(asset.get("label", ""))
        entry = index.get(asset["id"], {})
        frame = entry.get("frame") or {}

        # 라벨과 검색어는 따로 채점한다. 한 바구니에 넣으면 Jaccard 분모가 커져
        # 모든 점수가 희석되고, 검색어가 많은 자산일수록 손해를 본다(실측 top1 -0.18).
        # 검색어는 도움만 주고 깎지는 않아야 한다.
        asset["_norm"] = _normalize(label)
        asset["_tokens"] = _tokens(label)
        asset["_bigrams"] = _bigrams(label)

        # 인덱스 검색어는 '라벨에 없는 다른 표현'이다(분쇄한다→갈다, 박스→상자).
        # 라벨만으로는 못 찾던 질의를 여기서 받는다.
        # objects(팀원 ta3woong 브랜치 병합분)도 같은 바구니에 넣는다 — 대상 명사를
        # 가산점으로 쓰면 회귀했지만(cd3972e), 검색 가능하게만 하는 건 keywords/aliases와
        # 같은 안전한 패턴이라 여기서는 그대로 넣는다.
        extra_terms = (
            asset.get("keywords", []) + asset.get("aliases", []) + asset.get("objects", [])
            + entry.get("keywords_ko", []) + entry.get("keywords_en", [])
        )
        keyword_text = " ".join(extra_terms).strip()
        asset["_kw_norm"] = _normalize(keyword_text)
        asset["_kw_bigrams"] = _bigrams(keyword_text)
        # 동사 원형은 _tokens의 어미 제거로 뭉개지므로("분쇄하다"→"분쇄하") 따로 넣는다.
        # 질의에서 뽑은 원형과 같은 형태여야 만난다.
        lemmas = {w for w in extra_terms if isinstance(w, str) and w.endswith("다")}
        if frame.get("verb"):
            lemmas.add(frame["verb"])

        # 도구(instrument)는 그림을 가르는 강한 신호다 — "대걸레로"가 "밀대로 바닥을
        # 닦는다"를 끌어올려야 한다. 라벨에서 뽑은 도구 명사와 인덱스의 instrument를
        # 동의어까지 넓혀 따로 든다.
        tools: set[str] = set()
        if frame.get("instrument"):
            tools |= _tokens(frame["instrument"])
        tools |= _tokens(label) & set(_TOOL_SYNONYM_MAP)
        tools = _expand_tools(tools)
        asset["_tools"] = tools

        asset["_kw_tokens"] = _tokens(keyword_text) | lemmas | tools
        # 이 자산이 나타내는 동작들. 질의에서 뽑은 원형과 직접 비교한다.
        asset["_lemmas"] = lemmas

        # 프레임은 점수가 아니라 '무엇과 비교할지'를 정하는 데 쓴다.
        asset["_frame"] = frame
        asset["_is_object_card"] = bool(frame.get("is_object_card"))
        asset["_verb_class"] = frame.get("verb_class")

        # 현재 인덱스에 polarity가 없어도 label에서 안전하게 추론한다.
        # 추후 frame.polarity가 생기면 그 값을 우선 사용한다.
        polarity = str(frame.get("polarity") or "").strip().lower()
        if polarity == "negative":
            asset["_negative"] = True
        elif polarity == "positive":
            asset["_negative"] = False
        else:
            asset["_negative"] = _is_negative_text(label)
    return assets


# 맥락 가중치(job/asset_type)는 '동점을 깨는' 크기여야 한다.
# 과거에는 job 일치 +0.16 / 불일치 -0.08 이었는데, 이 크기면 다른 직무에 있는 정답을
# 묻어버린다(예: 청소 맥락에서 cafe 소속인 "바닥을 빗자루로 쓸어낸다"가 순위 밖으로 밀림).
#
# 크기는 eval/run_match_eval.py로 실측해 정했다. 직무가 갈리는 경계 사례의 관련도 격차는
# 0.02 내외다("박스 뚜껑을 덮으세요"에서 CAFE_033 0.158 vs PACKAGING_047 0.137).
# 일치 보너스만으로는 이 격차를 못 넘으므로 불일치에 절반 크기의 벌점을 함께 둔다.
# 벌점을 일치 보너스보다 작게 유지하는 게 핵심 — 업종 맥락은 약한 양의 증거이고,
# 불일치는 그보다 더 약한 음의 증거다. 크게 잡으면 타 직무의 정답을 다시 묻는다.
_JOB_TIEBREAK = 0.02
_JOB_MISMATCH_PENALTY = 0.01
_ASSET_TYPE_TIEBREAK = 0.015


def _containment(q_norm: str, label_norm: str, q_tokens: set[str], a_tokens: set[str]) -> float:
    """한쪽이 다른 쪽을 포함할 때의 보정. 길이로 정규화한다.

    예전에는 포함이면 무조건 1.0을 줬는데, 그러면 한 단어짜리 도구 라벨이 문장 안에
    언급되기만 해도 만점을 받았다("행주"가 "테이블을 행주로 닦아주세요"에 포함).
    실측 결과 이 항(가중치 0.08)이 도구 카드가 동작 카드를 이기는 격차(~0.08)를
    거의 그대로 설명했다 — 즉 "테이블을 닦으세요"에 행주 사진이 붙던 원인이다.

    포함은 '언급됨'이 아니라 '거의 같은 말'일 때만 강한 증거다. 짧은 쪽이 긴 쪽을
    얼마나 덮는지의 비율로 준다.
    """
    if not q_norm or not label_norm:
        return 0.0

    q_compact = q_norm.replace(" ", "")
    label_compact = label_norm.replace(" ", "")

    if label_compact in q_compact or q_compact in label_compact:
        shorter, longer = sorted((len(label_compact), len(q_compact)))
        return shorter / longer if longer else 0.0

    # 토큰 단위 포함도 같은 이유로 비율을 따른다.
    if q_tokens and a_tokens and q_tokens <= a_tokens:
        return 0.8 * len(q_tokens) / len(a_tokens)

    return 0.0


# 검색어로 맞은 것은 라벨로 맞은 것보다 약한 증거로 본다(라벨이 그 그림의 정의다).
#
# 스윕해 보니 이 값이 높을수록 나빠진다(0.9에서 full top1 0.939, 0.6에서 0.951).
# 검색어를 가방으로 묶어 유사도를 재면 관련 없는 단어까지 분모에 들어가 잡음이 된다.
# 인덱스의 값어치는 여기가 아니라 동사 원형(_lemmas)과 is_object_card에 있다 —
# 그 둘은 가방이 아니라 직접 비교하기 때문이다.
_KEYWORD_WEIGHT = 0.6


def _text_similarity(q_norm: str, q_tokens: set[str], q_bigrams: set[str],
                     t_norm: str, t_tokens: set[str], t_bigrams: set[str]) -> float:
    """질의와 대상 텍스트 한 덩어리의 유사도."""
    if not t_norm:
        return 0.0
    token_score = _jaccard(q_tokens, t_tokens)
    bigram_score = _jaccard(q_bigrams, t_bigrams)
    seq_score = SequenceMatcher(None, q_norm.replace(" ", ""), t_norm.replace(" ", "")).ratio()
    containment = _containment(q_norm, t_norm, q_tokens, t_tokens)
    return 0.38 * token_score + 0.34 * bigram_score + 0.20 * seq_score + 0.08 * containment


# 질의 동사 원형이 자산의 동사와 같을 때 주는 가산점.
# Jaccard 가방 안에서는 이 신호가 희석돼 묻힌다("갈다" 하나가 검색어 7개 중 1개로
# 계산되면 0.05 남짓이다). 동작이 같다는 것은 그림 선택에서 가장 직접적인 근거이므로
# 따로 더한다.
_VERB_MATCH_BONUS = 0.10

# 도구는 '검색 가능하게'만 하고 '가산점'은 주지 않는다.
#
# frame.instrument 와 도구 동의어(대걸레↔밀대)를 자산의 검색어 바구니(_kw_tokens)에
# 넣고, 질의 쪽 도구도 동의어까지 넓혀 토큰에 더한다. 그러면 "대걸레로 닦으세요"가
# Jaccard 유사도로 "밀대로 바닥을 닦는다"를 끌어올린다 — 실측 top1 0.951→0.952.
#
# 별도 가산점(_TOOL_MATCH_BONUS)은 시도했다가 되돌렸다(0.06 → full top1 0.940, r@3 0.976).
# "수세미로 세면대를 닦으세요"가 '차체를 스펀지로 닦는다'로 갔다 — 수세미↔스펀지
# 동의어에 가산점이 붙으니 세차 자산이 세면대 자산을 이겼다. 동사 가산점(_VERB_MATCH_BONUS)
# 과 달리 도구는 여러 동작에 공유돼서, 밀어올리면 잡음이 된다.

# frame.object / frame.object_detail 로 가산점을 주는 것은 시도했다가 되돌렸다.
#
# 실패 사례를 보면 대상이 갈라줄 것 같았다 — "포장 테이프를 챙기세요"에 '빈 포장 봉투를
# 준비한다'가 붙거나, "바코드를 찍어 계산하세요"에 '상품의 수량을 확인한다'가 붙었다.
# 실제로 그 두 건은 고쳐졌다. 그런데 회귀가 더 많았다:
#   - 대상 명사는 한 직무 안에서 널리 공유된다(제품·상품·부품·봉투). 가산점을 주면
#     오답까지 같이 올라가고, 전체 점수가 올라 임계값을 넘는 것이 늘어난다.
#     실측: wrong_accept 0.020 → 0.050+, gap_declined 0.895 → 0.789 (크기 무관).
#   - object_detail은 더 나빴다. '정해진', '포장' 같은 흔한 수식어에 점수를 줘서
#     "정해진 개수만큼 제품을 세어주세요"가 '정해진 수량만큼 제품을 담는다'로 갔다.
#
# 가산이 아니라 '질의가 명백히 다른 대상을 말할 때 깎는' 방향이라야 할 텐데, 질의에서
# 대상을 확실히 뽑아내는 것이 선행돼야 한다. 지금은 그 근거가 없다.


class _QueryFeatures:
    """질의를 한 번만 분석해 전체 AAC 자산에 재사용한다.

    예전에는 자산마다 형태소 추출을 다시 해서 질의 하나에 자산 수만큼 반복해서 돌았다.
    """

    __slots__ = ("norm", "tokens", "bigrams", "lemmas", "tools", "negative")

    def __init__(self, query: str) -> None:
        self.norm = _normalize(query)
        self.lemmas = _verb_lemmas(query)
        # 질의에 도구 이름이 있으면 동의어까지 넓혀 둔다("대걸레" -> {"대걸레","밀대"}).
        self.tools = _expand_tools(_tokens(query) & set(_TOOL_SYNONYM_MAP))
        # 활용형에서 뽑은 원형을 토큰에 더한다. 자산 검색어는 원형이라 이게 없으면
        # "갈아주세요"와 "갈다"가 만나지 못한다.
        self.tokens = _tokens(query) | self.lemmas | self.tools
        self.bigrams = _bigrams(query)
        self.negative = _is_negative_text(query)


def _relevance(asset: dict, qf: _QueryFeatures) -> float:
    """질의와 자산의 순수 유사도. 맥락 가중치가 섞이지 않는다.

    라벨과 검색어를 각각 재고 높은 쪽을 쓴다. 합치지 않는 이유는 검색어를 라벨에 이어
    붙이면 Jaccard 분모가 커져 점수가 희석되기 때문이다 — 검색어를 많이 가진 자산이
    오히려 손해를 본다. max를 쓰면 검색어는 도움만 주고 깎지 않는다.
    """
    q_norm, q_tokens, q_bigrams = qf.norm, qf.tokens, qf.bigrams
    if not q_norm:
        return 0.0

    label_score = _text_similarity(
        q_norm, q_tokens, q_bigrams,
        asset["_norm"], asset["_tokens"], asset["_bigrams"],
    )
    keyword_score = _text_similarity(
        q_norm, q_tokens, q_bigrams,
        asset.get("_kw_norm", ""), asset.get("_kw_tokens", set()),
        asset.get("_kw_bigrams", set()),
    )
    score = max(label_score, _KEYWORD_WEIGHT * keyword_score)

    # 동작이 같으면 직접 가산한다. "원두를 갈아주세요"의 '갈다'가 CAFE_013의 검색어
    # '갈다'와 만나도, Jaccard 안에서는 검색어 7개 중 1개라 묻힌다.
    if qf.lemmas and qf.lemmas & asset.get("_lemmas", set()):
        score += _VERB_MATCH_BONUS
    return score


# 한국어 종결어미. 이걸로 끝나면 '무엇을 하라'는 지시문이고, 아니면 명사구다.
_SENTENCE_ENDINGS = ("세요", "십시오", "주십시오", "합니다", "습니다", "해요", "요", "다", "라", "자")

# 지시문에 사물 카드가 걸렸을 때 관련도를 깎는 비율. 가산점이 아니라 곱셈인 이유는
# 확신이 클수록 더 크게 깎여야 하기 때문이다(도구 카드는 점수가 높을수록 더 위험하다).
_OBJECT_CARD_PENALTY = 0.55


# 질의의 action_type과 자산의 verb_class가 서로 달라도 정답인 조합들.
# 정답셋의 정답 쌍을 실측해서 정했다(둘 다 구체적인 66건 중 일치 55 / 불일치 11).
# 불일치는 '물건을 옮기고 정리한다' 계열에 몰려 있었다 — 담다/넣다/놓다는 사람마다
# move로도 pack으로도 분류한다. 이 묶음 안에서는 벌점을 주지 않는다.
_COMPATIBLE_CLASSES: tuple[frozenset[str], ...] = (
    frozenset({"move", "pack", "stack", "sort"}),
    frozenset({"observe", "operate"}),
)

# 동사 계열이 어긋날 때 관련도를 깎는 비율. 하드 페널티가 아닌 이유는 불일치가
# '틀렸다'가 아니라 '틀렸을 가능성이 높다'이기 때문이다(실측 5:1).
_VERB_CLASS_PENALTY = 0.85


def _verb_class_penalty(asset: dict, action_type: str | None) -> float:
    """동작 계열이 맞지 않으면 1보다 작은 값을 돌려준다(곱한다)."""
    if not action_type or action_type == "other":
        return 1.0
    verb_class = asset.get("_verb_class")
    # 사물 카드이거나 인덱스에 없으면 판단 근거가 없다 — 깎지 않는다.
    if not verb_class or verb_class == "other":
        return 1.0
    if verb_class == action_type:
        return 1.0
    for group in _COMPATIBLE_CLASSES:
        if action_type in group and verb_class in group:
            return 1.0
    return _VERB_CLASS_PENALTY


def _is_instruction(text: str) -> bool:
    """질의가 '무엇을 하라'는 문장인가, 아니면 물건 이름인가.

    작업 단계는 항상 지시문이다("얼음통을 씻어주세요"). 반면 사업주가 검색창에 직접
    치는 것은 대개 명사구다("얼음통"). 사물 카드는 후자에만 맞다.
    """
    stripped = text.strip().rstrip(".!?？！ ").strip()
    return stripped.endswith(_SENTENCE_ENDINGS)


def _tiebreak(asset: dict, preferred_job: str | None, action_type: str | None) -> float:
    """관련도가 비슷한 후보들의 순서만 바꾸는 작은 보정값."""
    bonus = 0.0

    # 업종 맥락이 있으면 같은 직무를 선호하고, 다른 직무에는 그 절반의 벌점을 준다.
    if preferred_job:
        if asset.get("job") == preferred_job:
            bonus += _JOB_TIEBREAK
        else:
            bonus -= _JOB_MISMATCH_PENALTY

    # 작업 단계는 보통 도구/보조 카드보다 동작 카드가 맞다.
    if action_type and action_type != "other":
        if asset.get("asset_type") == "action":
            bonus += _ASSET_TYPE_TIEBREAK
        else:
            bonus -= _ASSET_TYPE_TIEBREAK

    return bonus


# ta3woong님 브랜치(feature/local-aac, 26e00ec)의 "specificity penalty" 아이디어를
# 이식해 봤다가 되돌렸다 — 질의에 없는 세부 조건(냉장/불량/배송 등)이 자산에만 있으면
# 감점하는 것. 방향은 내가 되돌린 object 가산점(cd3972e)과 반대(가산이 아니라 감점)라
# 다를 줄 알았는데, 실측하니 아주 작은 크기(0.03)에서도 즉시 회귀했다(top1 0.964→0.952).
#
# 원인: 정답 자체가 세부 조건 단어를 쓰고 질의가 그걸 다른 말로 바꿔 쓰면 정답이 벌점을
# 받는다. 예) "상태가 안 좋은 제품을 빼내세요"의 정답은 "불량 제품을 골라낸다"인데
# 질의가 "불량"이라고 안 썼다는 이유로 벌점을 먹고, "다른 제품을 골라낸다"(오답, 벌점 없음)
# 에게 진다. 세부 조건 유무가 아니라 그 단어를 '질의가 그대로 썼는지'만 보는 게 문제라,
# 사업주가 다르게 말하는 표현일수록(정확히 이 프로젝트의 골든셋 작성 원칙과 충돌한다)
# 더 크게 틀린다. 크기를 조절해서 될 문제가 아니라 메커니즘 자체가 안 맞는다.


def _score_asset(asset: dict, qf: _QueryFeatures, preferred_job: str | None,
                 action_type: str | None, is_instruction: bool = False) -> float:
    relevance = _relevance(asset, qf)

    # 사물 카드 게이트 — 지시문에는 동작 그림이 맞다. "얼음통을 씻어주세요"에 도구
    # 카드 '얼음통'이 붙으면 근로자는 통을 보기만 하고 무엇을 할지 모른다.
    # 가중치(±0.015)로는 못 막았다 — 실측 격차가 0.05~0.15였다.
    if is_instruction and asset.get("_is_object_card"):
        relevance *= _OBJECT_CARD_PENALTY

    # 동사 호환성 — 명사만 겹치면 동작이 달라도 올라오던 것을 누른다.
    # "넘어진 상품을 세워주세요"에 "냉동 상품을 냉동 진열대에 놓는다"가 붙던 문제.
    relevance *= _verb_class_penalty(asset, action_type)

    return max(0.0, min(relevance + _tiebreak(asset, preferred_job, action_type), 1.0))


def _dedupe(ranked: list[tuple[float, dict]]) -> list[tuple[float, dict]]:
    """같은 그림을 결과에 두 번 넣지 않는다(점수 높은 쪽만 남긴다).

    두 종류의 중복을 걷어낸다:
    - 같은 `group_id`의 시각 변형(ASSEMBLY_031_01~04). 어느 것이 나와도 같은 행동이다.
    - 같은 직무에서 라벨이 완전히 같은 자산(CAFE_009/CAFE_026 "얼음을 컵에 담는다").
      데이터셋 쪽 중복이지만, 사용자에게 같은 카드가 두 번 보이는 건 막아야 한다.

    입력은 점수 내림차순으로 정렬돼 있어야 한다.
    """
    seen_groups: set[str] = set()
    seen_labels: set[tuple[str, str]] = set()
    out: list[tuple[float, dict]] = []
    for score, asset in ranked:
        group = asset.get("group_id") or asset["id"]
        label_key = (asset.get("job", ""), asset.get("label", ""))
        if group in seen_groups or label_key in seen_labels:
            continue
        seen_groups.add(group)
        seen_labels.add(label_key)
        out.append((score, asset))
    return out





def search_assets(query: str, context: dict | None = None, limit: int = 5) -> list[dict]:
    """자연어 질의와 가장 가까운 AAC 자산을 찾는다.

    검색 정책:
    - context.job이 명시된 경우: 해당 직무 자산만 검색(hard gate)
    - job이 명시되지 않은 경우: infer_job()은 기존처럼 약한 tiebreak로만 사용
    - 지시문에서는 긍정/금지 의미가 반대인 action 카드를 후보에서 제외
    - 나머지 점수 계산은 기존 relevance/verb_class/tiebreak 로직을 그대로 사용
    """
    ctx = dict(context or {})
    query = str(query or "").strip()
    if not query:
        return []

    explicit_job = _explicit_job(ctx)
    preferred_job = explicit_job or infer_job(ctx, query)
    action_type = str(ctx.get("action_type") or "").strip() or None

    sentence = str(ctx.get("sentence") or query).strip()
    is_instruction = _is_instruction(sentence)
    qf = _QueryFeatures(query)

    assets = load_assets()

    # LLM/상위 계층에서 canonical job을 명시한 경우 다른 직무 카드를 섞지 않는다.
    # 반대로 business_type/query에서 추론된 job은 hard gate하지 않는다.
    if explicit_job:
        assets = [asset for asset in assets if asset.get("job") == explicit_job]

    ranked: list[tuple[float, dict]] = []
    for asset in assets:
        # "조인다"와 "조이지 않는다"처럼 의미가 반대인 카드는 지시문에서 제외한다.
        # 사물 카드/명사 검색에는 이 gate를 적용하지 않는다.
        if (
            is_instruction
            and asset.get("asset_type") == "action"
            and bool(asset.get("_negative", False)) != qf.negative
        ):
            continue

        score = _score_asset(
            asset,
            qf,
            preferred_job,
            action_type,
            is_instruction,
        )
        if score <= 0:
            continue
        ranked.append((score, asset))

    ranked.sort(key=lambda item: (-item[0], item[1].get("id", "")))
    ranked = _dedupe(ranked)

    results: list[dict] = []
    for score, asset in ranked[: max(1, limit)]:
        results.append({
            "asset_id": asset["id"],
            "group_id": asset.get("group_id") or asset["id"],
            "job": asset.get("job", ""),
            "asset_type": asset.get("asset_type", "action"),
            "label": asset.get("label", ""),
            "image_url": f"/api/aac/images/{asset.get('image', '')}",
            "score": round(score, 4),
        })
    return results


def decide(results: list[dict]) -> dict:
    """검색 결과를 자동 채택할지 판정한다.

    절대 임계값 하나로는 정답과 오답이 갈리지 않는다. 임계값 스윕 곡선에 오답채택과
    사람확인이 동시에 낮은 구간이 없었고, 1순위 오답의 대부분은 2순위와의 점수 차
    (margin)가 0.01 이하였다 — "확신 있는 정답"이 아니라 사실상 동전 던지기였다.
    그래서 두 조건을 함께 본다:

      1) 1순위 점수가 임계값 이상인가   → 무관한 카드를 거른다
      2) 1순위와 2순위의 차가 충분한가   → 비슷한 후보 중 아무거나 고르지 않는다

    거절 사유를 구분해 돌려준다. 후보가 아예 없는 것과, 후보는 여럿인데 못 고르는 것은
    검토 화면에서 다르게 다뤄야 한다(전자는 폴백, 후자는 후보를 보여주고 사람이 선택).

    두 기본값 모두 eval/run_match_eval.py 의 스윕으로 교정했다. 스코어러를 고치면
    점수 척도가 바뀌므로 반드시 다시 교정해야 한다.

    반환: {"match": dict|None, "reason": str, "candidates": list, "margin": float}
      reason — "accepted" | "no_candidate" | "low_score" | "low_margin"
    """
    threshold = float(os.getenv("AAC_MATCH_THRESHOLD", "0.22"))
    min_margin = float(os.getenv("AAC_MATCH_MIN_MARGIN", "0.02"))

    if not results:
        return {"match": None, "reason": "no_candidate", "candidates": [], "margin": 0.0}

    best = results[0]
    # 후보가 하나뿐이면 비교 대상이 없다. 경쟁자가 없으므로 여유는 최대로 본다.
    margin = best["score"] - results[1]["score"] if len(results) > 1 else best["score"]

    if best["score"] < threshold:
        return {"match": None, "reason": "low_score", "candidates": results, "margin": margin}
    if margin < min_margin:
        return {"match": None, "reason": "low_margin", "candidates": results, "margin": margin}
    return {"match": best, "reason": "accepted", "candidates": results, "margin": margin}


def search_for_step(keywords: list[str], context: dict | None = None) -> dict | None:
    """단계에 붙일 AAC 자산을 고른다. 확신이 없으면 None(폴백)."""
    return search_for_step_detailed(keywords, context)["match"]


def search_for_step_detailed(keywords: list[str], context: dict | None = None) -> dict:
    """search_for_step에 판정 근거를 더한 형태. decide()의 반환을 그대로 준다."""
    ctx = dict(context or {})
    sentence = str(ctx.get("sentence") or "").strip()
    query_parts = [sentence] + [str(k).strip() for k in keywords if str(k).strip()]
    query = " ".join(part for part in query_parts if part)
    return decide(search_assets(query, ctx, limit=5))
