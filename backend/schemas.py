"""백엔드 API 입출력 스키마 (프론트엔드 대면 계약)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

MAX_RAW_INPUT = 2000


# --- 인증 ---
class EmployerLogin(BaseModel):
    login_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class WorkerLogin(BaseModel):
    access_code: str = Field(min_length=1, max_length=32)


class TokenOut(BaseModel):
    token: str
    role: str
    display_name: str


# --- 요청 ---
class TaskCreate(BaseModel):
    # 입력 길이 가드: 빈 입력 거부 + 과도한 입력으로 인한 TTS/AI 비용·DoS 방지
    raw_input: str = Field(min_length=1, max_length=MAX_RAW_INPUT)
    # 맥락적응 분해(LLM)를 위한 선택 컨텍스트
    business_type: str | None = Field(default=None, max_length=100)
    work_environment: str | None = Field(default=None, max_length=300)
    worker_note: str | None = Field(default=None, max_length=300)

    @field_validator("raw_input")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("직무 내용을 입력해 주세요.")
        return v


class StepUpdate(BaseModel):
    sentence: str | None = Field(default=None, max_length=500)
    symbol_url: str | None = Field(default=None, max_length=2000)


class AssignRequest(BaseModel):
    # 미지정 시 사업주의 근로자가 정확히 1명일 때만 자동 배정한다.
    worker_id: str | None = None


class WorkerCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=50)
    # 접속 코드는 근로자 로그인 키. 현장 디바이스 공유를 가정한 짧은 코드.
    access_code: str = Field(min_length=1, max_length=32)


class PerformanceLogCreate(BaseModel):
    assignment_id: str
    step_id: str
    duration_sec: float = Field(default=0.0, ge=0)
    replay_count: int = Field(default=0, ge=0)
    stuck: bool = False


class ArasaacSearchRequest(BaseModel):
    term: str = Field(min_length=1, max_length=100)
    langs: list[str] = []
    limit: int = Field(default=1, ge=1, le=10)


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
    id: str
    display_name: str
    access_code: str


class TodayCardOut(BaseModel):
    assignment_id: str
    task_id: str
    task_title: str
    steps: list[StepOut]


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


class ArasaacMatch(BaseModel):
    language: str
    term: str
    pictogram_id: str
    image_url: str


class ArasaacSearchResult(BaseModel):
    term: str
    matches: list[ArasaacMatch]


# --- 사업주용 AI 코칭 ---
class CoachingSuggestionOut(BaseModel):
    order: int
    issue: str
    suggestion: str
    action: str


class CoachingOut(BaseModel):
    summary: str
    suggestions: list[CoachingSuggestionOut] = []
