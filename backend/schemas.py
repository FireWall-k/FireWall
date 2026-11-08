"""백엔드 API 입출력 스키마 (프론트엔드 대면 계약)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MAX_RAW_INPUT = 2000


# --- 인증 ---
class EmployerLogin(BaseModel):
    login_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class WorkerLogin(BaseModel):
    # 접속 코드는 사업장 안에서만 unique다. 사업장 코드로 사업장을 먼저 정해야 근로자를 찾을 수 있다.
    # 프론트는 사업장 코드를 기기에 한 번 저장해 두고 근로자는 자기 접속 코드만 누른다.
    workplace_code: str = Field(min_length=1, max_length=32)
    access_code: str = Field(min_length=1, max_length=32)


class TokenOut(BaseModel):
    token: str
    role: str
    display_name: str


# --- 요청 ---
class ConfirmedStep(BaseModel):
    """입력 화면에서 사업주가 확인한 단계 한 줄(한 줄 = 한 동작 = 그림 1장)."""
    sentence: str = Field(min_length=1, max_length=500)
    action_type: str = Field(default="other", max_length=20)
    # 나누기 미리보기가 준 그림 검색어. 사업주가 문장을 고치지 않은 줄만 그대로 돌려보낸다
    # (고친 줄은 비워 보내고, 서버가 문장에서 검색어를 다시 뽑는다).
    symbol_query: list[str] | None = Field(default=None, max_length=8)

    @field_validator("sentence")
    @classmethod
    def _sentence_not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("빈 단계 문장이 있습니다.")
        return v

    @field_validator("symbol_query")
    @classmethod
    def _query_terms(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return None
        out = [t.strip()[:50] for t in v if isinstance(t, str) and t.strip()]
        return out or None


class TaskCreate(BaseModel):
    # 입력 길이 가드: 빈 입력 거부 + 과도한 입력으로 인한 TTS/AI 비용·DoS 방지
    raw_input: str = Field(min_length=1, max_length=MAX_RAW_INPUT)
    # 맥락적응 분해(LLM)를 위한 선택 컨텍스트
    business_type: str | None = Field(default=None, max_length=100)
    work_environment: str | None = Field(default=None, max_length=300)
    worker_note: str | None = Field(default=None, max_length=300)
    # 맞춤 대상 근로자(선택). 근로자 특성 메모는 이 근로자가 "AI에 메모 사용"을 허용했고 AI 처리 동의가
    # 살아 있을 때만 AI로 보낸다. 근로자를 지정하지 않으면 누구의 허용인지 알 수 없어 메모를 보내지 않는다.
    worker_id: str | None = Field(default=None, max_length=64)
    # 입력 화면에서 확인한 단계 목록(POST /api/tasks/split-preview 결과를 사업주가 다듬은 것).
    # 있으면 다시 나누지 않고 이 문장들 그대로 그림·음성을 붙인다. 없으면 예전처럼 서버가 나눈다.
    steps: list[ConfirmedStep] | None = Field(default=None, min_length=1, max_length=30)
    # 미리보기가 준 직무 제목·직무 추정값. steps와 함께 온다(없으면 기본값).
    title: str | None = Field(default=None, max_length=100)
    job: str | None = Field(default=None, max_length=50)

    @field_validator("raw_input")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("직무 내용을 입력해 주세요.")
        return v


class StepUpdate(BaseModel):
    sentence: str | None = Field(default=None, max_length=500)
    symbol_url: str | None = Field(default=None, max_length=2000)
    # 검토 화면에서 AAC 후보를 직접 고른 경우 "LOCAL_AAC". 생략하면 기존처럼 fallback.
    symbol_source: Literal["LOCAL_AAC", "fallback"] | None = None


class StepRewrite(BaseModel):
    """편집기에서 단계 문장을 고쳐 저장. 동작이 둘이면 서버가 두 단계로 나눈다(되돌리기 가능)."""
    sentence: str = Field(min_length=1, max_length=500)

    @field_validator("sentence")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("문장을 입력해 주세요.")
        return v


class StepMerge(BaseModel):
    """이어진 단계들을 한 단계로 합친다(편집기의 [되돌리기]). sentence가 합친 단계의 문장이다."""
    step_ids: list[str] = Field(min_length=2, max_length=10)
    sentence: str = Field(min_length=1, max_length=500)

    @field_validator("sentence")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("문장을 입력해 주세요.")
        return v


class StepCreate(BaseModel):
    # 사업주가 검토 화면에서 직접 추가하는 단계. 문장만 받고, 상징/TTS는 서버가 붙인다.
    sentence: str = Field(min_length=1, max_length=500)
    action_type: str = Field(default="other", max_length=20)

    @field_validator("sentence")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("문장을 입력해 주세요.")
        return v


class StepReorder(BaseModel):
    # 새 순서대로 나열된 단계 id 전체. 서버가 이 순서로 order_index를 1..N 재부여한다.
    step_ids: list[str] = Field(min_length=1)


class AssignRequest(BaseModel):
    # worker_ids가 있으면 여러 명에게 한 번에 배정한다. 없고 worker_id만 있으면 그 한 명에게,
    # 둘 다 없으면 사업주의 근로자가 정확히 1명일 때만 자동 배정한다.
    worker_id: str | None = None
    worker_ids: list[str] | None = None


class WorkerCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)
    # 접속 코드는 근로자 로그인 키. 비워 두면 서버가 6자리 무작위 코드를 만든다.
    # 직접 정할 때는 4자리 이상 숫자만 받는다. 4자리(1만 개)는 6자리보다 대입에 약하므로
    # 로그인 시도 제한(ratelimit.py)이 실제 방어선이다 — 코드 자릿수만으로 안전하다고 보지 않는다.
    # (예전에 만든 짧은 코드는 WorkerLogin이 그대로 받아 주므로 기존 근로자는 계속 로그인된다.)
    access_code: str | None = Field(default=None, pattern=r"^\d{4,12}$")

    @field_validator("access_code", mode="before")
    @classmethod
    def _blank_is_none(cls, v):
        return None if isinstance(v, str) and not v.strip() else v


class WorkerUpdate(BaseModel):
    """근로자 정보 수정. 보낸 필드만 바꾼다."""
    display_name: str | None = Field(default=None, min_length=1, max_length=50)
    # 사업주 메모(근로자 특성). 기본으로는 AI에 보내지 않는다(ai_note_allowed 참고).
    note: str | None = Field(default=None, max_length=300)
    # "AI 코칭에 메모 사용" — 사업주가 명시적으로 켜야 한다(기본 false).
    ai_note_allowed: bool | None = None


ConsentType = Literal["personal_info", "ai_processing"]


class ConsentCreate(BaseModel):
    """보호자·당사자에게서 받은 동의를 기록한다(동의서 원본은 사업장이 보관)."""
    consent_type: ConsentType
    subject: Literal["self", "guardian"] = "self"


class PerformanceLogCreate(BaseModel):
    assignment_id: str
    step_id: str
    duration_sec: float = Field(default=0.0, ge=0)
    replay_count: int = Field(default=0, ge=0)
    stuck: bool = False


class AacSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    job: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=5, ge=1, le=20)


# --- 응답 ---
class StepOut(BaseModel):
    id: str
    order: int
    sentence: str
    action_type: str
    symbol_url: str | None
    symbol_source: str
    needs_fallback: bool
    tts_audio_url: str | None


class TaskOut(BaseModel):
    id: str
    title: str
    status: str
    steps: list[StepOut]


class SplitPreviewStep(BaseModel):
    """나누기 미리보기의 한 줄. split_*·source_text는 ai_service 분해 응답 계약을 그대로 옮긴다."""
    order: int
    sentence: str
    action_type: str = "other"
    symbol_query: list[str] = []
    # 같은 원래 절(문장)에서 나온 줄끼리 같은 번호. 원문 그대로인 줄은 None.
    split_group: int | None = None
    # 나눈 것(또는 안 나눈 것)이 애매해 사업주가 봐야 하는 줄 — 입력 화면에서 노랗게 칠한다.
    split_check: bool = False
    # 이 줄들이 나온 원래 절 — [합치기]가 되돌릴 문장.
    source_text: str | None = None


class SplitPreviewOut(BaseModel):
    task_title: str
    job: str = ""
    steps: list[SplitPreviewStep]


class StepRewriteOut(BaseModel):
    task: TaskOut
    # 저장하면서 나눈 경우 새 단계 id들(되돌리기용). 안 나눴으면 빈 목록.
    split_step_ids: list[str] = []
    # 사업주가 적은 문장 그대로 — [되돌리기]가 이 문장 한 단계로 합친다.
    sentence: str


class TaskSummaryOut(BaseModel):
    id: str
    title: str
    status: str
    created_at: datetime


class AssignmentOut(BaseModel):
    id: str
    task_id: str
    worker_id: str
    status: str


class WorkerOut(BaseModel):
    """사업주용 근로자 목록 항목. 그 근로자를 소유한 사업주에게만 나가는 응답이다."""
    id: str
    display_name: str
    # 전체 접속 코드(사업주가 근로자에게 알려 주는 용도). 서버는 암호문으로 들고 있다가 응답 때 푼다.
    # 0005 이전에 만든 근로자는 평문을 몰라 None — 그 근로자가 한 번 로그인하거나 재발급하면 채워진다.
    access_code: str | None = None
    access_code_hint: str
    # 4~5자리 예전 코드를 "짧은 코드" 경고로 보여 주는 데 쓴다.
    access_code_length: int
    note: str = ""
    ai_note_allowed: bool = False
    # AI 처리(국외 이전) 동의가 살아 있는지. 없으면 AI 코칭은 규칙 기반 제안만 쓴다.
    ai_consent: bool = False
    # 개인정보 수집·이용 동의가 살아 있는지. 사업주 화면에서 동의서 수령 기록 여부를 보여 주는 데 쓴다.
    personal_info_consent: bool = False
    # 이름이 일반 낱말("하나"·"보람" 등)과 같아, AI에 보낼 때 호칭("하나 씨")이 붙은 경우만 가릴 수 있다.
    # 사업주 화면에 "직무 문장에는 이름 대신 '근로자'라고 써 달라"는 경고를 띄우는 데 쓴다.
    name_ambiguous: bool = False


class WorkerWithCodeOut(WorkerOut):
    """근로자 생성·코드 재발급 응답 전용. 방금 만든 코드라 항상 있다."""
    access_code: str


class ConsentOut(BaseModel):
    id: str
    consent_type: str
    subject: str
    policy_version: str
    granted_at: datetime
    revoked_at: datetime | None
    recorded_by: str


class WorkplaceOut(BaseModel):
    """사업주 화면에 보여 줄 사업장 코드(근로자 기기에 한 번 입력해 둔다)."""
    workplace_code: str
    org_name: str


class DashboardWorkerOut(BaseModel):
    """대시보드에서 직무별로 어떤 근로자를 볼지 고르기 위한 목록 항목."""
    worker_id: str
    display_name: str
    access_code: str | None = None  # WorkerOut.access_code와 같은 규칙
    access_code_hint: str
    status: str


class TodayCardOut(BaseModel):
    assignment_id: str
    task_id: str
    task_title: str
    steps: list[StepOut]


class HistoryStepOut(StepOut):
    completed: bool


class HistoryCardOut(BaseModel):
    """근로자 본인이 지난번에 받았던 일 — 완료 후에도 다시 열어 볼 수 있게 한다."""
    assignment_id: str
    task_id: str
    task_title: str
    assigned_date: str  # YYYY-MM-DD, 근로자 현지 기준(APP_UTC_OFFSET_HOURS)
    status: str
    steps: list[HistoryStepOut]


class StepStat(BaseModel):
    order: int
    sentence: str
    completed: bool
    duration_sec: float
    replay_count: int
    stuck: bool


class DashboardOut(BaseModel):
    task_id: str
    task_title: str
    total_steps: int
    completed_steps: int
    completion_rate: float
    stuck_steps: list[int]
    steps: list[StepStat]


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


class StepSymbolCandidates(BaseModel):
    """단계에 붙일 AAC 후보. 자동 채택을 못 했을 때 사업주가 직접 고른다.

    reason으로 왜 자동 채택하지 않았는지 알려준다.
      low_margin  — 후보들 점수가 붙어 있어 못 고름. 후보를 보여주고 사람이 선택.
      low_score / no_candidate — 쓸 만한 후보가 없음. 실제 현장 사진을 권한다.
    """
    step_id: str
    reason: Literal["accepted", "no_candidate", "low_score", "low_margin"]
    candidates: list[AacMatch]


# --- 사업주용 AI 코칭 ---
class CoachingSuggestionOut(BaseModel):
    order: int
    issue: str
    suggestion: str
    action: str


class CoachingOut(BaseModel):
    summary: str
    suggestions: list[CoachingSuggestionOut] = []
    # AI 처리 동의가 없는 근로자 기록이 섞여 LLM을 쓰지 않고 규칙 기반 제안만 만든 경우 true.
    # 화면에서 "동의를 기록하면 더 자세한 제안을 받을 수 있다"고 안내하는 데 쓴다.
    ai_excluded: bool = False
