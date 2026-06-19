"""AI 하네스 서비스 (FastAPI).

계약: 기술 명세서 4-2.
  POST /ai/decompose    원문 -> 단계 배열 (검증 통과분)
  POST /ai/map-symbols  키워드 배열 -> 상징 매핑 + 폴백 플래그

하네스 4원칙을 골격으로 담는다: 계약 / 검증 / 폴백 / 관측가능성.
LLM은 아직 목(decompose.py)이지만, 바깥 인터페이스는 최종형과 동일하다.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException

import llm
from arasaac import search_term
from decompose import decompose
from schemas import (
    ArasaacMatch,
    ArasaacSearchRequest,
    ArasaacSearchResult,
    CoachingRequest,
    CoachingResult,
    CoachingSuggestion,
    DecomposeRequest,
    DecomposeResult,
    MapSymbolsRequest,
    MapSymbolsResult,
)
from symbols import map_symbols

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_harness")

app = FastAPI(title="JOB CARD - AI Harness", version="0.1.0")

MAX_RETRIES = 2  # (가정) 스키마 검증 실패 시 재시도 횟수


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ai/decompose", response_model=DecomposeResult)
def ai_decompose(req: DecomposeRequest) -> DecomposeResult:
    # --- 가드레일: 입력 검증 ---
    if not req.raw_input or not req.raw_input.strip():
        raise HTTPException(status_code=422, detail="raw_input이 비어 있습니다.")

    # --- LLM 분해 (목) + 검증/재시도 골격 ---
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = decompose(req.raw_input, req.context)
            # 가드레일: 빈 단계는 거부
            if not result.steps:
                raise ValueError("분해 결과 단계가 0개입니다.")
            # 관측가능성: 한 건당 입력/시도/단계 수 기록
            logger.info(
                "decompose ok attempt=%s steps=%s input=%r",
                attempt, len(result.steps), req.raw_input[:40],
            )
            return result
        except Exception as e:  # noqa: BLE001 - 스켈레톤에서는 광범위 캐치 후 재시도
            last_error = e
            logger.warning("decompose retry attempt=%s error=%s", attempt, e)

    raise HTTPException(status_code=502, detail=f"분해 실패: {last_error}")


@app.post("/ai/map-symbols", response_model=MapSymbolsResult)
def ai_map_symbols(req: MapSymbolsRequest) -> MapSymbolsResult:
    result = map_symbols(req.keywords, req.context)
    fallback_count = sum(1 for s in result.symbols if s.needs_fallback)
    logger.info("map-symbols ok total=%s fallback=%s",
                len(result.symbols), fallback_count)
    return result


@app.post("/ai/arasaac/search", response_model=ArasaacSearchResult)
def ai_arasaac_search(req: ArasaacSearchRequest) -> ArasaacSearchResult:
    if not req.term.strip():
        raise HTTPException(status_code=422, detail="term이 비어 있습니다.")

    matches = search_term(req.term.strip(), langs=req.langs or None)
    limited = matches[: max(req.limit, 1)]
    return ArasaacSearchResult(
        term=req.term.strip(),
        matches=[ArasaacMatch(**match) for match in limited],
    )


# 자동 '막힘' 판정 임계(프론트 임계와 동일 기준)
_STUCK_REPLAY = 3
_STUCK_DURATION = 120.0


def _rule_coaching(req: CoachingRequest) -> CoachingResult:
    """LLM 미사용/실패 시 휴리스틱 코칭(수행 데이터 기반)."""
    suggestions: list[CoachingSuggestion] = []
    for s in req.steps:
        if s.stuck or s.replay_count >= _STUCK_REPLAY or s.duration_sec >= _STUCK_DURATION:
            if s.duration_sec >= _STUCK_DURATION:
                action, sug = "split", "이 단계를 두 개의 더 작은 동작으로 나눠보세요."
            elif s.replay_count >= _STUCK_REPLAY:
                action, sug = "photo", "그림이 잘 전달되지 않을 수 있어요. 실제 현장 사진으로 교체해 보세요."
            else:
                action, sug = "rephrase", "문장을 더 짧고 쉬운 말로 바꿔보세요."
            suggestions.append(CoachingSuggestion(
                order=s.order,
                issue=f"{s.order}단계에서 어려움 징후(다시듣기 {s.replay_count}회, "
                      f"소요 {round(s.duration_sec)}초, 막힘 {'예' if s.stuck else '아니오'}).",
                suggestion=sug, action=action,
            ))
    if suggestions:
        summary = f"{len(suggestions)}개 단계에서 개선이 필요해 보입니다."
    else:
        summary = "전반적으로 무난하게 수행하고 있습니다."
    return CoachingResult(summary=summary, suggestions=suggestions)


@app.post("/ai/coaching", response_model=CoachingResult)
def ai_coaching(req: CoachingRequest) -> CoachingResult:
    if llm.llm_available():
        try:
            raw = llm.llm_coaching(
                req.task_title,
                [s.model_dump() for s in req.steps],
                req.context,
            )
            result = CoachingResult(**raw)  # 가드레일: 스키마 검증
            logger.info("coaching via LLM: %s suggestions", len(result.suggestions))
            return result
        except Exception as e:  # noqa: BLE001 - LLM 실패 시 휴리스틱 폴백
            logger.warning("LLM coaching 실패, 휴리스틱 폴백: %s", e)
    return _rule_coaching(req)
