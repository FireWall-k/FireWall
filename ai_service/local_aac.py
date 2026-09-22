from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path

import embeddings

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")

_JOB_ALIASES: dict[str, tuple[str, ...]] = {
    "assembly": ("assembly", "조립", "제조", "부품", "생산"),
    "cafe": ("cafe", "카페", "커피", "음료", "바리스타"),
    "cleaning": ("cleaning", "청소", "세탁", "세차", "환경미화"),
    "packaging": ("packaging", "포장", "패킹", "박스포장"),
    "retail": ("retail", "마트", "매장", "소매", "피킹", "계산"),
    "display": ("display", "진열", "매대", "선반"),
    "delivery": ("delivery", "배송", "택배", "화물"),
    "gas": ("gas", "주유", "주유소"),
    "serving": ("serving", "서빙", "식당", "레스토랑", "홀서빙"),
}

# 여러 직무에 두루 쓰이는 말은 절반만 센다. "매장 상품 진열"이 마트(매장) 1점, 진열 1점으로
# 동점이 되어 이름순으로 마트가 되던 문제 — 진열 그림 74장이 있는데도 마트로만 잡혔다.
_ALIAS_WEIGHT = {"매장": 0.5}

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
    # 무관한 자산(상품 정리)에 밀렸다. CAFE_078의 검색어 '정리하다'가 '정리하'로만
    # 남아 질의의 '정리'와 안 만난 게 원인이었다.
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


# 어간 끝 모음이 어미와 만나 줄어드는 형태. '세우-'+'어' → '세워', '하-'+'여' → '해'.
_STEM_CONTRACTIONS = {"우": "워", "오": "와", "이": "여", "하": "해", "리": "려", "기": "겨"}

_HANGUL_BASE = 0xAC00
_HANGUL_LAST = 0xD7A3
_RIEUL_FINAL_INDEX = 8  # 종성 28개 중 ㄹ의 순번(없음=0, ㄱ=1, ... ㄹ=8)


def _drop_rieul_final(char: str) -> str | None:
    """받침 ㄹ을 뗀 글자를 돌려준다. ㄹ받침이 아니면 None.

    ㄹ받침 어간(열다/만들다/쓸다/갈다 등)은 '-세요/-ㅂ니다/-는' 앞에서 받침이
    탈락한다: 열다→여세요, 만들다→만드세요, 쓸다→쓰세요, 갈다→가세요.
    이 규칙이 없으면 "창문을 여세요"에서 '열다'를 못 알아낸다 — 인덱스에 실제로
    있는 동사(열다·쓸다·만들다·갈다·밀다·들다 등 10여 개)가 전부 활용형 인식에서
    빠져 있었다.
    """
    if len(char) != 1:
        return None
    code = ord(char)
    if not (_HANGUL_BASE <= code <= _HANGUL_LAST):
        return None
    if (code - _HANGUL_BASE) % 28 != _RIEUL_FINAL_INDEX:
        return None
    return chr(code - _RIEUL_FINAL_INDEX)


def _stem_variants(stem: str) -> tuple[str, ...]:
    """어간의 표면형 후보. 활용형에서 어간을 찾아내기 위한 것이다."""
    if not stem:
        return ()
    variants = [stem]
    contracted = _STEM_CONTRACTIONS.get(stem[-1])
    if contracted:
        variants.append(stem[:-1] + contracted)
    dropped = _drop_rieul_final(stem[-1])
    if dropped:
        variants.append(stem[:-1] + dropped)
    return tuple(variants)


# ㄹ탈락으로 만든 표면형이 한 글자가 되면서, 훨씬 흔한 다른 동사의 원형과 우연히
# 같은 글자가 되는 경우가 있다. '갈다'(갈아주세요로 이미 원래 어간 '갈'이 잡힌다)의
# 탈락형 '가'가 대표적 — 이동을 뜻하는 '가다'의 원형과 같은 글자라, "고객님 댁에
# 가세요"·"창고에 가세요" 같은 문장에서 커피 원두를 "간다"는 엉뚱한 동사로 잡혔다
# (실사용 중 블라인드 테스트 2026-09-16에서 발견). '갈다'의 실제 존댓말 요청형은
# 거의 항상 모음축약형 '갈아(주세요)'라 기본 어간 '갈'만으로 충분히 잡힌다 —
# 탈락형 '가'는 실익 없이 충돌만 만들어 제외한다.
_RIEUL_DROP_EXCLUDE_LEMMAS = frozenset({"갈다"})


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
            if surface != stem and lemma in _RIEUL_DROP_EXCLUDE_LEMMAS:
                continue  # ㄹ탈락형만 제외 — 기본 어간(예: '갈')은 그대로 둔다.
            pairs.add((surface, lemma))
    # 긴 어간 우선 — '준비하'가 '준'보다 먼저 걸려야 한다. 길이가 같으면(예: 표면형
    # '쓰'가 '쓰다'·'쓸다' 둘 다에서 나옴) 원형 문자열로 2차 정렬해 결과가 매 실행마다
    # 바뀌지 않게 한다 — set 순서(해시 시드)에 맡기면 서버를 재시작할 때마다 어느
    # 원형이 이기는지 달라질 수 있다.
    return tuple(sorted(pairs, key=lambda p: (-len(p[0]), p[1])))


def _verb_lemmas(text: str) -> set[str]:
    """활용형 문장에서 동사 원형을 뽑는다.

    "원두를 갈아주세요" → {'갈다'}. 자산 쪽 검색어는 원형('갈다')이라 이 변환이 없으면
    질의 토큰('갈아주')과 영영 만나지 못한다 — 인덱스를 만들어도 아무 효과가 없다.

    한 표면형이 서로 다른 원형에 동시에 걸리는 경우가 있다("쓰"는 '쓰다'(사용/착용)
    와 '쓸다'(쓸기) 둘 다에서 나온다 — "쓰세요"는 한국어 자체가 중의적이다). 예전엔
    가장 긴 어간을 찾으면 그중 하나만(먼저 만난 것) 채택했는데, 어느 쪽이 이기는지가
    내부 정렬 순서에 좌우돼 한쪽을 고치면 다른 쪽이 깨졌다. 대신 같은 길이로 묶인
    원형을 전부 후보로 남긴다 — 최종 판단(직무·명사 겹침)은 이미 `_score_asset`이
    한다: 문맥과 맞는 자산만 가산점의 이득을 본다.
    """
    found: set[str] = set()
    for word in _TOKEN_RE.findall(text):
        best_len: int | None = None
        for surface, lemma in _verb_stem_map():
            # 어간만 덜렁 있는 게 아니라 뒤에 어미가 붙어 있어야 동사로 본다.
            if len(word) <= len(surface) or not word.startswith(surface):
                continue
            # 한 글자 어간('갈','개')은 아무 단어에나 걸리기 쉽다. 어미가 두 글자 이상
            # 붙어 있을 때만 인정한다('갈아주세요'는 통과, '갈색'은 탈락).
            if len(surface) == 1 and len(word) < 3:
                continue
            if best_len is not None and len(surface) < best_len:
                break  # 더 짧은 어간은(정렬상 이제부터 전부) 무시 — 가장 긴 것만 본다.
            best_len = len(surface)
            found.add(lemma)
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
        str(ctx.get(key, "")) for key in ("business_type", "work_environment", "job")
    ) + " " + query
    # 업종을 안 넣으면 단계 문장 하나로는 직무를 못 알아낼 때가 많다("큰 나사를
    # 나누세요"만 봐서는 조립인지 알 수 없다). 원문 전체("부품 상자에서 나사를...")에는
    # 대개 직무를 알려주는 단어가 있으므로 보조 신호로 함께 본다. 업종이 이미 있으면
    # 그쪽이 개수를 더 많이 쌓아 여전히 우선하므로, 있어도 해가 되지 않는다.
    if ctx.get("raw_input"):
        haystack += " " + str(ctx["raw_input"])
    norm = _normalize(haystack)
    scores: list[tuple[float, str]] = []
    for job, aliases in _JOB_ALIASES.items():
        count = sum(_ALIAS_WEIGHT.get(alias, 1.0) for alias in aliases if alias.lower() in norm)
        if count:
            scores.append((count, job))
    return max(scores)[1] if scores else None


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
    """질의를 한 번만 분석해 자산 401개에 재사용한다.

    예전에는 자산마다 형태소 추출을 다시 해서 질의 하나에 401번 돌았다.
    """

    __slots__ = ("norm", "tokens", "bigrams", "lemmas", "tools")

    def __init__(self, query: str) -> None:
        self.norm = _normalize(query)
        self.lemmas = _verb_lemmas(query)
        # 질의에 도구 이름이 있으면 동의어까지 넓혀 둔다("대걸레" -> {"대걸레","밀대"}).
        self.tools = _expand_tools(_tokens(query) & set(_TOOL_SYNONYM_MAP))
        # 활용형에서 뽑은 원형을 토큰에 더한다. 자산 검색어는 원형이라 이게 없으면
        # "갈아주세요"와 "갈다"가 만나지 못한다.
        self.tokens = _tokens(query) | self.lemmas | self.tools
        self.bigrams = _bigrams(query)


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


# 실사용 중 발견: "남은 재료를 꺼내세요"(냉장고에서 빼기)가 "남은 재료를 냉장고에
# 넣는다"(CAFE_088)로 붙었다. 원인은 verb_class가 방향을 구분 못 하는 것 —
# '넣다'/'꺼내다'는 둘 다 verb_class="move"라 _verb_class_penalty가 안 걸린다.
# 동사 원형 매칭(_verb_lemmas)도 일치할 때만 가산할 뿐 불일치를 벌점 주지 않으므로,
# "꺼내다 냉장고" 같은 자산이 아예 없는 도메인에서는 유일한 후보(CAFE_088)가 방향이
# 반대인데도 자신 있게 채택된다(골든셋의 gap_fridge_out과 같은 결함).
#
# object_detail/specificity 감점(cd3972e, 이 파일 아래)처럼 '흔한 신호의 부재'로
# 깎으면 회귀한다는 걸 이미 세 번 확인했다. 그래서 여기서는 넓게 깎지 않고, 명확히
# 반대말인 동사 쌍만 좁게 골라 벌점을 준다 — _TOOL_SYNONYMS와 같은 폐쇄형 목록 패턴.
_VERB_ANTONYMS: tuple[frozenset[str], ...] = (
    frozenset({"넣다", "꺼내다"}),
    frozenset({"열다", "닫다"}),
    frozenset({"붙이다", "떼다"}),
    frozenset({"켜다", "끄다"}),
    frozenset({"올리다", "내리다"}),
    frozenset({"채우다", "비우다"}),
)

# 실측: 0.4 미만은 정답 쌍 중 진짜 반의어가 아닌데 우연히 걸린 경우까지 과하게
# 깎아 top1을 깎아 먹었다. 0.4~0.6 구간에서 골든셋 회귀 없이 gap_fridge_out이
# 정상 거절로 바뀌어 0.4로 잡았다(도구 게이트 0.55보다 약간 세게 — 방향이 아예
# 반대인 건 도구/사물 혼동보다 더 확실히 틀렸다고 보기 때문).
_VERB_ANTONYM_PENALTY = 0.4


def _verb_antonym_penalty(asset: dict, query_lemmas: set[str]) -> float:
    """질의 동사가 자산 동사의 명확한 반대말이면 깎는다(곱한다).

    동의어(_TOOL_SYNONYMS)와 정반대 성격이라 별도 목록으로 둔다 — 겹치는 단어가
    아니라 반대 방향의 동작이라는 게 확실할 때만 걸리는 좁은 목록이다.
    """
    asset_lemmas = asset.get("_lemmas", set())
    if not query_lemmas or not asset_lemmas:
        return 1.0
    for group in _VERB_ANTONYMS:
        q_hit = query_lemmas & group
        a_hit = asset_lemmas & group
        if q_hit and a_hit and q_hit != a_hit:
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
# 가산만 한다 — 유사도가 낮다고 깎지 않는다("흔한 신호 부재를 감점하는" 방식은 세 번 회귀했다).
# 기준 0.4 아래의 유사도는 잡음이라 0으로 본다. w·기준·임계값(_EMBED_* 아래 decide)은
# 블라인드 세트 A/B/C 스윕으로 정했다(독립 검증 249단계에서 오답 채택 19건→9건, 악화 0건).
_EMBED_WEIGHT = float(os.getenv("AAC_EMBED_WEIGHT", "0.5"))
_EMBED_BASE = float(os.getenv("AAC_EMBED_BASE", "0.4"))


def _score_asset(asset: dict, qf: _QueryFeatures, preferred_job: str | None,
                 action_type: str | None, is_instruction: bool = False,
                 emb_sim: float | None = None) -> float:
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
        score = min(1.0, score + _EMBED_WEIGHT * max(0.0, emb_sim - _EMBED_BASE))
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
    """(결과, 임베딩을 썼는가). 채택 임계값이 임베딩 유무에 따라 달라서 함께 돌려준다."""
    ctx = context or {}
    preferred_job = infer_job(ctx, query)
    action_type = str(ctx.get("action_type") or "") or None
    # 단계 문장이 있으면 그것으로 판단한다. query에는 symbol_query가 섞여 있어
    # 문장 형태가 흐려지기 때문이다.
    is_instruction = _is_instruction(str(ctx.get("sentence") or query))
    qf = _QueryFeatures(query)  # 질의 분석은 한 번만 — 자산마다 다시 하면 401번 돈다.
    # 못 쓰면(키·파일 없음, 호출 실패) None — 그러면 임베딩 없는 기존 점수로 그대로 진행한다.
    sims = embeddings.query_similarities(query)

    ranked: list[tuple[float, dict]] = []
    for asset in load_assets():
        emb_sim = sims.get(asset["id"]) if sims is not None else None
        score = _score_asset(asset, qf, preferred_job, action_type, is_instruction, emb_sim)
        if score <= 0:
            continue
        ranked.append((score, asset))
    ranked.sort(key=lambda item: (-item[0], item[1].get("id", "")))

    results: list[dict] = []
    for score, asset in _dedupe(ranked)[: max(1, limit)]:
        results.append({
            "asset_id": asset["id"],
            "group_id": asset.get("group_id") or asset["id"],
            "job": asset.get("job", ""),
            "asset_type": asset.get("asset_type", "action"),
            "label": asset.get("label", ""),
            "image_url": f"/api/aac/images/{asset['image']}",
            "score": round(score, 4),
        })
    return results, sims is not None


def _same_action(asset_id_a: str, asset_id_b: str) -> bool:
    """두 자산이 완전히 같은 동작(동사·대상·세부·도구·장소 전부 일치)을 가리키는가.

    LLM 인덱스의 frame이 그 정도로 세밀하게 겹치는 자산 쌍은 거의 항상 같은 그림을
    다른 번호로 중복 등록한 것이다(예: DELIVERY_022/041 둘 다 "초인종을 누른다").
    """
    index = load_index()
    fa = (index.get(asset_id_a) or {}).get("frame") or {}
    fb = (index.get(asset_id_b) or {}).get("frame") or {}
    if not fa.get("verb") or not fb.get("verb"):
        return False
    keys = ("verb", "object", "object_detail", "instrument", "location")
    return all(fa.get(k) == fb.get(k) for k in keys)


def decide(results: list[dict], embedding: bool = False) -> dict:
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

    임계값은 두 벌이다. 임베딩 가산 항이 붙으면 점수 척도가 올라가므로(정답은 더 높게,
    오답도 조금 높게) 같은 임계값을 쓰면 안 된다 — 임베딩을 쓴 검색은 AAC_EMBED_MATCH_*
    (0.35 / 0.02), 못 쓴 검색(키 없음·호출 실패)은 기존 AAC_MATCH_*(0.22 / 0.02)로 판정한다.
    여유 값은 393문장 독립 블라인드 스윕(2026-09-22)으로 0.04→0.02로 낮췄다 — 정밀도는
    거의 그대로인데(0.800→0.793) 자동 채택이 91→118건으로 늘었다. 자세한 표는 eval/README.md.
    장애로 임베딩이 빠졌는데 임베딩용 임계값(더 엄격)을 그대로 쓰면 전부 폴백되고,
    반대로 임베딩이 붙었는데 기존 임계값을 쓰면 오답 채택이 다시 늘어난다.

    반환: {"match": dict|None, "reason": str, "candidates": list, "margin": float,
           "embedding": bool}
      reason — "accepted" | "no_candidate" | "low_score" | "low_margin"
    """
    if embedding:
        threshold = float(os.getenv("AAC_EMBED_MATCH_THRESHOLD", "0.35"))
        min_margin = float(os.getenv("AAC_EMBED_MATCH_MIN_MARGIN", "0.02"))
    else:
        threshold = float(os.getenv("AAC_MATCH_THRESHOLD", "0.22"))
        min_margin = float(os.getenv("AAC_MATCH_MIN_MARGIN", "0.02"))

    if not results:
        return {"match": None, "reason": "no_candidate", "candidates": [], "margin": 0.0,
                "embedding": embedding}

    best = results[0]
    # 후보가 하나뿐이면 비교 대상이 없다. 경쟁자가 없으므로 여유는 최대로 본다.
    margin = best["score"] - results[1]["score"] if len(results) > 1 else best["score"]

    if best["score"] < threshold:
        return {"match": None, "reason": "low_score", "candidates": results, "margin": margin,
                "embedding": embedding}
    # 여유가 좁아도, 1·2위가 "같은 직무 안에서 같은 동작을 가리키는 쌍둥이 자산"이면
    # (예: DELIVERY_022/041 둘 다 "초인종을 누른다") 어느 쪽이 나와도 정답이라 위험 신호가
    # 아니다. 범위를 "같은 직무일 때만"으로 좁힌 이유는, 직무가 다르면 동작 텍스트는 같아도
    # 그림 속 캐릭터의 복장·배경이 달라 사용자에게 어느 쪽이 맞는지가 텍스트 의미보다 더
    # 중요할 수 있기 때문(2026-09-22, 사용자 지적으로 무직무 버전은 되돌리고 이렇게 좁혔다).
    is_twin = (len(results) > 1 and margin < min_margin
               and best.get("job") == results[1].get("job")
               and _same_action(best["asset_id"], results[1]["asset_id"]))
    if margin < min_margin and not is_twin:
        return {"match": None, "reason": "low_margin", "candidates": results, "margin": margin,
                "embedding": embedding}
    return {"match": best, "reason": "accepted", "candidates": results, "margin": margin,
            "embedding": embedding}


def search_for_step(keywords: list[str], context: dict | None = None) -> dict | None:
    """단계에 붙일 AAC 자산을 고른다. 확신이 없으면 None(폴백)."""
    return search_for_step_detailed(keywords, context)["match"]


def search_for_step_detailed(keywords: list[str], context: dict | None = None) -> dict:
    """search_for_step에 판정 근거를 더한 형태. decide()의 반환을 그대로 준다."""
    ctx = dict(context or {})
    sentence = str(ctx.get("sentence") or "").strip()
    query_parts = [sentence] + [str(k).strip() for k in keywords if str(k).strip()]
    query = " ".join(part for part in query_parts if part)
    results, used_embedding = _search(query, ctx, limit=5)
    return decide(results, embedding=used_embedding)
