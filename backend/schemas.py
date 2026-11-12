"""백엔드 API 입출력 스키마 (프론트엔드 대면 계약)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

MAX_RAW_INPUT = 2000
# 입력 화면에서 확인한 단계 문장 합계의 상한. 단계마다 그림 검색(임베딩 API)·음성 합성을 하므로 원문 상한과 같은
# 이유로 막는다. 사업주가 줄을 고치거나 더하면 원문보다 조금 길어질 수 있어 여유를 둔다.
MAX_CONFIRMED_TOTAL = MAX_RAW_INPUT + 500
# 입력 화면에서 확인한 단계 줄 수·한 줄 글자 수의 상한(프런트 SplitPreviewList도 같은 값으로 미리 막는다).
MAX_CONFIRMED_STEPS = 30
MAX_STEP_SENTENCE = 500


# --- 인증 ---
class EmployerLogin(BaseModel):
    login_id: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class WorkerLogin(BaseModel):
    # 접속 코드는 사업장 안에서만 unique다. 사업장 코드로 사업장을 먼저 정해야 근로자를 찾을 수 있다.
    # 프론트는 사업장 코드를 기기에 한 번 저장해 두고 근로자는 자기 접속 코드만 누른다.
    workplace_code: str = Field(min_length=1, max_length=32)
    access_code: str = Field(min_length=1, max_length=32)
    # 이 기기가 전에 맞게 들어왔을 때 받은 표시(TokenOut.device_token). 있으면 사업장 공용 잠금 대신 근로자 몫의
    # 잠금만 본다(main.worker_login). 없거나 틀리면 그냥 믿지 않는 기기로 본다.
    device_token: str | None = Field(default=None, max_length=512)


class TokenOut(BaseModel):
    token: str
    role: str
    display_name: str
    # 근로자 로그인 응답에만 싣는 사업장 이름(키패드 위 띠에 보여 준다). 사업주 로그인은 None.
    # 로그인 전에 사업장 이름을 알려 주는 공개 API는 두지 않는다(사업장 코드 존재 오라클이 된다).
    workplace_name: str | None = None
    # 근로자 로그인 응답에만: 믿는 기기 표시. 근로자 기기가 저장해 두고 다음 로그인 때 보낸다.
    device_token: str | None = None


# --- 근로자 화면 설정(0006 a11y_prefs) ---
TTS_RATES = (0.8, 0.9, 1.0)


class A11yPrefs(BaseModel):
    """근로자 화면 설정. 응답은 항상 8개 키를 모두 채운다(기본값 포함)."""
    font_size: Literal["normal", "large"] = "normal"
    # 단계에 들어갈 때 문장 소리를 저절로 들려줄지(창업자 결정 4: 기본 켬, 근로자마다 끌 수 있다).
    autoplay_sound: bool = True
    # 서버 mp3는 0.9로 합성돼 있다. 프론트는 audio.playbackRate = tts_rate / 0.9로 맞춘다.
    tts_rate: float = 0.9
    sfx: bool = True
    vibration: bool = False
    praise: Literal["normal", "quiet"] = "normal"
    hand: Literal["right", "left"] = "right"
    contrast: Literal["normal", "high"] = "normal"

    @field_validator("tts_rate")
    @classmethod
    def _rate(cls, v: float) -> float:
        if v not in TTS_RATES:
            raise ValueError("tts_rate는 0.8, 0.9, 1.0 중 하나여야 합니다.")
        return v


class A11yPrefsPatch(BaseModel):
    """사업주가 근로자 화면 설정을 부분 변경한다. 보낸 키만 바꾼다. 쓰기는 엄격하다(모르는 키·허용 밖 값은 422).

    strict: 타입도 바꿔 주지 않는다(2차 검증: 예전에는 tts_rate true → 1.0, autoplay_sound 'off' → false로 받았다).
    JSON 숫자 1은 tts_rate 1.0으로 받는다(strict float도 정수는 받는다).
    """
    model_config = ConfigDict(extra="forbid", strict=True)
    font_size: Literal["normal", "large"] | None = None
    autoplay_sound: bool | None = None
    tts_rate: float | None = None
    sfx: bool | None = None
    vibration: bool | None = None
    praise: Literal["normal", "quiet"] | None = None
    hand: Literal["right", "left"] | None = None
    contrast: Literal["normal", "high"] | None = None

    @field_validator("tts_rate")
    @classmethod
    def _rate(cls, v: float | None) -> float | None:
        if v is not None and v not in TTS_RATES:
            raise ValueError("tts_rate는 0.8, 0.9, 1.0 중 하나여야 합니다.")
        return v


def parse_a11y_prefs(raw: str | None) -> A11yPrefs:
    """DB에 저장된 JSON을 읽는다. 읽기는 관용: 깨진 JSON·모르는 키는 버리고, 잘못된 값은 그 키만 기본값으로 둔다."""
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    kept: dict = {}
    for key in A11yPrefs.model_fields:
        if key not in data:
            continue
        try:
            A11yPrefs(**{key: data[key]})
        except ValidationError:
            continue
        kept[key] = data[key]
    return A11yPrefs(**kept)


def merge_a11y_prefs(raw: str | None, patch: A11yPrefsPatch) -> str:
    """저장된 설정에 보낸 키만 덮어써 JSON 문자열로 돌려준다."""
    merged = parse_a11y_prefs(raw).model_dump()
    merged.update(patch.model_dump(exclude_unset=True, exclude_none=True))
    return json.dumps(A11yPrefs(**merged).model_dump(), ensure_ascii=False)


class WorkerMeOut(BaseModel):
    id: str
    display_name: str
    workplace_name: str
    # 근로자 화면에서 사업주를 부르는 호칭(창업자 결정 1). 사업장별 설정은 2차.
    teacher_title: str = "선생님"
    a11y_prefs: A11yPrefs


# --- 요청 ---
class ConfirmedSplit(BaseModel):
    source: Literal["rule", "model", "manual", ""] = ""
    original_span: str | None = Field(default=None, max_length=MAX_STEP_SENTENCE * 2)
    # 받아도 쓰지 않는다(contract §3.2: POST /api/tasks는 needs_review를 늘 False로 저장).
    needs_review: bool | None = None


class ConfirmedStep(BaseModel):
    """입력 화면에서 사업주가 확인한 단계 한 줄(한 줄 = 한 동작 = 그림 1장)."""
    sentence: str = Field(min_length=1, max_length=MAX_STEP_SENTENCE)
    # 미리보기가 준 동작 계열. 사업주가 고치거나 합치거나 새로 쓴 줄은 보내지 않는다(None) — 서버가 규칙 분류기로
    # 다시 매긴다(2차 검증: 'other'로 저장돼 근로자 화면 동작 꼬리표가 숨고 그림 검색이 동작 맥락을 못 썼다).
    action_type: str | None = Field(default=None, max_length=20)
    # 나누기 미리보기가 준 그림 검색어. 사업주가 문장을 고치지 않은 줄만 그대로 돌려보낸다
    # (고친 줄은 비워 보내고, 서버가 문장에서 검색어를 다시 뽑는다).
    symbol_query: list[str] | None = Field(default=None, max_length=8)
    # (2b-1) 입력 화면이 이 줄을 어떻게 나눴는지와 원래 지시문 조각. needs_review는 받아도 버린다(늘 False로 저장 —
    # [이대로 그림 고르기]가 나누기 확인이다, contract §3.2).
    split: ConfirmedSplit | None = None
    # (2b-1) 나누기 미리보기의 '✦ 자동 제안' 조심 표시. 없거나 False여도 서버가 문장 낱말 규칙으로 다시 본다.
    safety_flag: bool | None = None

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
    steps: list[ConfirmedStep] | None = Field(default=None, min_length=1, max_length=MAX_CONFIRMED_STEPS)
    # 미리보기가 준 직무 제목·직무 추정값. steps와 함께 온다(없으면 기본값).
    title: str | None = Field(default=None, max_length=100)
    job: str | None = Field(default=None, max_length=50)

    @field_validator("raw_input")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("직무 내용을 입력해 주세요.")
        return v

    @model_validator(mode="after")
    def _confirmed_total(self) -> "TaskCreate":
        if self.steps and sum(len(s.sentence) for s in self.steps) > MAX_CONFIRMED_TOTAL:
            raise ValueError("단계 문장이 너무 길어요. 줄을 줄이거나 나눠 주세요.")
        return self


class StepUpdate(BaseModel):
    sentence: str | None = Field(default=None, max_length=500)
    symbol_url: str | None = Field(default=None, max_length=2000)
    # 검토 화면에서 AAC 후보를 직접 고른 경우 "LOCAL_AAC". 생략하면 기존처럼 fallback.
    symbol_source: Literal["LOCAL_AAC", "fallback"] | None = None
    # (2b-1) 조심 스위치. 보내면 source='manual'(같은 값이어도 — 사업주가 본 것이다).
    safety_flag: bool | None = None
    safety_note: str | None = Field(default=None, max_length=200)
    # (2b-1) 이 단계 앞에서 묶음을 나눈다(데이터만).
    group_break: bool | None = None
    # (2b-1) 600ms 자동 저장: 문장만 저장하고 음성은 만들지 않는다(tts_stale=1). 나누기 검사도 하지 않는다.
    defer_media: bool = False
    # (2b-1) 이 창이 마지막으로 본 직무 updated_at. 다르면 409(다른 창에서 먼저 고침). 없으면 검사하지 않는다.
    expected_updated_at: datetime | None = None

    @field_validator("sentence")
    @classmethod
    def _sentence_not_blank(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        if not v:
            raise ValueError("문장을 입력해 주세요.")
        return v


class PicturesConfirm(BaseModel):
    """그림 한눈에 보기의 [보이는 자동 그림 모두 맞아요]. 하나라도 확인할 수 없으면 아무것도 바꾸지 않는다."""
    step_ids: list[str] = Field(min_length=1, max_length=MAX_CONFIRMED_STEPS * 2)


class PictureApply(BaseModel):
    """후보·검색 결과 적용. card_id는 AAC 그림 id(그림 주소의 파일 이름과 같다)."""
    card_id: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=1, max_length=2000)
    label: str | None = Field(default=None, max_length=200)


class StepRewrite(BaseModel):
    """편집기에서 단계 문장을 고쳐 저장. 동작이 둘이면 서버가 두 단계로 나눈다(되돌리기 가능)."""
    sentence: str = Field(min_length=1, max_length=500)
    # (2b-1, 1회차 검증) 자동 저장(StepUpdate)과 같은 다른 창 검사. 다르면 409. 없으면 검사하지 않는다(옛 화면).
    expected_updated_at: datetime | None = None

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
    # 나누기 전 단계의 동작 종류(되돌리기가 원래 단계를 되살리도록 화면이 기억해 보낸다). 없으면 "other".
    action_type: str | None = Field(default=None, max_length=20)

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
    # 접속 코드는 근로자 로그인 키. 비워 두면 서버가 사업장 안에서 겹치지 않는 4자리 무작위 코드를 만든다
    # (창업자 결정 3: 근로자 키패드는 4자리를 누르면 바로 들어간다). 직접 정할 때는 4~12자리 숫자.
    # 4자리(1만 개)는 대입에 약하므로 로그인 시도 제한(ratelimit.py: IP·사업장 두 키)이 실제 방어선이다.
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
    # 근로자 화면 설정. 보낸 키만 병합한다(별도 /prefs 엔드포인트는 두지 않는다).
    a11y_prefs: A11yPrefsPatch | None = None


ConsentType = Literal["personal_info", "ai_processing"]


class ConsentCreate(BaseModel):
    """보호자·당사자에게서 받은 동의를 기록한다(동의서 원본은 사업장이 보관)."""
    consent_type: ConsentType
    subject: Literal["self", "guardian"] = "self"


class PerformanceLogCreate(BaseModel):
    assignment_id: str
    step_id: str
    # 기기 시계가 단계 중에 뒤로 가면(꺼진 채 켠 뒤 시각 맞춤 등) 음수가 올 수 있다. 예전에는 422였고 대기열은 422를
    # 버리므로 완료 기록이 영영 사라졌다(2차 검증). 검증 오류로 완료를 지우지 않게 0으로 자른다.
    duration_sec: float = 0.0
    replay_count: int = Field(default=0, ge=0)
    # '어려움 신호'(다시 듣기 과다·시간 초과)만 뜻한다. 도움 요청은 POST /api/worker/help로 따로 보낸다.
    stuck: bool = False
    # false면 신호만 남기고 완료로 세지 않는다.
    completed: bool = True
    @field_validator("duration_sec")
    @classmethod
    def _clamp_duration(cls, v: float) -> float:
        return v if v > 0 else 0.0

    # 오프라인 대기열 재전송 묶기 키. 같은 값이 다시 오면 아무것도 바꾸지 않고 200(duplicate)을 준다.
    client_event_id: str | None = Field(default=None, max_length=64)
    # 기기에서 단계를 끝낸 시각(시간대 포함 ISO). 서버가 범위를 자른다. 없으면 서버 시각.
    client_completed_at: datetime | None = None
    # 기기가 이 기록을 보낸 순간의 기기 시각(4차 검증). 서버는 (보낸 시각 - 끝낸 시각)으로 '몇 초 전에 끝냈는지'를
    # 같은 기기 시계끼리 재고, 서버 시각 기준의 완료 순간을 얻는다. 기기 시계가 서버와 달라도 도움 요청
    # (서버 시각 created_at)과 순서를 바르게 비교할 수 있다. 없으면 client_completed_at을 그대로 쓴다.
    client_sent_at: datetime | None = None
    # (2c, 0009) 이 단계에서 [이전]을 누른 수. 저장만 한다(타임라인·코칭 신호). 옛 기기는 보내지 않는다(0).
    prev_count: int = Field(default=0, ge=0, le=100000)

    @field_validator("client_completed_at", "client_sent_at")
    @classmethod
    def _drop_absurd_time(cls, v: datetime | None) -> datetime | None:
        # 4차 검증 2회: '0001-01-02'·'9999-12-31T23:00-09:00' 같은 값은 시간대 바꾸기·빼기에서 날짜가 넘쳐(OverflowError)
        # 500이 났고, 대기열은 5xx를 다시 보내므로 그 기록이 맨 앞에서 뒤 기록까지 막았다. 422로 거절하면 대기열이 완료
        # 기록을 버리므로(시계가 크게 망가진 기기의 진짜 완료가 사라진다) 거절하지 않고 '모르는 시각'(None)으로 본다.
        # 그러면 서버 시각을 쓴다. 전원이 나가 1970년으로 돌아간 기기 시계는 그대로 받는다.
        if v is not None and not (1900 <= v.year <= 2200):
            return None
        return v


class LogResultOut(BaseModel):
    ok: bool = True
    assignment_status: str
    duplicate: bool = False
    applied: bool = True


# --- 도움 요청(0006) ---
HelpState = Literal["open", "cancelled", "acknowledged", "resolved"]


class HelpCreate(BaseModel):
    assignment_id: str = Field(min_length=1, max_length=64)
    # 직무 시작·완료 화면에서 부르면 단계가 없다.
    step_id: str | None = Field(default=None, max_length=64)
    # 같은 누름의 재전송 묶기 키.
    client_request_id: str | None = Field(default=None, max_length=64)


class HelpOut(BaseModel):
    id: str
    assignment_id: str
    step_id: str | None
    step_order: int | None
    state: HelpState
    resolution: Literal["employer", "step_done"] | None
    created_at: datetime
    acknowledged_at: datetime | None
    cancelled_at: datetime | None
    resolved_at: datetime | None


class ActiveHelpOut(BaseModel):
    id: str
    state: HelpState
    step_id: str | None
    created_at: datetime


class EmployerHelpOut(BaseModel):
    """사업주 화면 도움 알림 띠의 한 줄."""
    id: str
    state: HelpState
    created_at: datetime
    acknowledged_at: datetime | None
    worker_id: str
    worker_name: str
    assignment_id: str
    task_id: str
    task_title: str
    step_id: str | None
    step_order: int | None
    step_sentence: str | None
    step_symbol_url: str | None
    # (2c) 버전을 넘어 같은 단계를 가리키는 키(편집기 ?step= 로 쓴다)와 띠의 단계 썸네일(지금은 그림 URL과 같다).
    source_step_id: str | None = None
    step_thumb_url: str | None = None


class AacSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    job: str | None = Field(default=None, max_length=40)
    limit: int = Field(default=5, ge=1, le=20)


# --- 응답 ---
# 그림 4상태(스펙 5.5): 확인함 / 자동(확인 필요) / 골라 주세요 / 그림 없음. main.picture_state가 정한다.
PictureState = Literal["confirmed", "auto_high", "choose", "none"]


# 근로자 화면이 읽는 단계 모양(today·history·도움). 사업주 편집기는 EditorStepOut(이것 + 편집 칸).
# 근로자 응답 스키마 스냅샷(test_versions) 때문에 설명은 docstring이 아니라 주석으로 둔다.
class StepOut(BaseModel):
    id: str
    order: int
    sentence: str
    action_type: str
    symbol_url: str | None
    symbol_source: str
    needs_fallback: bool
    tts_audio_url: str | None
    picture_state: PictureState = "none"
    # (2b-1) 근로자 화면 '조심해요' 띠(contract §3.5). source·note는 보내지 않는다.
    safety_flag: bool = False


# --- (2b-1) 편집기 단계 응답(contract §3.3) ---
PictureSource = Literal["auto", "manual", "photo"]


class PictureOut(BaseModel):
    # AAC 그림 id(그림 파일 이름) 또는 사진 media id.
    card_id: str
    url: str
    label: str = ""
    source: PictureSource


class CandidateOut(BaseModel):
    card_id: str
    url: str
    label: str = ""


class SplitOut(BaseModel):
    source: Literal["rule", "model", "manual", ""] = ""
    needs_review: bool = False
    original_span: str = ""


LintCode = Literal["too_long", "hard_word", "command_tone"]


class LintOut(BaseModel):
    # 화면 문구는 copy.ts가 만든다('20자가 넘어요', '어려운 말: 적재 → 쌓기', '~해요 체로 바꾸기').
    model_config = ConfigDict(populate_by_name=True)
    code: LintCode
    from_: str | None = Field(default=None, alias="from")
    to: str | None = None


class SafetyOut(BaseModel):
    flag: bool = False
    source: Literal["auto", "manual", ""] = ""
    note: str = ""


class EditorStepOut(StepOut):
    """사업주 편집기 단계. 확신 점수 숫자는 보내지 않는다. needs_fallback은 남기되 화면은 picture_state만 본다.

    candidates는 응답마다 다시 찾지 않는다(그림 검색이 단계마다 한 번씩 돈다) — 늘 빈 목록이고, 후보는
    GET /api/tasks/{id}/candidates가 모든 단계를 한 번에 돌려준다."""
    picture: PictureOut | None = None
    candidates: list[CandidateOut] = []
    split: SplitOut = SplitOut()
    lint: list[LintOut] = []
    safety: SafetyOut = SafetyOut()
    group_break: bool = False
    # 이 단계를 고친 뒤의 직무 updated_at(다음 자동 저장의 expected_updated_at으로 쓴다).
    task_updated_at: datetime | None = None


class StepCandidatesOut(BaseModel):
    step_id: str
    candidates: list[CandidateOut]


class TaskCandidatesOut(BaseModel):
    steps: list[StepCandidatesOut]


class TtsOut(BaseModel):
    # 합성하지 못했으면 None(근로자·사업주 기기의 음성 합성이 대신 읽는다).
    tts_url: str | None


class PreviewStepOut(StepOut):
    """미리보기(근로자 Step 모양 + 묶음 경계). picture_state는 지금 편집 단계의 실제 상태다(경고 배지용)."""
    group_break: bool = False


class PreviewOut(BaseModel):
    title: str
    steps: list[PreviewStepOut]


class TaskVersionInfoOut(BaseModel):
    """(2a-0) 보낸 버전 정보. current_no: 마지막으로 보낸 버전 번호(보낸 적 없으면 None)."""
    current_no: int | None = None
    # 보낸 뒤 고친 내용이 있는지(versions.same_content로 지금 단계와 마지막 버전을 비교).
    has_unsent_changes: bool = False


class TaskOut(BaseModel):
    id: str
    title: str
    status: str
    steps: list[EditorStepOut]
    # (2a-0) 아래는 더한 칸이다(옛 화면은 무시해도 된다).
    version: TaskVersionInfoOut | None = None
    # 오늘 배정 중 하는 중(완료 단계 1개 이상, 다 하지 않음)인 수.
    in_progress_count: int = 0
    # 이 직무를 받은 적 있는 근로자 수.
    recipients_count: int = 0
    updated_at: datetime | None = None


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
    # (2b-1) '✦ 자동 제안' 조심 표시(ai_service safety_flags 또는 낱말 규칙). [이대로 그림 고르기]가 그대로 돌려보낸다.
    safety_flag: bool = False


class SplitPreviewOut(BaseModel):
    task_title: str
    job: str = ""
    steps: list[SplitPreviewStep]


class StepAddOut(TaskOut):
    """단계 추가 결과(직무 전체). 새 문장에 동작이 둘이라 두 단계로 나눠 넣었으면 그 id들(되돌리기용)."""
    split_step_ids: list[str] = []
    sentence: str = ""


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
    # (2a-1) 보관함에 있는지. 옛 대시보드(/m)가 보관한 직무에 [보관하기]를 다시 띄우지 않으려고 더한다(필드 추가만).
    archived: bool = False


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
    # 근로자 화면 설정(8개 키 모두).
    a11y_prefs: A11yPrefs = Field(default_factory=A11yPrefs)


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
    # 아래는 0006에서 더한 표시용 필드(기존 화면은 무시해도 된다).
    # new(완료 기록 0) / in_progress(1개 이상, 배정 미완료) / done(배정 done). 배정 테이블 값과 별개다.
    status: Literal["new", "in_progress", "done"] = "new"
    # 이 배정에서 끝낸 단계 id(지금 직무에 있는 단계만, 단계 순서대로).
    done_step_ids: list[str] = []
    # 이어서 할 단계 인덱스(0부터). 모두 했으면 len(steps).
    resume_step_index: int = 0
    # 배열에서 done이 아닌 첫 카드만 true(창업자 결정 7: 사업주 순서, 다음 카드 강조).
    is_next: bool = False
    assigned_at: datetime | None = None
    completed_at: datetime | None = None
    # 열린(open/acknowledged) 도움 요청 중 최신 1건. 새로고침 뒤 도움 띠 복원용.
    active_help: ActiveHelpOut | None = None
    # (2a-0) 이 배정이 고정된 버전 번호. 근로자 화면은 쓰지 않는다(사업주 쪽·디버깅용).
    task_version_no: int | None = None


class HistoryStepOut(StepOut):
    completed: bool


class HistoryCardOut(BaseModel):
    """근로자 본인이 지난번에 받았던 일 — 완료 후에도 다시 열어 볼 수 있게 한다."""
    assignment_id: str
    task_id: str
    task_title: str
    # YYYY-MM-DD, 근로자 현지 기준(APP_UTC_OFFSET_HOURS). (2a-0) 배정의 scheduled_day(그 일을 하는 날)다.
    assigned_date: str
    status: str
    steps: list[HistoryStepOut]
    # (2a-0) 이 배정이 고정된 버전 번호. 근로자 화면은 쓰지 않는다.
    task_version_no: int | None = None


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


# --- (2a-0) 보내기: 서버 검사·보내기·받는 사람 (contract §1.4) ---
SendBlockCode = Literal["no_picture", "unconfirmed_auto", "unreviewed_split", "no_steps", "archived"]
SendWarnCode = Literal["too_long", "command_tone", "auto_caution"]
SendOutcome = Literal["created", "repinned", "unchanged", "kept", "kept_in_progress"]


class SendBlockOut(BaseModel):
    """막는 항목. 화면 문구는 사업주 화면 copy.ts가 code와 숫자로 만든다(서버는 label을 보내지 않는다).
    done/total: 이 항목을 통과한 단계 수/살펴본 단계 수. total=0인 줄은 화면에 보이지 않는다."""
    code: SendBlockCode
    done: int
    total: int
    step_ids: list[str] = []


class SendWarnOut(BaseModel):
    """막지 않는 경고(2b-1부터 채운다)."""
    code: SendWarnCode
    count: int
    step_ids: list[str] = []


class SendCheckOut(BaseModel):
    ok: bool
    blocking: list[SendBlockOut]
    warnings: list[SendWarnOut]


class SendRequest(BaseModel):
    # 빈 목록은 send.py가 한국어 422로 막는다(검증 오류 문구보다 다음 할 일을 알려 주려고 기본값을 둔다).
    worker_ids: list[str] = Field(default_factory=list, max_length=200)
    # "today" | "tomorrow" | "YYYY-MM-DD"(현지 날짜)
    day: str = Field(default="today", max_length=20)


class SendResultItemOut(BaseModel):
    worker_id: str
    display_name: str
    outcome: SendOutcome


class SendResultOut(BaseModel):
    version_no: int
    version_created: bool
    day: str  # YYYY-MM-DD
    results: list[SendResultItemOut]


class RecipientsOut(BaseModel):
    last_batch_worker_ids: list[str]
    all_ever_worker_ids: list[str]
    workplace_last_batch_worker_ids: list[str]
    # 이 직무의 오늘 배정 상태: none | not_started | in_progress | done
    today_status: dict[str, Literal["none", "not_started", "in_progress", "done"]]


# --- 2a-1 직무 목록(contract §2.1) -------------------------------------------------------------
# 옛 GET /api/tasks의 TaskSummaryOut(배열)은 2d까지 그대로 두므로, 새 목록 행은 이름을 달리한다.
# 화면 타입 이름은 frontend/src/manager/api/types.ts의 TaskSummaryOut이다(필드는 같다).

TaskFilter = Literal["all", "draft", "needs_check", "published", "archived"]


class TaskRecipientOut(BaseModel):
    worker_id: str
    # 이름 앞 글자(아바타). 실명 전체는 목록에 싣지 않는다.
    initials: str


class EmployerTaskSummaryOut(BaseModel):
    id: str
    title: str
    state: Literal["draft", "published", "archived"]
    # 보내기 전에 사업주가 봐야 할 단계 수(그림 없음 + 확인 안 한 자동 그림 = 보내기 검사가 막는 단계).
    needs_check_count: int
    # 보낸 뒤 고쳤지만 아직 다시 보내지 않음(versions.same_content).
    has_unsent_changes: bool
    step_count: int
    cover_url: str | None = None
    recipients: list[TaskRecipientOut]
    recipients_more: int
    updated_at: datetime
    current_version_no: int | None = None


class TaskCountsOut(BaseModel):
    all: int
    draft: int
    needs_check: int
    published: int
    archived: int


class EmployerTaskListOut(BaseModel):
    items: list[EmployerTaskSummaryOut]
    counts: TaskCountsOut


class TaskTitleUpdate(BaseModel):
    # 길이·글자 종류 검사는 task_list.py가 한국어 422로 한다(검증 오류 기본 문구보다 다음 할 일을 알려 주려고).
    # 글자가 아닌 값(숫자 등)도 같은 문구로 막으려고 Any로 받는다.
    title: Any = None


# --- 2c 오늘 현황과 도움 (contract §5) -------------------------------------------------------

def _device_time(value) -> datetime | None:
    """기기 시각: 읽지 못하는 값·엉터리 연도는 '모르는 시각'(None)으로 본다(422·500 대신 서버 시각을 쓴다)."""
    if value is None:
        return None
    try:
        v = TypeAdapter(datetime).validate_python(value)
    except (ValidationError, TypeError, ValueError):
        return None
    return v if 1900 <= v.year <= 2200 else None


class PresenceIn(BaseModel):
    """근로자 기기가 지금 보는 단계(POST /api/worker/presence → 204)."""
    assignment_id: str = Field(min_length=1, max_length=64)
    # 직무 시작·완료 화면이면 null.
    step_id: str | None = Field(default=None, max_length=64)
    # 기기 시계로 이 단계를 연 시각과 이 신호를 보낸 시각. 서버는 둘의 차이만 쓴다(시계가 틀려도 머문 시간은 맞다).
    step_started_at: Any = None
    client_sent_at: Any = None
    replay_count: int = Field(default=0, ge=0, le=100000)
    prev_count: int = Field(default=0, ge=0, le=100000)

    @field_validator("step_started_at", "client_sent_at", mode="before")
    @classmethod
    def _times(cls, value):
        return _device_time(value)


Badge = Literal["help", "help_acked", "offline", "stuck_suspect", "in_progress", "new", "done", "idle"]


class LiveStepOut(BaseModel):
    id: str
    source_step_id: str | None
    order: int
    sentence: str
    thumb_url: str | None


class LiveCurrentOut(BaseModel):
    assignment_id: str
    task_id: str
    task_title: str
    version_no: int | None
    done: int
    total: int
    step: LiveStepOut | None


class LiveTodayOut(BaseModel):
    assignment_id: str
    task_title: str
    status: Literal["new", "in_progress", "done"]
    is_next: bool


class LiveWorkerOut(BaseModel):
    worker_id: str
    display_name: str
    initials: str
    badge: Badge
    last_activity_at: datetime | None
    last_signal_at: datetime | None
    current: LiveCurrentOut | None
    today: list[LiveTodayOut]


class LiveSummaryOut(BaseModel):
    working: int
    total_workers: int
    open_help: int
    stuck_steps: int
    needs_check_tasks: int


class LiveOut(BaseModel):
    server_now: datetime
    summary: LiveSummaryOut
    workers: list[LiveWorkerOut]
    help: list[EmployerHelpOut]


class TimelineStepOut(BaseModel):
    step_id: str
    source_step_id: str | None
    order: int
    sentence: str
    thumb_url: str | None
    completed: bool
    completed_at: datetime | None
    duration_sec: float | None
    replay_count: int
    prev_count: int
    help_count: int


class TimelineAssignmentOut(BaseModel):
    assignment_id: str
    task_id: str
    task_title: str
    version_no: int | None
    status: Literal["new", "in_progress", "done"]
    assigned_at: datetime
    steps: list[TimelineStepOut]


class TimelineEventOut(BaseModel):
    at: datetime
    kind: Literal["step_done", "help_open", "help_ack", "help_resolved", "help_cancelled"]
    assignment_id: str
    step_order: int | None


class TimelineOut(BaseModel):
    worker_id: str
    display_name: str
    date: str
    assignments: list[TimelineAssignmentOut]
    events: list[TimelineEventOut]


class CoachingSignalsOut(BaseModel):
    replay_avg: float
    duration_avg_sec: float
    help_count: int
    runs: int


class CoachingAfterOut(CoachingSignalsOut):
    # 고친 내용을 처음 보낸 버전 번호(그 버전부터의 기록만 셈).
    since_version_no: int


class CoachingCardOut(BaseModel):
    task_id: str
    task_title: str
    source_step_id: str
    step_id: str | None
    sentence: str
    thumb_url: str | None
    signals: CoachingSignalsOut
    suggestion: Literal["photo", "split", "easy_words"]
    after: CoachingAfterOut | None


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    task_id: str | None = Field(default=None, max_length=64)
    step_id: str | None = Field(default=None, max_length=64)
    value_num: float | None = Field(default=None, ge=-1e9, le=1e9)
    at: Any = None

    @field_validator("at", mode="before")
    @classmethod
    def _at(cls, value):
        return _device_time(value)


class EventsIn(BaseModel):
    events: list[EventIn] = Field(min_length=1, max_length=50)


class PushKeysIn(BaseModel):
    p256dh: str = Field(min_length=1, max_length=256)
    auth: str = Field(min_length=1, max_length=128)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)
    keys: PushKeysIn


class PushUnsubscribeIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=2048)


class PushConfigOut(BaseModel):
    enabled: bool
    public_key: str | None
