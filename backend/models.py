"""ORM 모델.

엔티티: Employer, Worker, Task, Step, Assignment, PerformanceLog.
변경점(평가 반영):
- Employer.login_id/password_hash, Worker.access_code 추가 → 인증 가능
- 모든 FK에 index=True (조회 성능)
- PerformanceLog(assignment_id, step_id) UNIQUE → 단계당 1로그 보장(업서트)
- 미사용 SymbolAsset 테이블 제거(死 코드 정리). 자체 상징 DB는 도입 시점에 재설계한다.
- (0002) Employer.workplace_code 추가, Worker.access_code 평문 → access_code_hash(+힌트·길이).
  접속 코드는 사업장 안에서만 unique다(교차 테넌트 코드 오라클 제거).
- (0003) Worker.note/ai_note_allowed, WorkerConsent(동의 기록), AccessAuditLog(접근 감사, append-only).
  개인정보 보호(Phase 0.2) — docs/privacy/data-map.md 참고.
- (0004) MediaFile(사진·TTS 소유 레코드), Step.symbol_media_id/tts_media_id, Step.tts_audio_url 제거.
  파일은 단기 서명 URL로만 나간다(media.py). DB에는 URL이 아니라 media id와 상대 키만 둔다.
- (0006) 근로자 화면 0·1차: Step.picture_confirmed(사업주가 그림을 확인함), PerformanceLog.completed·client_event_id
  (어려움 신호와 완료를 나누고 오프라인 재전송을 묶는다), Worker.a11y_prefs·last_seen_at, HelpRequest(도움 요청).
  예전에는 [도와주세요]가 stuck=true 수행 로그로 저장돼, 마지막 단계에서 도움만 눌러도 직무가 '다 함'이 됐다.
- (0007) 버전 고정: TaskVersion·TaskVersionStep(보낼 때 steps를 복사한 스냅샷). 배정은 task_version_id로 버전을
  가리키고, 근로자 화면·완료 판정·도움·대시보드·내보내기는 그 버전 단계를 읽는다. steps는 사업주 편집 작업면이다.
  수행 로그·도움 요청의 step_id는 버전 단계 id다(편집으로 지워지지 않는다). 배정의 '그 날'은 scheduled_day(현지 날짜).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    inspect as sa_inspect,
    text,
)
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

import clock
from auth import encrypt_access_code, hash_access_code
from codes import new_workplace_code
from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Employer(Base):
    __tablename__ = "employers"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String, default="")
    org_name: Mapped[str] = mapped_column(String, default="")
    login_id: Mapped[str] = mapped_column(String, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, default="")
    # 근로자 로그인용 사업장 식별자(codes.py). 서버가 만들고 사업주 화면에 보여 준다.
    # 근로자 접속 코드는 사업장 안에서만 unique이므로, 로그인은 이 코드로 사업장을 먼저 정한다.
    workplace_code: Mapped[str] = mapped_column(String, unique=True, index=True,
                                                default=new_workplace_code)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    tasks: Mapped[list["Task"]] = relationship(back_populates="employer")
    workers: Mapped[list["Worker"]] = relationship(back_populates="employer")


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (
        # 접속 코드는 사업장 안에서만 겹치지 않으면 된다. 예전처럼 전역 unique면 다른 사업장이
        # 같은 코드를 못 쓰고, 그 "못 씀"(409)이 남의 사업장 코드를 알려 주는 오라클이 됐다.
        UniqueConstraint("employer_id", "access_code_hash", name="uq_worker_employer_code"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    employer_id: Mapped[str] = mapped_column(ForeignKey("employers.id"), index=True)
    display_name: Mapped[str] = mapped_column(String, default="근로자")
    # 발달장애인 근로자는 비밀번호 대신 짧은 접속 코드로 로그인한다(현장 디바이스 공유 가정).
    # 평문은 저장하지 않는다 — 로그인 조회용 HMAC(JOBCARD_SECRET, "employer_id:code")(auth.hash_access_code)과
    # 사업주 화면 표시용 암호문(access_code_cipher)만 둔다. 둘 다 시크릿 없이 DB만으로는 코드를 알 수 없다.
    access_code_hash: Mapped[str] = mapped_column(String)
    # 사업주 화면에서 "어느 코드였는지" 알아보는 용도의 뒤 2자리와, 짧은(4~5자리) 예전 코드 경고용 길이.
    access_code_hint: Mapped[str] = mapped_column(String, default="")
    access_code_length: Mapped[int] = mapped_column(Integer, default=0)
    # 사업주 화면에 전체 코드를 보여 주기 위한 암호문(auth.encrypt_access_code, 0005). 로그인은 여전히 해시로 한다.
    # 0005 이전에 만든 근로자는 평문을 알 수 없어 비어 있다 — 그 근로자가 다음에 로그인하거나 코드를 재발급하면 채워진다.
    access_code_cipher: Mapped[str | None] = mapped_column(String, nullable=True)
    # 사업주가 적어 두는 근로자 특성 메모(예: "그림을 선호함"). 장애 특성 같은 민감한 내용이 들어가기 쉬워
    # 기본으로는 AI(해외 LLM)에 보내지 않는다. ai_note_allowed를 사업주가 켜고, 근로자(또는 보호자)의
    # AI 처리 동의(WorkerConsent)가 살아 있을 때만 보낸다(main._sendable_note).
    note: Mapped[str] = mapped_column(Text, default="", server_default="")
    ai_note_allowed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # (0006) 근로자 화면 설정(JSON 문자열). 빈 객체 = 모두 기본값. 읽을 때 모르는 키·잘못된 값은 기본값으로
    # 바꾼다(schemas.parse_a11y_prefs). 소리 자동 재생은 기본 켬(창업자 결정 4), 근로자마다 끌 수 있다.
    a11y_prefs: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    # (0006) 근로자 기기가 마지막으로 오늘 할 일을 불러온 시각(UTC). 2차 '연결 끊김' 표시용.
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    employer: Mapped["Employer"] = relationship(back_populates="workers")

    def set_access_code(self, code: str) -> None:
        """평문 코드를 받아 해시·힌트·길이를 채운다. employer_id가 먼저 정해져 있어야 한다
        (해시에 사업장 id가 섞이므로, 없으면 엉뚱한 사업장 기준 해시가 된다)."""
        if not self.employer_id:
            raise ValueError("employer_id를 먼저 정해야 접속 코드를 해시할 수 있습니다.")
        self.access_code_hash = hash_access_code(self.employer_id, code)
        self.access_code_hint = code[-2:]
        self.access_code_length = len(code)
        self.access_code_cipher = encrypt_access_code(self.employer_id, code)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    employer_id: Mapped[str] = mapped_column(ForeignKey("employers.id"), index=True)
    title: Mapped[str] = mapped_column(String, default="")
    raw_input: Mapped[str] = mapped_column(Text, default="")
    # 직무 생성 시 사업주가 입력한 현장 맥락. AAC 검색이 업종을 추론하는 데 쓴다.
    # 저장하지 않으면 나중에(검토 화면 후보 조회, 단계 직접 추가) 같은 조건으로
    # 재검색할 수 없어, 생성 시 판정과 후보 목록이 어긋난다.
    business_type: Mapped[str] = mapped_column(String, default="")
    work_environment: Mapped[str] = mapped_column(String, default="")
    # LLM이 생성한 canonical job. 직무 생성 시에만 사용되며, 이후에는 변경되지 않는다.
    job: Mapped[str] = mapped_column(String, default="")

    # draft -> published -> archived
    status: Mapped[str] = mapped_column(String, default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # (0007) 마지막으로 보낸 버전(TaskVersion.id). 보낸 적 없으면 NULL. tasks와 task_versions가 서로 FK를 걸면
    # 표 만들기·지우기 순서가 꼬여서 FK 없이 둔다(직무를 지울 때 버전도 함께 지운다).
    current_version_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # (0007) 사업주가 마지막으로 고친 시각(단계 변경·제목 변경 때 아래 before_flush가 갱신). 백필 = created_at.
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # (0007) 보관한 시각(2a-1부터 씀).
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    employer: Mapped["Employer"] = relationship(back_populates="tasks")
    steps: Mapped[list["Step"]] = relationship(
        back_populates="task", order_by="Step.order_index",
        cascade="all, delete-orphan",
    )


class Step(Base):
    __tablename__ = "steps"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    sentence: Mapped[str] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(String, default="other")
    # LLM 분해가 준 구체 명사(["바닥","floor"] 등). 직무 생성 시 AAC 검색에 쓴 질의를
    # 그대로 저장한다. 검토 화면에서 후보를 다시 조회할 때 같은 질의를 써야 판정이
    # 어긋나지 않는다(안 그러면 "생성 땐 그림 없음, 후보 조회 땐 매칭 있음"이 된다).
    # 문장을 수정하면 이 값은 무의미해지므로 update_step 에서 비운다.
    symbol_query: Mapped[str] = mapped_column(Text, default="")  # "," 로 이은 문자열
    # 자체 AAC 그림(공개 자산)의 URL. 사업주가 올린 사진은 여기 두지 않고 symbol_media_id로 가리킨다.
    symbol_url: Mapped[str | None] = mapped_column(String, nullable=True)
    symbol_source: Mapped[str] = mapped_column(String, default="fallback")
    needs_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    # (0004) 사진·TTS는 소유 레코드(MediaFile)로 가리킨다. 응답 시점에 단기 서명 URL로 바꾼다(main._step_to_out).
    # 예전처럼 절대 URL을 저장하면 서버 주소가 바뀔 때 깨지고, URL만 알면 누구나 받을 수 있었다.
    symbol_media_id: Mapped[str | None] = mapped_column(ForeignKey("media_files.id"), nullable=True,
                                                        index=True)
    tts_media_id: Mapped[str | None] = mapped_column(ForeignKey("media_files.id"), nullable=True,
                                                     index=True)
    # (0006) 사업주가 이 그림을 직접 고르거나 올리거나 확인했는지. 그림 4상태(main.picture_state)의 '확인함'.
    # 문장만 고치면 그대로 두고, 사진을 지우거나 사진이 사라지면 False로 되돌린다.
    picture_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    task: Mapped["Task"] = relationship(back_populates="steps")
    # 레코드가 GC로 지워졌으면 None이 된다 — 응답은 그림/음성 없음으로 나가고,
    # 근로자 화면은 브라우저 음성합성으로 대신한다.
    symbol_media: Mapped["MediaFile | None"] = relationship(foreign_keys=[symbol_media_id], lazy="selectin")
    tts_media: Mapped["MediaFile | None"] = relationship(foreign_keys=[tts_media_id], lazy="selectin")


class TaskVersion(Base):
    """(0007) 보낼 때 만든 직무 스냅샷. 같은 내용을 다시 보내면 새로 만들지 않는다(versions.same_content)."""
    __tablename__ = "task_versions"
    __table_args__ = (UniqueConstraint("task_id", "version_no", name="uq_task_versions_task_no"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    # 보낸 사업주 id(백필은 직무의 사업주).
    created_by: Mapped[str | None] = mapped_column(String, nullable=True)

    steps: Mapped[list["TaskVersionStep"]] = relationship(
        back_populates="version", order_by="TaskVersionStep.order_index",
        cascade="all, delete-orphan",
    )


class TaskVersionStep(Base):
    """(0007) 버전에 고정된 단계. 수행 로그·도움 요청은 이 id를 가리킨다.

    백필한 버전 1의 단계 id는 원래 steps.id와 같다(근로자 기기의 옛 대기열이 그대로 맞는다). 그 뒤 버전은 새 uuid다.
    source_step_id: 복사해 온 steps.id(버전을 넘어 같은 단계로 묶는 키). FK 없음 — 원래 단계는 지워질 수 있다.
    사진·음성은 편집 단계와 같은 MediaFile 레코드를 가리킨다. media._unreferenced가 이 표의 참조도 세므로
    편집기에서 사진을 바꿔도 지금 일하는 근로자의 사진은 남는다.
    """
    __tablename__ = "task_version_steps"
    __table_args__ = (UniqueConstraint("version_id", "order_index", name="uq_task_version_steps_order"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    version_id: Mapped[str] = mapped_column(ForeignKey("task_versions.id"), index=True)
    source_step_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    order_index: Mapped[int] = mapped_column(Integer)
    sentence: Mapped[str] = mapped_column(Text)
    action_type: Mapped[str] = mapped_column(String, default="other")
    symbol_query: Mapped[str] = mapped_column(Text, default="")
    symbol_url: Mapped[str | None] = mapped_column(String, nullable=True)
    symbol_source: Mapped[str] = mapped_column(String, default="fallback")
    symbol_media_id: Mapped[str | None] = mapped_column(ForeignKey("media_files.id"), nullable=True,
                                                        index=True)
    tts_media_id: Mapped[str | None] = mapped_column(ForeignKey("media_files.id"), nullable=True,
                                                     index=True)

    version: Mapped["TaskVersion"] = relationship(back_populates="steps")
    symbol_media: Mapped["MediaFile | None"] = relationship(foreign_keys=[symbol_media_id], lazy="selectin")
    tts_media: Mapped["MediaFile | None"] = relationship(foreign_keys=[tts_media_id], lazy="selectin")


class MediaFile(Base):
    """사업주 소유 파일(업로드 사진·서버 합성 TTS mp3)의 레코드 (Phase 0.3).

    - 파일은 kind별 디렉터리(PHOTO_DIR / TTS_CACHE_DIR) 아래 storage_key(상대 키, "<32hex>.<ext>")에 있다.
      절대 경로·URL은 저장하지 않는다 — 디렉터리나 서버 주소가 바뀌어도 레코드는 그대로 쓸 수 있다.
    - 이 레코드가 있어야 서명 URL을 만들 수 있고(media.signed_url), 단계에 붙일 수 있다(employer_id 일치).
    - 같은 storage_key를 여러 레코드가 가리킬 수 있다(같은 사업장의 같은 문장 TTS, 0004 이전부터 공유되던 파일).
      파일은 그 키를 가리키는 레코드가 하나도 없을 때만 지운다(media.release / media.gc).
    """
    __tablename__ = "media_files"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    employer_id: Mapped[str] = mapped_column(ForeignKey("employers.id"), index=True)
    kind: Mapped[str] = mapped_column(String)  # "photo" | "tts"
    storage_key: Mapped[str] = mapped_column(String, index=True)
    sha256: Mapped[str] = mapped_column(String, default="")
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        # 근로자 '오늘 할 일'(worker_id + scheduled_day)과 배정 규칙(같은 근로자·직무·날)의 조회.
        Index("ix_assignments_worker_day", "worker_id", "scheduled_day"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    # 보낸 시각(UTC). 사업주가 보낸 순서(결정 7) 정렬·완료 시각 하한·assigned_at 표시에만 쓴다. 날짜는 scheduled_day.
    assigned_date: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    status: Mapped[str] = mapped_column(String, default="assigned")
    # (0007) 고정된 버전. NULL이면(백필이 못 채움) versions.assignment_steps가 task.steps로 대신 읽고 경고를 남긴다.
    task_version_id: Mapped[str | None] = mapped_column(ForeignKey("task_versions.id"), nullable=True,
                                                        index=True)
    # (0007) 한 번의 보내기 묶음. 시각 순으로 정렬되는 문자열(send.new_batch_id) — 가장 큰 값이 마지막 보내기.
    send_batch_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    # (0007) 근로자가 이 일을 하는 현지 날짜(KST). today·history·대시보드의 '그 날'.
    scheduled_day: Mapped[date] = mapped_column(Date, default=clock.local_today)
    # (0007) 이 배정이 지금 버전에 묶인 시각(다시 보내기로 옮기면 갱신).
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # (0007) 근로자 기기가 이 배정을 처음 받은 시각(/me/today가 한 번 씀). 받은 뒤에는 다시 보내도 옮기지 않는다.
    first_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PerformanceLog(Base):
    __tablename__ = "performance_logs"
    __table_args__ = (
        UniqueConstraint("assignment_id", "step_id", name="uq_log_assignment_step"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), index=True)
    # (0007) 버전 단계 id. 편집으로 steps가 지워져도 기록은 남는다.
    step_id: Mapped[str] = mapped_column(ForeignKey("task_version_steps.id"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    replay_count: Mapped[int] = mapped_column(Integer, default=0)
    stuck: Mapped[bool] = mapped_column(Boolean, default=False)
    # (0006) stuck은 이제 '어려움 신호'(다시 듣기 과다·시간 초과)만 뜻한다. completed=False 행은 신호만 남기고
    # 완료로 세지 않는다. 0006 이전 행은 완료로 본다(server_default 1). 도움 요청은 HelpRequest에 따로 둔다.
    completed: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # 근로자 기기 오프라인 대기열의 재전송 묶기 키. 같은 값이 다시 오면 아무것도 바꾸지 않는다.
    client_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class HelpRequest(Base):
    """근로자의 [도와주세요] 요청(0006).

    상태: open → acknowledged(사업주 [확인했어요]) → resolved(사업주 [도와줬어요] 또는 근로자 [다 했어요]),
    open/acknowledged → cancelled(근로자 [취소]). cancelled·resolved는 끝 상태다.
    수행 로그와 따로 두어, 도움 요청이 단계 완료로 세지지 않게 한다.
    """
    __tablename__ = "help_requests"
    __table_args__ = (
        Index("ix_help_requests_assignment_state", "assignment_id", "state"),
        # 같은 누름(client_request_id)은 한 건, 배정마다 열린 요청(open·acknowledged)은 한 건(2차 검증: 동시 요청이
        # 확인과 저장 사이에 겹쳐 두 건이 생겼다). NULL 키는 서로 다른 값으로 본다(SQLite·PostgreSQL 모두).
        Index("uq_help_requests_assignment_client", "assignment_id", "client_request_id", unique=True),
        Index("uq_help_requests_one_active", "assignment_id", unique=True,
              sqlite_where=text("state IN ('open', 'acknowledged')"),
              postgresql_where=text("state IN ('open', 'acknowledged')")),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    employer_id: Mapped[str] = mapped_column(ForeignKey("employers.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), index=True)
    # (0007) 버전 단계 id. 직무 시작·완료 화면에서 부르면 처음부터 NULL. 편집으로 지워지지 않는다.
    step_id: Mapped[str | None] = mapped_column(ForeignKey("task_version_steps.id"), nullable=True,
                                                index=True)
    state: Mapped[str] = mapped_column(String, default="open")
    # employer(사업주 [도와줬어요]) | step_done(근로자가 [다 했어요])
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WorkerConsent(Base):
    """근로자(또는 보호자)에게서 받은 동의 기록.

    동의서 원본은 종이로 받는 경우가 많아, 서버에는 "누가(사업주) 언제 어떤 방침 버전으로 받았는지"만 남긴다.
    철회는 행을 지우지 않고 revoked_at을 채운다 — 언제까지 동의가 유효했는지가 나중에 근거가 된다.
    근로자를 삭제하면 이 기록도 함께 지운다(근로자를 식별하는 정보와 같이 묶여 있으므로).
    """
    __tablename__ = "worker_consents"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    # privacy.CONSENT_TYPES 중 하나. ai_processing이 있어야 AI 코칭(해외 LLM 전송) 대상이 된다.
    consent_type: Mapped[str] = mapped_column(String)
    # 동의한 사람: self(당사자) / guardian(보호자·법정대리인).
    subject: Mapped[str] = mapped_column(String, default="self")
    policy_version: Mapped[str] = mapped_column(String)
    granted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 동의 수령을 기록한 사업주 id.
    recorded_by: Mapped[str] = mapped_column(ForeignKey("employers.id"), index=True)


class AccessAuditLog(Base):
    """사업주가 근로자 개인 데이터를 열람·내보내기·삭제한 기록(append-only).

    - 앱 코드에는 수정·삭제 경로가 없다. 아래 매퍼 이벤트가 ORM 수정·삭제를 막고, 행을 지우는 곳은
      보존기간 purge(retention.py) 하나뿐이다(Core delete는 매퍼 이벤트를 거치지 않는다).
    - worker_id에 FK를 걸지 않는다. 근로자를 삭제해도 "누가 언제 그 근로자 데이터를 봤는지"는
      보존기간 동안 남아야 하기 때문이다. 대신 이름 등 식별 정보는 담지 않는다(id만).
    """
    __tablename__ = "access_audit_logs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    actor_id: Mapped[str] = mapped_column(String, index=True)
    actor_role: Mapped[str] = mapped_column(String, default="employer")
    action: Mapped[str] = mapped_column(String)
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    request_ip: Mapped[str] = mapped_column(String, default="")


def _reject_audit_mutation(_mapper, _connection, _target) -> None:
    raise PermissionError("접근 감사 로그는 고치거나 지울 수 없습니다(보존기간 purge만 허용).")


event.listen(AccessAuditLog, "before_update", _reject_audit_mutation)
event.listen(AccessAuditLog, "before_delete", _reject_audit_mutation)


def _touch_task_updated_at(session: Session, _flush_context, _instances) -> None:
    """단계를 더하거나 고치거나 지우면, 또는 제목을 바꾸면 그 직무의 updated_at(목록의 '고친 날')을 갱신한다.

    단계 편집 함수마다 적으면 빠뜨리기 쉬워 flush 한 곳에서 한다. 보내기(status·current_version_id)는 고친 것이 아니다.
    """
    task_ids: set[str] = set()
    for obj in list(session.new) + list(session.dirty) + list(session.deleted):
        if isinstance(obj, Step) and obj.task_id:
            if obj in session.dirty and not session.is_modified(obj):
                continue
            task_ids.add(obj.task_id)
        elif isinstance(obj, Task) and obj in session.dirty and obj not in session.new:
            if sa_inspect(obj).attrs.title.history.has_changes():
                task_ids.add(obj.id)
    if not task_ids:
        return
    now = _now()
    with session.no_autoflush:
        for tid in task_ids:
            task = session.get(Task, tid)
            if task is not None and task not in session.deleted:
                task.updated_at = now


event.listen(Session, "before_flush", _touch_task_updated_at)
