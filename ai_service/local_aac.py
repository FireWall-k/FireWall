from __future__ import annotations

import json
import os
import re
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path


_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


# ---------------------------------------------------------------------
# Job aliases
# ---------------------------------------------------------------------

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
        "진열",
        "피킹",
        "계산",
        "배송",
    ),
}


# ---------------------------------------------------------------------
# Korean particles / endings
# ---------------------------------------------------------------------

_PARTICLES = (
    "으로",
    "에서",
    "에게",
    "까지",
    "부터",
    "처럼",
    "보다",
    "하고",
    "이며",
    "을",
    "를",
    "이",
    "가",
    "은",
    "는",
    "에",
    "의",
    "와",
    "과",
    "도",
    "만",
    "로",
)


# ---------------------------------------------------------------------
# Action normalization
#
# LLM action_type과 AAC metadata action의 표현 차이를 보정한다.
# ---------------------------------------------------------------------

_ACTION_TYPE_ALIASES: dict[str, str] = {
    "put": "place",
    "placement": "place",
    "놓기": "place",
    "배치": "place",
    "진열": "place",

    "insert": "put_in",
    "넣기": "put_in",
    "담기": "put_in",

    "확인": "check",
    "점검": "check",

    "운반": "carry",
    "가져가기": "carry",

    "이동": "move",
    "옮기기": "move",

    "청소": "clean",
    "닦기": "clean",

    "씻기": "wash",
    "세척": "wash",

    "분류": "sort",
    "나누기": "sort",

    "구분": "separate",
    "분리": "separate",

    "붙이기": "attach",
    "부착": "attach",

    "열기": "open",
    "닫기": "close",

    "접기": "fold",
    "펼치기": "unfold",

    "밀봉": "seal",

    "누르기": "press",

    "착용": "wear",

    "붓기": "pour",
    "따르기": "pour",

    "섞기": "mix",

    "보관": "store",
}


# 서로 완전히 동일한 action은 아니지만
# 어느 정도 의미적으로 가까운 action.
_ACTION_COMPATIBILITY: dict[frozenset[str], float] = {
    frozenset(("place", "put_in")): 0.45,
    frozenset(("check", "inspect")): 0.65,
    frozenset(("carry", "move")): 0.55,
    frozenset(("clean", "wash")): 0.40,
    frozenset(("collect", "pick_up")): 0.45,
    frozenset(("sort", "separate")): 0.60,
    frozenset(("attach", "fasten")): 0.65,
}


# ---------------------------------------------------------------------
# Specificity control
#
# 사용자가 말하지 않은 세부 조건을 가진 AAC가
# 일반적인 AAC보다 위로 올라오는 현상을 줄인다.
#
# 예:
#
# query:
#   제품을 진열대에 올려주세요
#
# 후보:
#   냉장 상품을 냉장 진열대에 놓는다
#
# 사용자가 "냉장"이라고 하지 않았으므로 감점.
# ---------------------------------------------------------------------

_SPECIFICITY_TERMS = (
    "냉장",
    "냉동",
    "상온",
    "새 상품",
    "오래된",
    "무거운",
    "가벼운",
    "파손",
    "불량",
    "정상",
    "잘못된",
    "배송",
    "주문",
)


# ---------------------------------------------------------------------
# Data path
# ---------------------------------------------------------------------

def _default_data_dir() -> Path:
    # ai_service/local_aac.py
    # -> repository root/data/aac
    return (
        Path(__file__).resolve().parent.parent
        / "data"
        / "aac"
    )


def get_data_dir() -> Path:
    return Path(
        os.getenv(
            "AAC_DATA_DIR",
            str(_default_data_dir()),
        )
    ).resolve()


# ---------------------------------------------------------------------
# Text normalization
# ---------------------------------------------------------------------

def _normalize(text: str) -> str:
    return " ".join(
        _TOKEN_RE.findall(
            str(text or "").lower()
        )
    )


def _stem_token(token: str) -> str:
    value = token

    for particle in _PARTICLES:
        if (
            len(value) > len(particle) + 1
            and value.endswith(particle)
        ):
            value = value[:-len(particle)]
            break

    for ending in (
        "해주세요",
        "하십시오",
        "하세요",
        "합니다",
        "한다",
        "해요",
        "세요",
        "니다",
        "다",
    ):
        if (
            len(value) > len(ending) + 1
            and value.endswith(ending)
        ):
            value = value[:-len(ending)]
            break

    return value


def _tokens(text: str) -> set[str]:
    result: set[str] = set()

    for token in _TOKEN_RE.findall(
        str(text or "").lower()
    ):
        stem = _stem_token(token)

        if len(stem) >= 2:
            result.add(stem)

    return result


def _bigrams(text: str) -> set[str]:
    compact = _normalize(text).replace(
        " ",
        "",
    )

    if len(compact) < 2:
        return (
            {compact}
            if compact
            else set()
        )

    return {
        compact[i:i + 2]
        for i in range(len(compact) - 1)
    }


def _jaccard(
    a: set[str],
    b: set[str],
) -> float:
    if not a or not b:
        return 0.0

    return len(a & b) / len(a | b)


# ---------------------------------------------------------------------
# Generic text similarity
# ---------------------------------------------------------------------

def _text_similarity(
    query_norm: str,
    query_tokens: set[str],
    query_bigrams: set[str],
    target_norm: str,
    target_tokens: set[str],
    target_bigrams: set[str],
) -> float:

    if (
        not query_norm
        or not target_norm
    ):
        return 0.0

    token_score = _jaccard(
        query_tokens,
        target_tokens,
    )

    bigram_score = _jaccard(
        query_bigrams,
        target_bigrams,
    )

    seq_score = SequenceMatcher(
        None,
        query_norm.replace(" ", ""),
        target_norm.replace(" ", ""),
    ).ratio()

    containment = 0.0

    if (
        target_norm in query_norm
        or query_norm in target_norm
    ):
        containment = 1.0

    elif (
        query_tokens
        and query_tokens <= target_tokens
    ):
        containment = 0.8

    return (
        0.38 * token_score
        + 0.34 * bigram_score
        + 0.20 * seq_score
        + 0.08 * containment
    )


# ---------------------------------------------------------------------
# Job normalization / inference
# ---------------------------------------------------------------------

def _canonical_job(
    value: str | None,
) -> str | None:

    if not value:
        return None

    norm = _normalize(
        str(value)
    )

    if not norm:
        return None

    if norm in _JOB_ALIASES:
        return norm

    for job, aliases in _JOB_ALIASES.items():
        for alias in aliases:
            if norm == _normalize(alias):
                return job

    return None


def infer_job(
    context: dict | None = None,
    query: str = "",
) -> str | None:

    ctx = context or {}

    haystack = " ".join(
        str(ctx.get(key, ""))
        for key in (
            "business_type",
            "work_environment",
            "job",
        )
    )

    haystack = (
        haystack
        + " "
        + str(query or "")
    )

    norm = _normalize(haystack)

    scores: list[
        tuple[int, str]
    ] = []

    for job, aliases in _JOB_ALIASES.items():
        count = sum(
            1
            for alias in aliases
            if alias.lower() in norm
        )

        if count:
            scores.append(
                (count, job)
            )

    return (
        max(scores)[1]
        if scores
        else None
    )


# ---------------------------------------------------------------------
# Action normalization
# ---------------------------------------------------------------------

def _canonical_action(
    value: str | None,
) -> str | None:

    if not value:
        return None

    action = (
        str(value)
        .strip()
        .lower()
        .replace("-", "_")
        .replace(" ", "_")
    )

    if not action:
        return None

    return _ACTION_TYPE_ALIASES.get(
        action,
        action,
    )


def _action_similarity(
    expected: str | None,
    actual: str | None,
) -> float:

    expected = _canonical_action(
        expected
    )

    actual = _canonical_action(
        actual
    )

    if (
        not expected
        or expected == "other"
    ):
        return 0.0

    if not actual:
        return 0.0

    if expected == actual:
        return 1.0

    return _ACTION_COMPATIBILITY.get(
        frozenset(
            (
                expected,
                actual,
            )
        ),
        0.0,
    )


# ---------------------------------------------------------------------
# Context keyword handling
# ---------------------------------------------------------------------

def _context_keywords(
    context: dict,
) -> list[str]:

    raw = (
        context.get("_step_keywords")
        or context.get("keywords")
        or []
    )

    if isinstance(raw, str):
        raw = [raw]

    if not isinstance(
        raw,
        (list, tuple, set),
    ):
        return []

    result: list[str] = []

    for value in raw:
        value = str(value).strip()

        if (
            value
            and value not in result
        ):
            result.append(value)

    return result


# ---------------------------------------------------------------------
# Specificity penalty
# ---------------------------------------------------------------------

def _specificity_penalty(
    asset: dict,
    query: str,
) -> float:

    query_norm = _normalize(
        query
    )

    asset_text = " ".join(
        [
            str(asset.get("label", "")),
            *[
                str(value)
                for value in asset.get(
                    "objects",
                    [],
                )
            ],
        ]
    )

    asset_norm = _normalize(
        asset_text
    )

    missing_terms: set[str] = set()

    for term in _SPECIFICITY_TERMS:
        term_norm = _normalize(
            term
        )

        if (
            term_norm
            and term_norm in asset_norm
            and term_norm not in query_norm
        ):
            missing_terms.add(
                term_norm
            )

    return min(
        0.12 * len(missing_terms),
        0.24,
    )


# ---------------------------------------------------------------------
# Asset loading / precomputation
# ---------------------------------------------------------------------

@lru_cache(maxsize=1)
def load_assets() -> list[dict]:

    path = (
        get_data_dir()
        / "aac_assets.json"
    )

    payload = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    assets = payload.get(
        "assets",
        [],
    )

    for asset in assets:
        label = str(
            asset.get(
                "label",
                "",
            )
        )

        keywords = [
            str(value)
            for value in asset.get(
                "keywords",
                [],
            )
            if str(value).strip()
        ]

        aliases = [
            str(value)
            for value in asset.get(
                "aliases",
                [],
            )
            if str(value).strip()
        ]

        objects = [
            str(value)
            for value in asset.get(
                "objects",
                [],
            )
            if str(value).strip()
        ]

        action = str(
            asset.get(
                "action",
                "",
            )
        )

        search_text = str(
            asset.get(
                "search_text",
                "",
            )
        )

        # -----------------------------------------------------
        # Label
        # -----------------------------------------------------

        asset["_label_norm"] = (
            _normalize(label)
        )

        asset["_label_tokens"] = (
            _tokens(label)
        )

        asset["_label_bigrams"] = (
            _bigrams(label)
        )

        # -----------------------------------------------------
        # Keywords
        # -----------------------------------------------------

        keyword_text = " ".join(
            keywords
        )

        asset["_keyword_norm"] = (
            _normalize(
                keyword_text
            )
        )

        asset["_keyword_tokens"] = (
            _tokens(
                keyword_text
            )
        )

        # -----------------------------------------------------
        # Aliases
        # -----------------------------------------------------

        alias_entries: list[
            tuple[
                str,
                set[str],
                set[str],
            ]
        ] = []

        for alias in aliases:
            alias_entries.append(
                (
                    _normalize(alias),
                    _tokens(alias),
                    _bigrams(alias),
                )
            )

        asset["_alias_entries"] = (
            alias_entries
        )

        # -----------------------------------------------------
        # Objects
        # -----------------------------------------------------

        object_entries: list[
            tuple[
                str,
                set[str],
            ]
        ] = []

        for obj in objects:
            object_entries.append(
                (
                    _normalize(obj),
                    _tokens(obj),
                )
            )

        asset["_object_entries"] = (
            object_entries
        )

        # -----------------------------------------------------
        # Action
        # -----------------------------------------------------

        asset["_action"] = (
            _canonical_action(
                action
            )
        )

        # -----------------------------------------------------
        # Full metadata search text
        # -----------------------------------------------------

        if not search_text:
            search_text = " ".join(
                [
                    label,
                    action,
                    *objects,
                    *keywords,
                    *aliases,
                ]
            )

        asset["_search_norm"] = (
            _normalize(
                search_text
            )
        )

        asset["_search_tokens"] = (
            _tokens(
                search_text
            )
        )

        asset["_search_bigrams"] = (
            _bigrams(
                search_text
            )
        )

    return assets


# ---------------------------------------------------------------------
# Metadata scoring
# ---------------------------------------------------------------------

def _keyword_score(
    query_tokens: set[str],
    asset: dict,
) -> float:

    asset_tokens: set[str] = (
        asset.get(
            "_keyword_tokens",
            set(),
        )
    )

    if (
        not query_tokens
        or not asset_tokens
    ):
        return 0.0

    matched = (
        query_tokens
        & asset_tokens
    )

    return (
        len(matched)
        / len(query_tokens)
    )


def _object_score(
    query_norm: str,
    query_tokens: set[str],
    asset: dict,
) -> float:

    object_entries = asset.get(
        "_object_entries",
        [],
    )

    if not object_entries:
        return 0.0

    scores: list[float] = []

    for (
        object_norm,
        object_tokens,
    ) in object_entries:

        if not object_norm:
            continue

        # 객체 문구가 query에 그대로 존재
        if object_norm in query_norm:
            scores.append(1.0)
            continue

        # 객체 token 전체가 query에 존재
        if (
            object_tokens
            and object_tokens <= query_tokens
        ):
            scores.append(1.0)
            continue

        # 부분 일치
        scores.append(
            _jaccard(
                query_tokens,
                object_tokens,
            )
        )

    if not scores:
        return 0.0

    return (
        sum(scores)
        / len(scores)
    )


def _best_alias_score(
    query_norm: str,
    query_tokens: set[str],
    query_bigrams: set[str],
    asset: dict,
) -> float:

    aliases = asset.get(
        "_alias_entries",
        [],
    )

    if not aliases:
        return 0.0

    best = 0.0

    for (
        alias_norm,
        alias_tokens,
        alias_bigrams,
    ) in aliases:

        score = _text_similarity(
            query_norm,
            query_tokens,
            query_bigrams,
            alias_norm,
            alias_tokens,
            alias_bigrams,
        )

        best = max(
            best,
            score,
        )

    return best


# ---------------------------------------------------------------------
# Final ranking score
# ---------------------------------------------------------------------

def _score_asset(
    asset: dict,
    query: str,
    preferred_job: str | None,
    action_type: str | None,
    step_keywords: list[str],
) -> float:

    primary_query = str(
        query or ""
    ).strip()

    if not primary_query:
        return 0.0

    # ---------------------------------------------------------
    # Main query
    # ---------------------------------------------------------

    q_norm = _normalize(
        primary_query
    )

    q_tokens = _tokens(
        primary_query
    )

    q_bigrams = _bigrams(
        primary_query
    )

    # ---------------------------------------------------------
    # Metadata query
    #
    # sentence + LLM keywords
    # ---------------------------------------------------------

    signal_query = " ".join(
        [
            primary_query,
            *step_keywords,
        ]
    ).strip()

    signal_norm = _normalize(
        signal_query
    )

    signal_tokens = _tokens(
        signal_query
    )

    signal_bigrams = _bigrams(
        signal_query
    )

    # ---------------------------------------------------------
    # 1. Label similarity
    # ---------------------------------------------------------

    label_score = _text_similarity(
        q_norm,
        q_tokens,
        q_bigrams,
        asset["_label_norm"],
        asset["_label_tokens"],
        asset["_label_bigrams"],
    )

    # ---------------------------------------------------------
    # 2. Alias similarity
    # ---------------------------------------------------------

    alias_score = _best_alias_score(
        q_norm,
        q_tokens,
        q_bigrams,
        asset,
    )

    # ---------------------------------------------------------
    # 3. Keyword match
    # ---------------------------------------------------------

    keyword_score = _keyword_score(
        signal_tokens,
        asset,
    )

    # ---------------------------------------------------------
    # 4. Object match
    # ---------------------------------------------------------

    object_score = _object_score(
        signal_norm,
        signal_tokens,
        asset,
    )

    # ---------------------------------------------------------
    # 5. Full search_text similarity
    # ---------------------------------------------------------

    search_text_score = (
        _text_similarity(
            signal_norm,
            signal_tokens,
            signal_bigrams,
            asset["_search_norm"],
            asset["_search_tokens"],
            asset["_search_bigrams"],
        )
    )

    # ---------------------------------------------------------
    # Base score
    # ---------------------------------------------------------

    score = (
        0.44 * label_score
        + 0.12 * alias_score
        + 0.14 * keyword_score
        + 0.12 * object_score
        + 0.08 * search_text_score
    )

    # ---------------------------------------------------------
    # 6. Job context bonus / penalty
    #
    # explicit job은 search_assets에서 hard filter 처리.
    # infer된 job에는 soft bonus 적용.
    # ---------------------------------------------------------

    if preferred_job:
        if (
            asset.get("job")
            == preferred_job
        ):
            score += 0.07
        else:
            score -= 0.04

    # ---------------------------------------------------------
    # 7. Action metadata
    # ---------------------------------------------------------

    canonical_expected_action = (
        _canonical_action(
            action_type
        )
    )

    action_score = (
        _action_similarity(
            canonical_expected_action,
            asset.get("_action"),
        )
    )

    if (
        canonical_expected_action
        and canonical_expected_action
        != "other"
    ):
        if action_score > 0:
            score += (
                0.08
                * action_score
            )
        else:
            score -= 0.025

    # ---------------------------------------------------------
    # 8. 실제 작업이면 action card 우선
    # ---------------------------------------------------------

    if (
        canonical_expected_action
        and canonical_expected_action
        != "other"
    ):
        if (
            asset.get("asset_type")
            == "action"
        ):
            score += 0.03
        else:
            score -= 0.03

    # ---------------------------------------------------------
    # 9. Unsupported specificity penalty
    #
    # query에는 없는 냉장/냉동/배송/주문 등의
    # 세부 조건이 candidate에만 있으면 감점.
    # ---------------------------------------------------------

    score -= _specificity_penalty(
        asset,
        primary_query,
    )

    return max(
        0.0,
        min(
            score,
            1.0,
        ),
    )


# ---------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------

def search_assets(
    query: str,
    context: dict | None = None,
    limit: int = 5,
) -> list[dict]:

    ctx = dict(
        context or {}
    )

    step_keywords = (
        _context_keywords(
            ctx
        )
    )

    job_query = " ".join(
        [
            str(query or ""),
            *step_keywords,
        ]
    )

    # ---------------------------------------------------------
    # Explicit job
    #
    # context에 job이 직접 들어왔다면
    # 해당 job만 검색한다.
    #
    # 예:
    # {"job": "retail"}
    #
    # cafe/cleaning 등 다른 직무는 후보에서 제거.
    # ---------------------------------------------------------

    explicit_job = (
        _canonical_job(
            ctx.get("job")
        )
    )

    # 명시 job이 없을 때만 query/context에서 추론
    preferred_job = (
        explicit_job
        or infer_job(
            ctx,
            job_query,
        )
    )

    action_type = (
        str(
            ctx.get(
                "action_type",
                "",
            )
        ).strip()
        or None
    )

    ranked: list[
        tuple[
            float,
            dict,
        ]
    ] = []

    for asset in load_assets():

        # -----------------------------------------------------
        # Hard job filter
        # -----------------------------------------------------

        if (
            explicit_job
            and asset.get("job")
            != explicit_job
        ):
            continue

        score = _score_asset(
            asset,
            query,
            preferred_job,
            action_type,
            step_keywords,
        )

        if score <= 0:
            continue

        ranked.append(
            (
                score,
                asset,
            )
        )

    ranked.sort(
        key=lambda item: (
            -item[0],
            item[1].get(
                "id",
                "",
            ),
        )
    )

    # ---------------------------------------------------------
    # Group deduplication
    #
    # ASSEMBLY_031_01 ~ _04처럼
    # 같은 group의 variant가 Top-K를 독점하지 않도록
    # 기본적으로 group당 하나만 반환한다.
    #
    # 환경변수로 끌 수 있음:
    # AAC_DEDUP_GROUPS=0
    # ---------------------------------------------------------

    dedupe_groups = (
        os.getenv(
            "AAC_DEDUP_GROUPS",
            "1",
        ).strip().lower()
        not in {
            "0",
            "false",
            "no",
        }
    )

    selected: list[
        tuple[
            float,
            dict,
        ]
    ] = []

    seen_groups: set[str] = set()

    for score, asset in ranked:

        group_id = str(
            asset.get("group_id")
            or asset.get("id")
            or ""
        )

        if (
            dedupe_groups
            and group_id in seen_groups
        ):
            continue

        selected.append(
            (
                score,
                asset,
            )
        )

        if group_id:
            seen_groups.add(
                group_id
            )

        if len(selected) >= max(
            1,
            limit,
        ):
            break

    # ---------------------------------------------------------
    # API response
    # ---------------------------------------------------------

    results: list[dict] = []

    for score, asset in selected:

        results.append(
            {
                "asset_id": asset["id"],
                "group_id": (
                    asset.get("group_id")
                    or asset["id"]
                ),
                "job": asset.get(
                    "job",
                    "",
                ),
                "asset_type": asset.get(
                    "asset_type",
                    "action",
                ),
                "label": asset.get(
                    "label",
                    "",
                ),
                "image_url": (
                    "/api/aac/images/"
                    f"{asset['image']}"
                ),
                "score": round(
                    score,
                    4,
                ),
            }
        )

    return results


# ---------------------------------------------------------------------
# Step search
# ---------------------------------------------------------------------

def search_for_step(
    keywords: list[str],
    context: dict | None = None,
) -> dict | None:

    ctx = dict(
        context or {}
    )

    sentence = str(
        ctx.get(
            "sentence",
            "",
        )
    ).strip()

    clean_keywords = [
        str(keyword).strip()
        for keyword in keywords
        if str(keyword).strip()
    ]

    # ---------------------------------------------------------
    # V2
    #
    # sentence:
    #   자연어 유사도 계산의 주 query
    #
    # keywords:
    #   metadata 매칭용 별도 signal
    # ---------------------------------------------------------

    ctx["_step_keywords"] = (
        clean_keywords
    )

    if sentence:
        query = sentence
    else:
        query = " ".join(
            clean_keywords
        )

    if not query:
        return None

    results = search_assets(
        query,
        ctx,
        limit=5,
    )

    if not results:
        return None

    best = results[0]

    # 평가셋 구축 전까지 기존 threshold 유지
    threshold = float(
        os.getenv(
            "AAC_MATCH_THRESHOLD",
            "0.28",
        )
    )

    if (
        best["score"]
        < threshold
    ):
        return None

    return best