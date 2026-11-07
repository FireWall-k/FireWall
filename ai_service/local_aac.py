from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import embeddings
import korean_verbs
from taxonomy import ALIAS_WEIGHT, JOB_ALIASES

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_HANGUL_RE = re.compile(r"[가-힣]")

# 직무 사전은 LLM 분해 검증·규칙 폴백과 같아야 하므로 taxonomy 한 곳에 둔다.
_JOB_ALIASES = JOB_ALIASES
_ALIAS_WEIGHT = ALIAS_WEIGHT

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
    #
    # '하다' 원형을 반드시 '한다'보다 먼저 검사한다. 순서가 바뀌면 "정리하다"(원형)는
    # '다'만 떨어져 '정리하'가 남고 "정리한다"(활용형)는 '한다'가 떨어져 '정리'가 남아,
    # 같은 뜻인데 토큰이 달라져 자산 검색어(원형이 많다)와 질의(활용형이 많다)가 서로
    # 못 만난다. 실사용 중 발견 — "의자들을 정리하세요"가 라벨에 '정리'가 그대로 박힌
    # 무관한 자산(상품 정리)에 밀렸다.
    for ending in ("하세요", "해주세요", "합니다", "하십시오", "하다", "한다", "해요", "세요", "니다", "다"):
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


# ---- 동사 원형 -------------------------------------------------------------------
# 활용 규칙은 korean_verbs에 있다. 여기서는 '어떤 동사를 아는가'(닫힌 사전)를 정한다.

# 인덱스에는 없지만 흔해서, 모르면 다른 동사로 잘못 읽히는 동사들. 그림과 맞을 일은 없고
# (자산 원형에 없다) '이 어절은 저 동사가 아니다'를 알려 주는 용도다.
#   - 들어오다/들어가다 → 모르면 '들다', 떨어지다 → '떨다', 여쭈다 → '열다'(여-)로 읽힌다.
#   - 개다·두르다·빨다처럼 인덱스 검색어에 활용형('갠다'·'빤다')으로만 들어 있는 원형.
#   - 하다는 '체크를 해요'처럼 앞 절의 범위(조건절인지)를 정하는 데 필요하다.
_EXTRA_VERBS = frozenset({
    "들어오다", "들어가다", "나오다", "나가다", "다가오다", "떨어지다", "흩어지다", "쏟아지다",
    "넘어지다", "차다", "비다", "남다", "남기다", "먹다", "마시다", "앉다", "여쭈다", "걷다",
    "끝나다", "울리다", "타다", "두르다", "개다", "빨다", "뜯다", "묻다", "있다", "되다",
    "맞다", "나다", "하다", "꽂히다", "적히다", "걸리다", "붙다", "쌓이다", "묻히다",
    "부르다", "쉬다",
    # 반대말 벌점(_VERB_ANTONYMS)에 쓰이는데 인덱스 원형에는 없는 동사. 모르면 "상자를 내려요"에서
    # 동사를 하나도 못 찾아 '싣다·올리다' 그림을 거르지 못한다.
    "내리다", "박다", "대다", "재다",
    # '신다'는 겉모양이 '-ㄴ다' 평서형과 같아('실다'의 활용형으로도 읽힌다) 원형임을 밝혀 둔다.
    "신다",
})

# ㄹ탈락으로 만든 표면형이 한 글자가 되면서, 훨씬 흔한 다른 동사의 원형과 우연히
# 같은 글자가 되는 경우가 있다. '갈다'(갈아주세요로 이미 원래 어간 '갈'이 잡힌다)의
# 탈락형 '가'가 대표적 — 이동을 뜻하는 '가다'의 원형과 같은 글자라, "고객님 댁에
# 가세요"·"창고에 가세요" 같은 문장에서 커피 원두를 "간다"는 엉뚱한 동사로 잡혔다.
# '갈다'의 실제 존댓말 요청형은 거의 항상 모음축약형 '갈아(주세요)'라 기본 어간 '갈'만
# 으로 충분히 잡힌다 — 탈락형 '가'는 실익 없이 충돌만 만들어 제외한다.
_RIEUL_DROP_EXCLUDE_LEMMAS = frozenset({"갈다"})


def _raw_index_verbs() -> set[str]:
    words: set[str] = set()
    for entry in load_index().values():
        verb = (entry.get("frame") or {}).get("verb")
        if verb:
            words.add(verb)
        # 검색어에도 '갈다', '비질하다' 같은 원형이 들어 있다('갈다'는 두 글자다).
        for word in entry.get("keywords_ko", []):
            if isinstance(word, str) and word.endswith("다"):
                words.add(word)
    return words


@lru_cache(maxsize=1)
def _lemma_normalization() -> dict[str, str]:
    """인덱스의 '-ㄴ다/-는다' 평서형('갠다'·'건다'·'든다'·'놓는다')을 원형으로 바꾸는 표.

    인덱스 검색어·frame.verb 일부가 원형이 아니라 활용형으로 들어 있다. 질의에서 뽑는 것은
    원형이라 이대로는 영영 만나지 못한다(예: '이불을 갠다'의 verb가 '갠다'). 데이터를 고치는
    대신(임베딩 digest가 바뀐다) 읽을 때 원형으로 맞춘다. 원형으로 설명이 안 되면('신다'는
    '신-+-다'이지 '시-+-ㄴ다'가 아니다) 그대로 둔다.
    """
    raw = {w for w in _raw_index_verbs() if korean_verbs.is_plain_lemma(w)} - set(_MISSPELLED_LEMMAS)
    conjugated = {w for w in raw if korean_verbs.is_conjugated_form(w)}
    plain = (raw - conjugated) | _EXTRA_VERBS
    base = korean_verbs.Analyzer(plain, generic_hada=False,
                                 rieul_drop_exclude=_RIEUL_DROP_EXCLUDE_LEMMAS)
    table: dict[str, str] = {}
    for word in conjugated:
        if word in plain:
            continue  # 원형으로도 쓰이는 낱말(신다)은 바꾸지 않는다.
        finals = sorted({p.lemma for p in base.analyze_word(word)
                         if p.kind == korean_verbs.FINAL and p.lemma != word})
        if len(finals) == 1:
            table[word] = finals[0]
    return table


# 인덱스 검색어에 섞인 잘못된 원형. ㄷ 불규칙 동사의 활용형('실어')에서 거꾸로 만든 틀린
# 원형('실다')이 대표적이다 — 바른 원형('싣다')과 갈라져서, 같은 동작인데 한쪽 그림에만 원형이
# 하나 더 붙고 질의에서도 두 원형이 나와 토큰만 늘린다. 표준 원형으로 모은다.
_MISSPELLED_LEMMAS = {"실다": "싣다"}


def _normalize_lemma(word: str) -> str:
    word = _MISSPELLED_LEMMAS.get(word, word)
    return _lemma_normalization().get(word, word)


@lru_cache(maxsize=1)
def _verb_analyzer() -> korean_verbs.Analyzer:
    """인덱스 동사(원형으로 맞춘 것) + 보충 동사로 만든 분석기."""
    lemmas = {_normalize_lemma(w) for w in _raw_index_verbs()} | _EXTRA_VERBS
    lemmas -= set(_MISSPELLED_LEMMAS)
    return korean_verbs.Analyzer(lemmas, rieul_drop_exclude=_RIEUL_DROP_EXCLUDE_LEMMAS)


def _verb_lemmas(text: str) -> set[str]:
    """지시문에서 '해야 할 동작'의 동사 원형을 뽑는다.

    "원두를 갈아주세요" → {'갈다'}. 자산 쪽 검색어는 원형('갈다')이라 이 변환이 없으면
    질의 토큰('갈아주')과 영영 만나지 못한다 — 인덱스를 만들어도 아무 효과가 없다.

    korean_verbs가 어미까지 확인하므로 명사·부사 어절("쓰레기를"·"가지런히")에서 동사를
    뽑지 않고, 보조 용언("꺼내 오세요"의 '오다', "닦아 주세요"의 '주다")은 본동사로 바꾸고,
    조건절·관형절("손님이 찾으면"·"다 붙인 박스")의 동사는 뺀다.

    한 표면형이 서로 다른 원형에 동시에 걸리는 경우가 있다("쓰"는 '쓰다'(사용/착용)
    와 '쓸다'(쓸기) 둘 다에서 나온다 — "쓰세요"는 한국어 자체가 중의적이다). 같은
    길이로 묶인 원형을 전부 후보로 남긴다 — 최종 판단(직무·명사 겹침)은 이미
    `_score_asset`이 한다: 문맥과 맞는 자산만 가산점의 이득을 본다.
    """
    return _verb_analyzer().main_lemmas(text)


# 같은 동작을 가리키는 다른 동사. 일상어와 그림 라벨(표준 설명어)이 다른 낱말을 쓰는 쌍만 둔다.
#   - 훔치다: '걸레로 훔치다'는 물기·먼지를 닦는다는 뜻의 일상어다(표준국어대사전 훔치다②).
#   - 개다: 빨래·이불을 '갠다'는 것은 접는 동작이다(개다③). 라벨은 '접는다'로 쓴다.
# 방향이 반대인 쌍은 넣지 않는다(반대말은 _VERB_ANTONYMS). 질의 쪽만 넓힌다 — 자산 원형을
# 바꾸면 반대말 벌점·대상 게이트가 함께 흔들린다. 그림별 동의 동사 보강은 인덱스 단계(P4) 몫이다.
_VERB_SYNONYMS: tuple[frozenset[str], ...] = (
    frozenset({"훔치다", "닦다"}),
    frozenset({"개다", "접다"}),
)


def _expand_verb_synonyms(lemmas: set[str]) -> set[str]:
    out = set(lemmas)
    for group in _VERB_SYNONYMS:
        if out & group:
            out |= group
    return out


def _is_verb_word(word: str) -> bool:
    """어절이 동사 활용형인가(조건·관형형 포함). 대상 명사를 고를 때 동사를 거르는 데 쓴다."""
    return _verb_analyzer().is_verb_word(word)


def _reconcile_frame_verb(verb: str | None, label: str) -> str | None:
    """frame.verb가 라벨의 동사와 활용형만 같은 다른 동사면 라벨 쪽으로 바로잡는다.

    인덱스를 만든 LLM이 '든다'(들다)를 '듣다'로 적은 경우가 있다 — 두 동사는 '들어'라는
    활용형이 같다(ㄷ 불규칙). 라벨이 그림의 정의이므로, 라벨에서 읽은 동사에 frame.verb가
    없고 둘의 '-어' 활용형이 겹칠 때만 라벨의 동사로 바꾼다(그 밖의 불일치는 건드리지 않는다).
    """
    if not verb:
        return verb
    verb = _normalize_lemma(verb)
    analyzer = _verb_analyzer()
    label_lemmas = {p.lemma for _, p in analyzer.analyze_text(label)}
    if not label_lemmas or verb in label_lemmas or " " in verb:
        return verb
    verb_forms = korean_verbs.a_forms(verb[:-1])
    for lemma in sorted(label_lemmas):
        if korean_verbs.a_forms(lemma[:-1]) & verb_forms:
            return lemma
    return verb


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
    # 업종을 안 넣으면 단계 문장 하나로는 직무를 못 알아낼 때가 많다("큰 나사를
    # 나누세요"만 봐서는 조립인지 알 수 없다). 원문 전체("부품 상자에서 나사를...")에는
    # 대개 직무를 알려주는 단어가 있으므로 보조 신호로 함께 본다.
    if ctx.get("raw_input"):
        haystack += " " + str(ctx["raw_input"])
    norm = _normalize(haystack)
    scores: list[tuple[float, str]] = []
    for job, aliases in _JOB_ALIASES.items():
        count = sum(_ALIAS_WEIGHT.get(alias, 1.0) for alias in aliases if alias.lower() in norm)
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

    # 첫 번째로 걸리는 직무를 고르면 사전 순서에 따라 결과가 달라진다("매장 진열" → 마트).
    # infer_job()과 같은 가중치로 모든 직무를 점수화하고, 동점이면 더 긴 별칭이 맞은 쪽을 고른다.
    best: tuple[float, int, str] | None = None
    for job, aliases in _JOB_ALIASES.items():
        score = 0.0
        longest = 0
        for alias in aliases:
            alias_norm = _normalize(alias)
            if alias_norm and (norm == alias_norm or alias_norm in norm):
                score += _ALIAS_WEIGHT.get(alias, 1.0)
                longest = max(longest, len(alias_norm))
        if score and (best is None or (score, longest) > best[:2]):
            best = (score, longest, job)
    return best[2] if best else None


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
        # frame.verb를 원형으로 맞추고, 라벨과 활용형만 같은 다른 동사면 바로잡는다
        # ('든다'를 '듣다'로 적은 인덱스 오류). 인덱스 dict는 공유되므로 복사해서 고친다.
        fixed_verb = _reconcile_frame_verb(frame.get("verb"), label)
        if fixed_verb != frame.get("verb"):
            frame = {**frame, "verb": fixed_verb}

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
        # 활용형으로 들어 있는 검색어('갠다'·'건다')는 원형도 함께 넣는다 — 질의 원형과 만나게.
        lemmas |= {_normalize_lemma(w) for w in lemmas}
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
# 앞 절 동사("덮고 … 맞추세요"의 '덮다')만 맞을 때. 지시의 중심은 문장 끝 서술어라 그 동사와
# 맞는 그림이 앞 단계 동사와 맞는 그림보다 위에 와야 한다. 앞 단계도 할 일이므로 0은 아니다.
# 0.03/0.05/0.07을 재 보니 0.05가 개발 sentence top1이 가장 높고 오답 채택은 같았다.
_SIDE_VERB_MATCH_BONUS = 0.05

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

    __slots__ = ("norm", "tokens", "bigrams", "lemmas", "head_lemmas", "match_lemmas",
                 "match_head_lemmas", "tools", "negative",
                 "ko_norm", "ko_tokens", "ko_bigrams", "ko_share")

    def __init__(self, query: str) -> None:
        self.norm = _normalize(query)
        roles = _verb_analyzer().lemma_roles(query)
        self.lemmas = set(roles)
        self.head_lemmas = {lemma for lemma, role in roles.items() if role == "head"}
        # 동사 가산(_relevance)에서만 동의 동사까지 넓힌다. 토큰에 넣으면 Jaccard 분모만 커진다.
        self.match_head_lemmas = _expand_verb_synonyms(self.head_lemmas)
        self.match_lemmas = _expand_verb_synonyms(self.lemmas) | self.match_head_lemmas
        # 질의에 도구 이름이 있으면 동의어까지 넓혀 둔다("대걸레" -> {"대걸레","밀대"}).
        self.tools = _expand_tools(_tokens(query) & set(_TOOL_SYNONYM_MAP))
        # 활용형에서 뽑은 원형을 토큰에 더한다. 자산 검색어는 원형이라 이게 없으면
        # "갈아주세요"와 "갈다"가 만나지 못한다.
        #
        # 중심 동사의 원형만 더한다. 앞 절 동사("수량표를 보고 … 확인하세요"의 '보다')까지
        # 더하면 Jaccard 분모만 커져 정답과 2위의 여유가 줄었다(골든 sentence 정답 자동 채택 −1).
        # 앞 절 동사는 _relevance의 작은 가산(_SIDE_VERB_MATCH_BONUS)으로만 반영한다.
        #
        # 동의 동사(훔치다→닦다)도 토큰에 넣는다. 그림 검색어에 일상어('훔치다')가 우연히 들어 있는
        # 그림만 Jaccard에서 앞서고, 같은 동작을 표준어('닦다')로 적은 그림은 밀리는 일을 막는다.
        # 묶음이 두 낱말짜리라 분모는 한 칸만 는다.
        self.tokens = _tokens(query) | self.match_head_lemmas | self.tools
        self.bigrams = _bigrams(query)
        self.negative = _is_negative_text(query)

        # 라벨 채널용 '한글 부분'. 그림 라벨은 모두 한국어라(영문 토큰 0개) 질의의 영문 낱말은
        # 라벨과 절대 겹치지 않고 Jaccard 분모만 키운다. 분모에 1을 더하는 효과는 짧은 라벨에
        # 더 크게 작용해서, 영문이 섞인 질의(LLM symbol_query에 'apron'·'plastic bag' 같은 영어
        # 명사가 섞여 나온다)에서는 영문 낱말 수가 '어느 그림이 이기는가'를 흔든다.
        # 검색어(keywords_en)에는 영문이 있으므로 검색어 채널은 질의 전체로 그대로 잰다.
        # 한글이 하나도 없는 질의는 비울 수 없으니 전체로 잰다.
        ko_query = " ".join(t for t in _TOKEN_RE.findall(query) if _HANGUL_RE.search(t))
        if ko_query:
            self.ko_norm = _normalize(ko_query)
            self.ko_tokens = {t for t in self.tokens if _HANGUL_RE.search(t)}
            self.ko_bigrams = _bigrams(ko_query)
        else:
            self.ko_norm, self.ko_tokens, self.ko_bigrams = self.norm, self.tokens, self.bigrams
        # 질의 중 라벨과 대조할 수 있는 몫. 라벨 점수에 곱한다 — 아래 _relevance 주석 참고.
        self.ko_share = len(self.ko_tokens) / len(self.tokens) if self.tokens else 1.0


def _relevance(asset: dict, qf: _QueryFeatures) -> float:
    """질의와 자산의 순수 유사도. 맥락 가중치가 섞이지 않는다.

    라벨과 검색어를 각각 재고 높은 쪽을 쓴다. 합치지 않는 이유는 검색어를 라벨에 이어
    붙이면 Jaccard 분모가 커져 점수가 희석되기 때문이다 — 검색어를 많이 가진 자산이
    오히려 손해를 본다. max를 쓰면 검색어는 도움만 주고 깎지 않는다.
    """
    q_norm, q_tokens, q_bigrams = qf.norm, qf.tokens, qf.bigrams
    if not q_norm:
        return 0.0

    # 라벨은 질의의 한글 부분과만 잰다(_QueryFeatures 주석). 그 위에 '한글 토큰 비율'을 곱하는
    # 이유: 영문 낱말을 그냥 빼면 질의 점수 척도가 올라가 임계값(0.215, 희석된 척도에서 보정)을
    # 넘는 오답이 늘었다(개발 full 오답 5→8, 골든 full 4→9). 확인 못 한 몫만큼 확신을 낮추되
    # 모든 그림에 같은 비율로 곱하므로, 영문은 더 이상 그림 사이 순서를 바꾸지 못한다.
    # 비율 지수를 0.5/0.75/0.85로 재 봤는데 1(그대로 곱하기)만 오답 증가 없이 top1이 올랐다.
    label_score = qf.ko_share * _text_similarity(
        qf.ko_norm, qf.ko_tokens, qf.ko_bigrams,
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
    asset_lemmas = asset.get("_lemmas", set())
    if qf.match_head_lemmas & asset_lemmas:
        score += _VERB_MATCH_BONUS
    elif qf.match_lemmas & asset_lemmas:
        score += _SIDE_VERB_MATCH_BONUS
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


# 실사용 중 발견: "남은 재료를 꺼내세요"(냉장고에서 빼기)가 "남은 재료를 냉장고에
# 넣는다"(CAFE_088)로 붙었다. 원인은 verb_class가 방향을 구분 못 하는 것 —
# '넣다'/'꺼내다'는 둘 다 verb_class="move"라 _verb_class_penalty가 안 걸린다.
# 동사 원형 매칭(_verb_lemmas)도 일치할 때만 가산할 뿐 불일치를 벌점 주지 않으므로,
# 진짜 반대말 쌍만 좁게 골라 따로 깎는다(동의어까지 걸리면 회귀하므로 목록을 넓히지 않는다).
_VERB_ANTONYMS: tuple[frozenset[str], ...] = (
    frozenset({"넣다", "꺼내다"}),
    frozenset({"열다", "닫다"}),
    frozenset({"켜다", "끄다"}),
    frozenset({"붙이다", "떼다"}),
    frozenset({"올리다", "내리다"}),
    # 아래는 개발셋 오답 채택에서 확인한 '같은 대상, 반대 방향' 쌍이다. 모두 verb_class가
    # 같아(move/operate) 계열 벌점이 안 걸리던 것들이다. 동의어끼리(착용하다·입다)는
    # 묶지 않는다 — 각 쌍은 한쪽이 다른 쪽을 되돌리는 동작이어야 한다.
    frozenset({"끼우다", "빼다"}),
    frozenset({"끼우다", "빼내다"}),
    frozenset({"착용하다", "벗다"}),
    frozenset({"입다", "벗다"}),
    frozenset({"쓰다", "벗다"}),
    frozenset({"끼다", "벗다"}),
    frozenset({"채우다", "비우다"}),
    frozenset({"꽂다", "뽑다"}),
    frozenset({"싣다", "내리다"}),
)
_VERB_ANTONYM_PENALTY = 0.4


def _verb_antonym_penalty(asset: dict, query_lemmas: set[str]) -> float:
    """질의 동사와 자산 동사가 진짜 반대말이면 깎는다(동의어·무관한 동사는 안 깎는다)."""
    verb = (asset.get("_frame") or {}).get("verb")
    if not verb or not query_lemmas:
        return 1.0
    for group in _VERB_ANTONYMS:
        if verb in group and (query_lemmas & group) - {verb}:
            return _VERB_ANTONYM_PENALTY
    return 1.0


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


# 임베딩 유사도를 규칙 점수에 '더하는' 항: w × max(0, 유사도 − 기준).
# 가산만 한다 — 유사도가 낮다고 깎지 않는다("흔한 신호 부재를 감점하는" 방식은 여러 번
# 회귀했다). 기준 아래의 유사도는 잡음이라 0으로 본다.
#
# 모델마다 코사인 분포가 달라 기본값이 제공자별로 다르다(AAC_EMBED_PROVIDER):
#   (가중치, 기준, 채택 임계값, 여유)
#   openai text-embedding-3-large 256 — 0.5 / 0.4  / 0.35 / 0.02 (예전 블라인드 보정)
#   local  paraphrase-multilingual-MiniLM-L12-v2 — 0.3 / 0.65 / 0.24 / 0.015
#          (개발셋 full·sentence 스윕, eval/README.md "로컬 임베딩"). MiniLM은 무관한 문장끼리도
#          0.3~0.5가 흔해 기준이 높고, 가산이 크면 규칙 점수의 순서를 너무 흔들어 가중치가 작다.
# 환경변수(AAC_EMBED_WEIGHT/BASE, AAC_EMBED_MATCH_THRESHOLD/MIN_MARGIN)를 주면 그 값이 이긴다.
_EMBED_DEFAULTS = {
    "openai": (0.5, 0.4, 0.35, 0.02),
    "local": (0.3, 0.65, 0.24, 0.015),
}


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name, "").strip()
    return float(value) if value else default


def _embed_defaults() -> tuple[float, float, float, float]:
    return _EMBED_DEFAULTS[embeddings.provider()]


def _embed_term_params() -> tuple[float, float]:
    """(가중치, 기준) — 지금 제공자의 기본값 또는 환경변수."""
    weight, base, _, _ = _embed_defaults()
    return _env_float("AAC_EMBED_WEIGHT", weight), _env_float("AAC_EMBED_BASE", base)


def _score_asset(asset: dict, qf: _QueryFeatures, preferred_job: str | None,
                 action_type: str | None, is_instruction: bool = False,
                 emb_sim: float | None = None,
                 emb_params: tuple[float, float] | None = None) -> float:
    relevance = _relevance(asset, qf)

    # 사물 카드 게이트 — 지시문에는 동작 그림이 맞다. "얼음통을 씻어주세요"에 도구
    # 카드 '얼음통'이 붙으면 근로자는 통을 보기만 하고 무엇을 할지 모른다.
    # 가중치(±0.015)로는 못 막았다 — 실측 격차가 0.05~0.15였다.
    if is_instruction and asset.get("_is_object_card"):
        relevance *= _OBJECT_CARD_PENALTY

    # 동사 호환성 — 명사만 겹치면 동작이 달라도 올라오던 것을 누른다.
    # "넘어진 상품을 세워주세요"에 "냉동 상품을 냉동 진열대에 놓는다"가 붙던 문제.
    relevance *= _verb_class_penalty(asset, action_type)

    # 반대 동사 — verb_class는 방향을 구분 못 해서("넣다"/"꺼내다" 둘 다 move) 위
    # 게이트를 통과한다. "남은 재료를 꺼내세요"에 "냉장고에 넣는다"가 붙던 문제.
    relevance *= _verb_antonym_penalty(asset, qf.lemmas)

    score = max(0.0, min(relevance + _tiebreak(asset, preferred_job, action_type), 1.0))
    if emb_sim is not None:
        weight, base = emb_params or _embed_term_params()
        score = min(1.0, score + weight * max(0.0, emb_sim - base))
    return score


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
    return _search(query, context, limit)[0]


def _search(query: str, context: dict | None = None, limit: int = 5) -> tuple[list[dict], bool]:
    """자연어 질의와 가장 가까운 AAC 자산을 찾는다. (결과, 임베딩을 썼는가)를 돌려준다
    — 채택 임계값이 임베딩 유무에 따라 달라서 함께 돌려준다.

    검색 정책:
    - context.job이 명시된 경우: 해당 직무 자산만 검색(hard gate)
    - job이 명시되지 않은 경우: infer_job()은 기존처럼 약한 tiebreak로만 사용
    - 지시문에서는 긍정/금지 의미가 반대인 action 카드를 후보에서 제외
    - 나머지 점수 계산은 기존 relevance/verb_class/tiebreak 로직을 그대로 사용
    """
    ctx = dict(context or {})
    query = str(query or "").strip()
    if not query:
        return [], False

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

    # 못 쓰면(키·파일 없음, 호출 실패) None — 그러면 임베딩 없는 기존 점수로 그대로 진행한다.
    sims = embeddings.query_similarities(query)
    emb_params = _embed_term_params() if sims is not None else None

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

        emb_sim = sims.get(asset["id"]) if sims is not None else None
        score = _score_asset(
            asset,
            qf,
            preferred_job,
            action_type,
            is_instruction,
            emb_sim,
            emb_params,
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
    return results, sims is not None


# ---- 대상 일치 게이트 -------------------------------------------------------------
# 오답 채택의 가장 큰 유형은 '동작은 같은데 대상이 다른 그림'이다("문을 닫으세요" →
# '컵에 뚜껑을 닫는다'). 대상으로 점수를 깎거나 더하는 것은 회귀했으므로(위 주석),
# 순위는 그대로 두고 자동 채택만 막는다 — 후보로는 남아 사람이 고를 수 있다.
#
# 문장의 목적어는 '명사+을/를' 어절로 잡는다. 한국어 지시문에서 목적격 조사가 붙은
# 명사가 곧 동작의 대상이고, 형태소 분석기 없이도 오탐이 적다.
_QUERY_OBJECT_RE = re.compile(r"([가-힣]+)(?:을|를)(?=\s|$|[.,!?])")

# 그림의 대상이 이런 일반 명사면 문장의 구체 대상(쿠키·빵·스티커 붙일 물건)을 포함한다.
# 대상 게이트만 쓰면 개발셋에서 '상품/제품' 그림이 정답인 3건을 잃었다 — 상위어는
# 하위어와 충돌로 보지 않는다.
_GENERIC_OBJECTS = frozenset({
    "상품", "제품", "물건", "물품", "새상품", "부품", "내용물", "구성품", "비품", "라벨", "스티커",
})

# 같은 대상을 부르는 다른 이름. 인덱스 검색어에 없어서 대상 게이트가 정답을 막는 것을
# 줄이려고 코드 쪽에 둔다(인덱스 검색어 보강은 별도 단계). 일상어↔표기어 쌍만 넣는다.
_OBJECT_SYNONYMS: tuple[frozenset[str], ...] = (
    frozenset({"뚜껑", "덮개"}),
    frozenset({"빨래", "세탁물"}),
    frozenset({"박스", "상자"}),
    frozenset({"수건", "천", "행주"}),
    frozenset({"휴지", "화장지"}),
    frozenset({"수저통", "수저함"}),
)


def _object_variants(word: str) -> set[str]:
    out = {word}
    for group in _OBJECT_SYNONYMS:
        if word in group:
            out |= group
    return out


def _query_objects(sentence: str) -> set[str]:
    return {m.group(1) for m in _QUERY_OBJECT_RE.finditer(sentence or "")}


def _object_conflict(asset: dict, sentence: str, query: str) -> bool:
    """문장이 말하는 대상과 그림의 대상이 분명히 다른가.

    판단 근거가 없으면(문장에 목적어가 없거나 그림에 대상 정보가 없으면) 충돌로 보지
    않는다 — 이 게이트는 '확실히 다를 때'만 막는다.
    """
    q_objects = _query_objects(sentence)
    if not q_objects:
        return False
    obj = (asset.get("_frame") or {}).get("object")
    if not obj:
        return False
    obj_norm = _normalize(obj)
    if obj_norm.replace(" ", "") in _GENERIC_OBJECTS:
        return False
    q_compact = _normalize(query or sentence).replace(" ", "")
    # 그림 대상(의 낱말 하나라도)이 질의에 나오면 일치.
    if any(tok in q_compact for tok in obj_norm.split()):
        return False
    # 반대로 문장의 대상(또는 동의어)이 그림 라벨·검색어에 나와도 일치로 본다
    # (박스↔상자처럼 frame.object와 문장이 다른 이름을 쓰는 경우).
    hay = (asset.get("_norm", "") + asset.get("_kw_norm", "")).replace(" ", "")
    for o in q_objects:
        if any(v in hay for v in _object_variants(_stem_token(o))):
            return False
    return True


@lru_cache(maxsize=1)
def _assets_by_id() -> dict[str, dict]:
    return {a["id"]: a for a in load_assets()}


def _same_action(asset_id_a: str, asset_id_b: str) -> bool:
    """두 자산이 완전히 같은 동작(동사·대상·세부·도구·장소 전부 일치)을 가리키는가.

    LLM 인덱스의 frame이 그 정도로 세밀하게 겹치는 자산 쌍은 거의 항상 같은 그림을
    다른 번호로 중복 등록한 것이다(예: SERVING_020/021 "빈 접시(들)를 쟁반에 담는다").
    """
    index = load_index()
    fa = (index.get(asset_id_a) or {}).get("frame") or {}
    fb = (index.get(asset_id_b) or {}).get("frame") or {}
    if not fa.get("verb") or not fb.get("verb"):
        return False
    keys = ("verb", "object", "object_detail", "instrument", "location")
    return all(fa.get(k) == fb.get(k) for k in keys)


def _same_picture(a: dict, b: dict) -> bool:
    """두 검색 결과가 사용자에게 사실상 같은 카드인가 — 여유 판정에서 한 묶음으로 본다.

    - 같은 직무: frame 5칸이 전부 같으면 같은 동작(_same_action). 같은 직무 안에서는
      캐릭터·배경이 같아 frame 일치만으로 충분하다(기존 규칙 유지).
    - 다른 직무(옵션, AAC_MATCH_CROSS_JOB_TWINS=on일 때만): 라벨 문자열까지 같고 frame도
      같아야 한다. frame만 같은 경우(‘바닥을 밀대로 닦는다’ vs ‘밀대로 바닥을 닦는다’)는 묶지
      않는다. 라벨까지 같은 쌍(‘안전화를 신는다’ ASSEMBLY_AUX_011/DELIVERY_038, 사물 카드
      ‘앞치마’)은 같은 동작을 직무 폴더마다 다시 그린 것이다. 사물 카드는 동사가 없어
      _same_action이 거짓이므로 frame 비교를 직접 한다.

    다른 직무 묶음을 기본으로 켜지 않는 이유: 2026-09-22 사용자 결정(eval/README.md "쌍둥이 자산
    여유 면제 시도 → 되돌림") — 직무가 다르면 그림 속 캐릭터의 복장·배경이 달라, 발달장애
    근로자에게는 그 시각적 일치가 텍스트 의미보다 중요할 수 있다. 라벨까지 같아도 그림 파일은
    직무마다 따로 그려져 이 우려는 그대로다. P5 네 측정에서도 켜고 끈 결과가 한 건도 다르지 않아
    (해당 쌍이 1·2위로 붙은 케이스가 없다) 기본값을 바꿀 근거가 없다. 실사용자 확인 뒤에 켠다.
    """
    id_a, id_b = a.get("asset_id"), b.get("asset_id")
    if not id_a or not id_b:
        return False
    if a.get("job") == b.get("job"):
        return _same_action(id_a, id_b)
    if os.getenv("AAC_MATCH_CROSS_JOB_TWINS", "off").strip().lower() not in ("1", "on", "true"):
        return False
    label_a, label_b = a.get("label"), b.get("label")
    if not label_a or label_a != label_b:
        return False
    index = load_index()
    fa = (index.get(id_a) or {}).get("frame")
    fb = (index.get(id_b) or {}).get("frame")
    if fa is None or fb is None:
        return False
    keys = ("verb", "object", "object_detail", "instrument", "location")
    return all(fa.get(k) == fb.get(k) for k in keys)


_MARGIN_MODES = ("absolute", "relative")


def _margin_settings(embedding: bool) -> tuple[float, float, str, float]:
    """(임계값, 절대 여유, 여유 방식, 상대 여유) — 임베딩 유무에 따라 다른 env 묶음을 읽는다.

    여유 방식(AAC_[EMBED_]MATCH_MARGIN_MODE):
      absolute(기본) — s1−s2 ≥ MIN_MARGIN
      relative       — (s1−s2)/s1 ≥ MIN_REL_MARGIN
    상대 여유는 점수 척도가 바뀌어도(임베딩 가산, 규칙 가중치 변경) 같은 값을 쓸 수 있게 하려는
    옵션이다. P5 스윕(골든·개발 × full·sentence, 임베딩 off)에서는 절대 여유보다 나은 운영점이
    없어 기본은 absolute로 둔다. 알 수 없는 값은 요청을 실패시키지 않고 absolute로 본다.
    """
    prefix = "AAC_EMBED_MATCH_" if embedding else "AAC_MATCH_"
    if embedding:
        _, _, thr_default, margin_default = _embed_defaults()
        threshold = _env_float(prefix + "THRESHOLD", thr_default)
        min_margin = _env_float(prefix + "MIN_MARGIN", margin_default)
    else:
        threshold = float(os.getenv(prefix + "THRESHOLD", "0.215"))
        min_margin = float(os.getenv(prefix + "MIN_MARGIN", "0.018"))
    mode = os.getenv(prefix + "MARGIN_MODE", "absolute").strip().lower()
    if mode not in _MARGIN_MODES:
        mode = "absolute"
    min_rel = float(os.getenv(prefix + "MIN_REL_MARGIN", "0.06"))
    return threshold, min_margin, mode, min_rel


def decide(results: list[dict], embedding: bool = False, *,
           sentence: str | None = None, query: str | None = None) -> dict:
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
    점수 척도가 바뀌므로 반드시 다시 교정해야 한다. P5(P2·P3 게이트·동사 원형 뒤)에서
    임베딩 없는 경로를 0.22/0.02 → 0.215/0.018로 다시 골랐다 — 네 측정(골든·개발 × full·sentence)
    모두 오답 채택이 늘지 않는 구간(임계값 0.2125~0.22 × 여유 0.018~0.02) 안쪽에서 정답 넘김이
    가장 적은 점이다. 여유 0.017 이하·임계값 0.21 이하는 오답 채택이 바로 늘어 그 바깥은 피했다.

    임계값은 두 벌이다. 임베딩 가산 항이 붙으면 점수 척도가 올라가므로(정답은 더 높게,
    오답도 조금 높게) 같은 임계값을 쓰면 안 된다 — 임베딩을 쓴 검색은 AAC_EMBED_MATCH_*
    (제공자별 기본값 — local 0.24 / 0.015, openai 0.35 / 0.02), 못 쓴 검색(꺼짐·파일 낡음·실패)은
    AAC_MATCH_*(0.215 / 0.018)로 판정한다.

    여유는 "2위"가 아니라 "1위와 같은 그림 묶음(_same_picture) 밖의 첫 후보"와 잰다. 쌍둥이
    그림끼리는 어느 쪽이 나와도 맞으므로 서로 여유를 깎으면 안 되고, 반대로 쌍둥이를 건너뛴
    뒤의 경쟁자가 바짝 붙어 있으면 여전히 고를 수 없다(예전 규칙은 2위가 쌍둥이면 3위를 안 봤다).
    여유 값은 독립 블라인드 스윕으로 0.04→0.02로 낮췄다 — 정밀도는 거의 그대로인데
    자동 채택이 크게 늘었다. 자세한 표는 eval/README.md.

    반환: {"match": dict|None, "reason": str, "candidates": list, "margin": float,
           "embedding": bool}
      reason — "accepted" | "no_candidate" | "low_score" | "low_margin" | "frame_mismatch"
      margin — 묶음 밖 첫 경쟁자와의 절대 점수 차(경쟁자가 없으면 1위 점수)

    sentence/query를 주면 마지막에 대상 일치 게이트를 건다: 채택될 1순위 그림의 대상이
    문장의 대상과 분명히 다르면 frame_mismatch로 채택을 보류한다(후보는 그대로 준다).
    """
    threshold, min_margin, margin_mode, min_rel_margin = _margin_settings(embedding)

    if not results:
        return {"match": None, "reason": "no_candidate", "candidates": [], "margin": 0.0,
                "embedding": embedding}

    best = results[0]
    # 1위와 같은 그림 묶음은 건너뛰고 첫 경쟁자를 찾는다. 경쟁자가 없으면(후보 하나, 또는
    # 나머지가 전부 쌍둥이) 비교 대상이 없으므로 여유는 최대로 본다.
    rival = next((r for r in results[1:] if not _same_picture(best, r)), None)
    margin = best["score"] - rival["score"] if rival is not None else best["score"]

    if best["score"] < threshold:
        return {"match": None, "reason": "low_score", "candidates": results, "margin": margin,
                "embedding": embedding}
    if margin_mode == "relative":
        # best["score"] ≥ threshold > 0 이 아닐 수도 있다(임계값 0 설정) — 0으로 나누지 않는다.
        enough = rival is None or (best["score"] > 0
                                   and margin / best["score"] >= min_rel_margin)
    else:
        enough = margin >= min_margin
    if not enough:
        return {"match": None, "reason": "low_margin", "candidates": results, "margin": margin,
                "embedding": embedding}
    if sentence:
        asset = _assets_by_id().get(best["asset_id"])
        if asset is not None and _object_conflict(asset, sentence, query or sentence):
            return {"match": None, "reason": "frame_mismatch", "candidates": results,
                    "margin": margin, "embedding": embedding}
    return {"match": best, "reason": "accepted", "candidates": results, "margin": margin,
            "embedding": embedding}


def search_for_step(keywords: list[str], context: dict | None = None) -> dict | None:
    """단계에 붙일 AAC 자산을 고른다. 확신이 없으면 None(폴백)."""
    return search_for_step_detailed(keywords, context)["match"]


def step_query(keywords: list[str], context: dict | None = None) -> str:
    """단계 검색 질의 문자열(문장 + 키워드). 평가 하네스가 같은 질의를 재현·캐시하려고 따로 뺐다."""
    sentence = str((context or {}).get("sentence") or "").strip()
    query_parts = [sentence] + [str(k).strip() for k in keywords if str(k).strip()]
    return " ".join(part for part in query_parts if part)


def search_for_step_detailed(keywords: list[str], context: dict | None = None,
                             limit: int = 5) -> dict:
    """search_for_step에 판정 근거를 더한 형태. decide()의 반환을 그대로 준다.

    limit은 candidates 길이만 바꾼다(decide는 1·2위만 본다). 평가 하네스가 recall@20을 재려고
    같은 검색 한 번으로 더 긴 후보 목록을 받을 때 쓴다 — 순위용·판정용 검색을 따로 돌리면
    두 결과가 어긋날 수 있고 두 배 느리다.
    """
    ctx = dict(context or {})
    query = step_query(keywords, ctx)
    results, used_embedding = _search(query, ctx, limit=limit)
    sentence = str(ctx.get("sentence") or "").strip()
    return decide(results, embedding=used_embedding, sentence=sentence, query=query)
