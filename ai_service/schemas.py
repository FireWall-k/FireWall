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


class ArasaacSearchRequest(BaseModel):
    term: str
    langs: list[str] = []
    limit: int = 1


class ArasaacMatch(BaseModel):
    language: str
    term: str
    pictogram_id: str
    image_url: str


class ArasaacSearchResult(BaseModel):
    term: str
    matches: list[ArasaacMatch]


class Symbol(BaseModel):
    keyword: str
    image_url: str | None = None
    source: Literal["ARASAAC", "KAAC", "fallback"] = "fallback"
    confidence: float = 0.0
    needs_fallback: bool = False
    external_id: str | None = None
    resolved_keyword: str | None = None


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
