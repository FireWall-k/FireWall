"""AI 하네스 입출력 스키마.

기술 명세서 3-2의 JSON 스키마를 Pydantic으로 고정한다.
LLM 출력은 반드시 DecomposeResult 형태만 통과시킨다(스키마 검증 = 가드레일).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- /ai/decompose ---------------------------------------------------------

ActionType = Literal["observe", "move", "stack", "sort", "pack", "clean", "other"]


class Keyword(BaseModel):
    term: str
    pos: Literal["noun", "verb", "adj", "other"] = "other"


class Step(BaseModel):
    order: int = Field(ge=1)
    sentence: str
    keywords: list[Keyword] = []
    # LLM이 제공하는 AAC 그림 검색용 구체 명사(있으면 키워드 대신 우선 사용).
    symbol_query: list[str] = []
    action_type: ActionType = "other"
    safety_flags: list[str] = []


class DecomposeRequest(BaseModel):
    raw_input: str
    context: dict = {}


class DecomposeResult(BaseModel):
    task_title: str
    steps: list[Step]


# --- /ai/map-symbols -------------------------------------------------------


class MapSymbolsRequest(BaseModel):
    keywords: list[str]
    context: dict = {}


class AacSearchRequest(BaseModel):
    query: str
    context: dict = {}
    limit: int = Field(default=5, ge=1, le=20)


class AacMatch(BaseModel):
    asset_id: str
    group_id: str
    job: str
    asset_type: str
    label: str
    image_url: str
    score: float


class AacSearchResult(BaseModel):
    query: str
    matches: list[AacMatch]


# 자동 채택 판정 결과. low_margin은 '후보는 있는데 못 고름'이라 검토 화면에서
# 후보를 보여주고 사람이 고르게 해야 한다. 나머지 거절 사유는 폴백/사진 유도.
MatchReason = Literal["accepted", "no_candidate", "low_score", "low_margin"]


class Symbol(BaseModel):
    keyword: str
    image_url: str | None = None
    #source: Literal["ARASAAC", "KAAC", "fallback"] = "fallback"
    source: Literal["LOCAL_AAC", "fallback"] = "fallback"
    confidence: float = 0.0
    needs_fallback: bool = False
    external_id: str | None = None
    resolved_keyword: str | None = None
    reason: MatchReason = "no_candidate"
    # 자동 채택하지 못했을 때 사람이 고를 후보. 채택했으면 비워 둔다.
    candidates: list[AacMatch] = []


class MapSymbolsResult(BaseModel):
    symbols: list[Symbol]


# --- /ai/coaching (사업주용 AI 코칭) ---------------------------------------

CoachingAction = Literal["rephrase", "photo", "split", "ok"]


class CoachingStepInput(BaseModel):
    order: int
    sentence: str
    completed: bool = False
    stuck: bool = False
    replay_count: int = 0
    duration_sec: float = 0.0


class CoachingRequest(BaseModel):
    task_title: str
    steps: list[CoachingStepInput]
    context: dict = {}


class CoachingSuggestion(BaseModel):
    order: int
    issue: str
    suggestion: str
    action: CoachingAction = "ok"


class CoachingResult(BaseModel):
    summary: str
    suggestions: list[CoachingSuggestion] = []
