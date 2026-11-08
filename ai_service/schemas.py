"""AI 하네스 입출력 스키마.

기술 명세서 3-2의 JSON 스키마를 Pydantic으로 고정한다.
LLM 출력은 반드시 DecomposeResult 형태만 통과시킨다(스키마 검증 = 가드레일).
"""
from __future__ import annotations

from typing import Literal

from taxonomy import ActionType, JobType

from pydantic import BaseModel, ConfigDict, Field

# --- /ai/decompose ---------------------------------------------------------

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


class DecomposeContext(BaseModel):
    """분해 요청 맥락. LLM 프롬프트에 들어갈 수 있는 필드만 받는다.

    예전에는 아무 dict나 받아 그대로 넘겼다. 그러면 호출하는 쪽이 실수로 근로자 이름(worker_name,
    display_name 등)을 넣어도 해외 LLM까지 간다. 모르는 필드는 여기서 버린다(extra="ignore") —
    거절(422)하지 않는 이유는 백엔드가 맥락 필드를 늘려도 분해 자체가 멈추지 않게 하려는 것이다.
    worker_note는 백엔드가 사업주 허용 + 근로자 동의를 확인한 뒤에만 채운다(backend/main._sendable_note).
    """
    model_config = ConfigDict(extra="ignore")

    business_type: str = ""
    work_environment: str = ""
    worker_note: str = ""
    raw_input: str = ""
    job: str = ""


class DecomposeRequest(BaseModel):
    raw_input: str
    context: DecomposeContext = DecomposeContext()


class DecomposeResult(BaseModel):
    task_title: str
    job: JobType = "unknown"
    steps: list[Step]


# --- /ai/classify-action ---------------------------------------------------

class ClassifyActionRequest(BaseModel):
    """사업주가 고친 단계 문장 하나. 규칙 분류만 하므로 LLM·외부 API로 나가지 않는다."""
    sentence: str = Field(max_length=500)


class ClassifyActionResult(BaseModel):
    action_type: ActionType = "other"


# --- /ai/map-symbols -------------------------------------------------------


class SymbolContext(BaseModel):
    """그림 매칭·검색 맥락. AAC 검색(local_aac)이 실제로 읽는 필드만 받고 나머지는 버린다.

    예전에는 아무 dict나 받아 그대로 넘겼다. 이 경로도 질의 문장을 임베딩 API(해외)로 보내므로, 호출하는
    쪽이 이름 필드를 실수로 넣으면 그대로 흘러간다. DecomposeContext와 같은 이유로 거절(422) 대신 버린다.
    main.py는 model_dump(exclude_unset=True)로 넘겨, 보낸 필드만 예전과 똑같은 dict로 검색에 전달한다
    (빈 값 기본값이 끼어들어 매칭 결과가 달라지지 않게).
    """
    model_config = ConfigDict(extra="ignore")

    # None도 받는다. 예전 dict 계약에서는 백엔드가 빈 값을 None으로 보내도 통과했으므로, 여기서 422로
    # 바꾸면 그림 매칭 전체가 폴백으로 떨어진다.
    business_type: str | None = None
    work_environment: str | None = None
    job: str | None = None
    job_hint: str | None = None
    sentence: str | None = None
    action_type: str | None = None
    raw_input: str | None = None


class MapSymbolsRequest(BaseModel):
    keywords: list[str]
    context: SymbolContext = SymbolContext()


class AacSearchRequest(BaseModel):
    query: str
    context: SymbolContext = SymbolContext()
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
    # 동작 특성(관찰/조작/조립 등). LLM이 action_type에 맞는 조치를 고르는 데 쓴다
    # (예: assemble이면 split, observe면 rephrase 쪽이 더 맞는 경우가 많다).
    action_type: ActionType = "other"


class CoachingContext(BaseModel):
    """코칭 요청 맥락. DecomposeContext와 같은 이유로 프롬프트에 넣을 필드만 받고 나머지는 버린다."""
    model_config = ConfigDict(extra="ignore")

    business_type: str = ""
    work_environment: str = ""
    job: str = ""
    worker_note: str = ""


class CoachingRequest(BaseModel):
    task_title: str
    steps: list[CoachingStepInput]
    context: CoachingContext = CoachingContext()
    # 백엔드가 근로자의 AI 처리(국외 이전) 동의를 확인하지 못하면 false로 보낸다. 그러면 LLM을 부르지 않고
    # 규칙 기반 제안만 만든다. 기본 true는 이 필드가 없던 예전 백엔드와의 호환용이다.
    allow_llm: bool = True


class CoachingSuggestion(BaseModel):
    order: int
    issue: str
    suggestion: str
    action: CoachingAction = "ok"


class CoachingResult(BaseModel):
    summary: str
    suggestions: list[CoachingSuggestion] = []
