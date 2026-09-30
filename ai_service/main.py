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
from local_aac import search_assets
from decompose import decompose
from schemas import (
    AacMatch,
    AacSearchRequest,
    AacSearchResult,
    CoachingRequest,
    CoachingResult,
    CoachingStepInput,
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

@app.post("/ai/aac/search", response_model=AacSearchResult)
def ai_aac_search(req: AacSearchRequest) -> AacSearchResult:
    query = req.query.strip()

    if not query:
        raise HTTPException(
            status_code=422,
            detail="query가 비어 있습니다."
        )

    matches = search_assets(
        query,
        req.context,
        limit=req.limit
    )

    return AacSearchResult(
        query=query,
        matches=[
            AacMatch(**match)
            for match in matches
        ],
    )


# 자동 '막힘' 판정 임계(프론트 임계와 동일 기준)
_STUCK_REPLAY = 3
_STUCK_DURATION = 120.0


def _is_stuck(s: CoachingStepInput) -> bool:
    return s.stuck or s.replay_count >= _STUCK_REPLAY or s.duration_sec >= _STUCK_DURATION


def _heuristic_suggestion(s: CoachingStepInput) -> CoachingSuggestion:
    """단계 하나에 대한 규칙 기반 제안. LLM 미사용 폴백과, LLM이 놓친 막힘 단계를
    채워 넣는 보강(_ensure_stuck_steps_covered) 둘 다에서 쓴다."""
    if s.duration_sec >= _STUCK_DURATION:
        action, sug = "split", "이 단계를 두 개의 더 작은 동작으로 나눠보세요."
    elif s.replay_count >= _STUCK_REPLAY:
        action, sug = "photo", "그림이 잘 전달되지 않을 수 있어요. 실제 현장 사진으로 교체해 보세요."
    elif s.action_type == "assemble":
        action, sug = "split", "조립 단계는 부품을 미리 나눠 두거나 두 동작으로 쪼개 보세요."
    else:
        action, sug = "rephrase", "문장을 더 짧고 쉬운 말로 바꿔보세요."
    return CoachingSuggestion(
        order=s.order,
        issue=f"{s.order}단계에서 어려움 징후(다시듣기 {s.replay_count}회, "
              f"소요 {round(s.duration_sec)}초, 막힘 {'예' if s.stuck else '아니오'}).",
        suggestion=sug, action=action,
    )


def _rule_coaching(req: CoachingRequest) -> CoachingResult:
    """LLM 미사용/실패 시 휴리스틱 코칭(수행 데이터 기반)."""
    suggestions = [_heuristic_suggestion(s) for s in req.steps if _is_stuck(s)]
    if suggestions:
        summary = f"{len(suggestions)}개 단계에서 개선이 필요해 보입니다."
    else:
        summary = "전반적으로 무난하게 수행하고 있습니다."
    return CoachingResult(summary=summary, suggestions=suggestions)


def _ensure_stuck_steps_covered(req: CoachingRequest, result: CoachingResult) -> CoachingResult:
    """막힘 신호가 있는 단계는 LLM이 빠뜨렸어도 반드시 제안을 받는다.

    프롬프트로 "막힘 단계는 전부 다루라"고 지시는 하지만, LLM이 지시를 놓치거나 판단이
    달라(예: replay_count=3인데 "경미하다"고 스스로 판단) 응답에서 통째로 빠질 수 있다.
    지시만 믿지 않고, 서버가 실제 수행 데이터로 계산한 막힘 여부와 대조해 빠진 단계를
    규칙 기반 제안으로 채운다 — LLM 응답을 지우지 않고 보태기만 한다.
    """
    covered = {sg.order for sg in result.suggestions}
    missing = [s for s in req.steps if _is_stuck(s) and s.order not in covered]
    if not missing:
        return result
    suggestions = sorted(
        [*result.suggestions, *(_heuristic_suggestion(s) for s in missing)],
        key=lambda sg: sg.order,
    )
    summary = result.summary.strip() or f"{len(suggestions)}개 단계에서 개선이 필요해 보입니다."
    logger.info("coaching: LLM이 놓친 막힘 단계 %s개를 보강함", len(missing))
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
            result = _ensure_stuck_steps_covered(req, result)
            logger.info("coaching via LLM: %s suggestions", len(result.suggestions))
            return result
        except Exception as e:  # noqa: BLE001 - LLM 실패 시 휴리스틱 폴백
            logger.warning("LLM coaching 실패, 휴리스틱 폴백: %s", e)
    return _rule_coaching(req)
