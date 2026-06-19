"""AAC 상징 매핑.

ARASAAC 공개 API를 우선 검색하고, 실패하면 fallback으로 넘긴다.
한국어 현장 직무 용어는 ARASAAC 언어권 검색에서 바로 잡히지 않을 수 있어
간단한 한→영/스페인어 검색어 보정 사전을 함께 사용한다.
"""
from __future__ import annotations

import logging
import os

from arasaac import search_term
from schemas import MapSymbolsResult, Symbol

logger = logging.getLogger("ai_harness.symbols")

ARASAAC_SEARCH_TIMEOUT = float(os.getenv("ARASAAC_SEARCH_TIMEOUT", "0.8"))
ARASAAC_LANGS = [
    lang.strip() for lang in os.getenv("ARASAAC_LANGS", "ko,en,es").split(",") if lang.strip()
]
ARASAAC_KEYWORD_SEARCH_LIMIT = int(os.getenv("ARASAAC_KEYWORD_SEARCH_LIMIT", "1"))
ARASAAC_TERM_SEARCH_LIMIT = int(os.getenv("ARASAAC_TERM_SEARCH_LIMIT", "1"))

# 한국어 작업장 표현 → ARASAAC에서 더 잘 검색되는 후보어.
# MVP용 최소 사전이며, 실증 과정에서 DB로 분리해 축적하는 것이 바람직하다.
_KO_QUERY_EXPANSIONS: dict[str, list[str]] = {
    "택배": ["package", "box", "paquete"],
    "상자": ["box", "package", "caja"],
    "박스": ["box", "caja"],
    "큰": ["big", "large", "grande"],
    "작은": ["small", "pequeño"],
    "분류": ["sort", "classify", "clasificar"],
    "나누": ["sort", "separate", "separar"],
    "구분": ["sort", "separate"],
    "정리": ["organize", "tidy", "ordenar"],
    "옮": ["move", "carry", "mover"],
    "이동": ["move", "mover"],
    "쌓": ["stack", "pile", "apilar"],
    "적재": ["stack", "load"],
    "포장": ["pack", "package", "embalar"],
    "담": ["put", "place", "poner"],
    "확인": ["check", "see", "comprobar"],
    "점검": ["check", "inspect", "revisar"],
    "수량": ["count", "number", "contar"],
    "개수": ["count", "number"],
    "청소": ["clean", "limpiar"],
    "닦": ["wipe", "clean", "limpiar"],
    "카페": ["coffee", "cafe"],
    "컵": ["cup", "vaso"],
    "쓰레기": ["trash", "garbage", "basura"],
}

# 의미가 너무 약해서 상징 검색어로 쓰기 어려운 단어.
_STOPWORDS = {
    "그리고", "그다음", "그", "다음", "마지막", "마지막에", "해주세요", "합니다", "한다",
    "오늘", "먼저", "이후", "후", "때", "곳", "구역", "A구역", "B구역",
}


def _normalize_keyword(keyword: str) -> str:
    return keyword.strip().strip(".,!?;:()[]{}\"'")


def _query_candidates(keyword: str) -> list[str]:
    keyword = _normalize_keyword(keyword)
    if not keyword or keyword in _STOPWORDS:
        return []

    # 한국어 원문은 ARASAAC 검색 성공률이 낮으므로, 매핑 사전이 있으면 보정 후보를 먼저 둔다.
    expansions: list[str] = []
    for ko, values in _KO_QUERY_EXPANSIONS.items():
        if ko in keyword:
            expansions.extend(values)

    candidates: list[str] = expansions + [keyword]

    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        c = _normalize_keyword(c)
        key = c.lower()
        if len(c) < 2 or key in seen:
            continue
        seen.add(key)
        result.append(c)
    return result[:4]


def map_symbols(keywords: list[str], context: dict) -> MapSymbolsResult:
    symbols: list[Symbol] = []

    # ARASAAC 장애/네트워크 차단이 직무 생성 전체를 오래 막지 않도록 앞쪽 핵심 키워드만 실제 검색한다.
    searchable_count = 0
    for raw_kw in keywords:
        candidates = _query_candidates(raw_kw)
        if not candidates or searchable_count >= ARASAAC_KEYWORD_SEARCH_LIMIT:
            symbols.append(
                Symbol(keyword=raw_kw, image_url=None, source="fallback", confidence=0.0, needs_fallback=True)
            )
            continue

        searchable_count += 1
        # 후보어들을 검색해 exact 매칭을 최우선으로 고른다(첫 결과 무비판 사용 제거).
        best: dict | None = None
        best_term = candidates[0]
        for term in candidates[:ARASAAC_TERM_SEARCH_LIMIT]:
            matches = search_term(term, langs=ARASAAC_LANGS, timeout=ARASAAC_SEARCH_TIMEOUT)
            if not matches:
                continue
            top = matches[0]  # search_term이 exact를 앞에 정렬해 둠
            if best is None:
                best, best_term = top, term
            if top.get("exact"):
                best, best_term = top, term
                break

        if best:
            symbols.append(
                Symbol(
                    keyword=raw_kw,
                    image_url=best["image_url"],
                    source="ARASAAC",
                    confidence=0.95 if best.get("exact") else 0.7,
                    needs_fallback=False,
                    external_id=best["pictogram_id"],
                    resolved_keyword=best.get("matched_keyword") or best_term,
                )
            )
        else:
            symbols.append(
                Symbol(keyword=raw_kw, image_url=None, source="fallback", confidence=0.0, needs_fallback=True)
            )

    return MapSymbolsResult(symbols=symbols)
