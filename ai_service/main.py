"""AI 하네스 서비스 (FastAPI).

계약: 기술 명세서 4-2.
  POST /ai/decompose    원문 -> 단계 배열 (검증 통과분)
  POST /ai/map-symbols  키워드 배열 -> 상징 매핑 + 폴백 플래그

하네스 4원칙을 골격으로 담는다: 계약 / 검증 / 폴백 / 관측가능성.
LLM은 아직 목(decompose.py)이지만, 바깥 인터페이스는 최종형과 동일하다.
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

import embeddings
import gpt_usage
import local_aac
import llm
from local_aac import search_assets
from decompose import _guess_action, decompose, may_split
from schemas import (
    AacMatch,
    AacSearchRequest,
    AacSearchResult,
    CoachingRequest,
    CoachingResult,
    CoachingStepInput,
    ClassifyActionRequest,
    ClassifyActionResult,
    SplitHintResult,
    CoachingSuggestion,
    DecomposeRequest,
    DecomposeResult,
    MapSymbolsRequest,
    MapSymbolsResult,
)
from symbols import map_symbols

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai_harness")


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    # 로컬 임베딩 모델 로딩(~3초)을 시작과 함께 뒤에서 한다. 그동안 들어온 요청은 로딩이 끝나기를
    # 기다릴 뿐 실패하지 않는다(embeddings.load_local_model의 잠금).
    try:
        local_aac.log_embed_settings()
    except Exception:  # 진단 로그 실패가 기동을 막으면 안 된다
        logger.exception("임베딩 보정값 로그 실패")
    threading.Thread(target=embeddings.warm_up, name="embed-warmup", daemon=True).start()
    yield


app = FastAPI(title="JOB CARD - AI Harness", version="0.1.0", lifespan=_lifespan)

MAX_RETRIES = 2  # (가정) 스키마 검증 실패 시 재시도 횟수


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ai/usage")
def ai_usage() -> dict:
    """이번 달(한국 시간) GPT 사용량 합계·종류별·최근 7일과 알림 기준(GPT_MONTHLY_ALERT_USD).

    요금은 토큰 수로 셈한 추정값이다. 내용(문장)은 기록하지 않는다(gpt_usage.py).
    """
    return gpt_usage.summary()


@app.post("/ai/decompose", response_model=DecomposeResult)
def ai_decompose(req: DecomposeRequest) -> DecomposeResult:
    # --- 가드레일: 입력 검증 ---
    if not req.raw_input or not req.raw_input.strip():
        raise HTTPException(status_code=422, detail="raw_input이 비어 있습니다.")

    # --- LLM 분해 (목) + 검증/재시도 골격 ---
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            result = decompose(req.raw_input, req.context.model_dump())
            # 가드레일: 빈 단계는 거부
            if not result.steps:
                raise ValueError("분해 결과 단계가 0개입니다.")
            # 관측가능성: 한 건당 입력 길이/시도/단계 수 기록. 원문은 남기지 않는다 — 직무 지시문에
            # 근로자 이름·특성이 들어갈 수 있고, 로그는 보존·삭제 관리 밖에 있다.
            logger.info(
                "decompose ok attempt=%s steps=%s input_len=%s",
                attempt, len(result.steps), len(req.raw_input),
            )
            return result
        except Exception as e:  # noqa: BLE001 - 스켈레톤에서는 광범위 캐치 후 재시도
            last_error = e
            logger.warning("decompose retry attempt=%s error=%s", attempt, e)

    raise HTTPException(status_code=502, detail=f"분해 실패: {last_error}")


@app.post("/ai/classify-action", response_model=ClassifyActionResult)
def ai_classify_action(req: ClassifyActionRequest) -> ClassifyActionResult:
    """단계 문장 하나의 동작 계열(action_type). 직무 분해(규칙)와 같은 분류기(_guess_action)를 쓴다.

    사업주가 검토 화면에서 문장을 고치면 백엔드가 이것으로 계열을 다시 매긴다. 예전에는 다시 추정할 길이 없어
    other로 되돌렸고, 사업주 화면의 동작 꼬리표가 단계를 다시 만들 때까지 '작업하기'로 남았다.
    결정론적 규칙만 쓴다 — LLM·임베딩 호출이 없어 비용이 들지 않고 문장이 밖으로 나가지 않는다.
    """
    return ClassifyActionResult(action_type=_guess_action(req.sentence))


@app.post("/ai/split-hint", response_model=SplitHintResult)
def ai_split_hint(req: ClassifyActionRequest) -> SplitHintResult:
    """고친 단계 문장 하나에 동작이 둘 이상일 수 있는가 — 규칙 동작 세기(step_split)만 쓴다(LLM·외부 API 없음).

    백엔드는 편집기 저장 때 이것이 True일 때만 GPT 분해를 부른다. 겉모양 정규식은 '냉장고'·'계산대'처럼 명사
    끝 글자에도 걸려 동작 하나짜리 문장의 오타 고치기마다 GPT를 불렀다(입력 화면 나누기 2차 검증).
    """
    hint = may_split(req.sentence)
    return SplitHintResult(**hint)


@app.post("/ai/map-symbols", response_model=MapSymbolsResult)
def ai_map_symbols(req: MapSymbolsRequest) -> MapSymbolsResult:
    result = map_symbols(req.keywords, req.context.model_dump(exclude_unset=True))
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
        req.context.model_dump(exclude_unset=True),
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
    # allow_llm=False: AI 처리 동의가 없는 근로자 기록이 들어 있다 → 해외 LLM으로 보내지 않고 규칙 기반만 쓴다.
    if req.allow_llm and llm.llm_available():
        try:
            raw = llm.llm_coaching(
                req.task_title,
                [s.model_dump() for s in req.steps],
                req.context.model_dump(),
            )
            result = CoachingResult(**raw)  # 가드레일: 스키마 검증
            result = _ensure_stuck_steps_covered(req, result)
            logger.info("coaching via LLM: %s suggestions", len(result.suggestions))
            return result
        except Exception as e:  # noqa: BLE001 - LLM 실패 시 휴리스틱 폴백
            logger.warning("LLM coaching 실패, 휴리스틱 폴백: %s", e)
    return _rule_coaching(req)
