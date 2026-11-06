"""ORM 모델.

엔티티: Employer, Worker, Task, Step, Assignment, PerformanceLog.
변경점(평가 반영):
- Employer.login_id/password_hash, Worker.access_code 추가 → 인증 가능
- 모든 FK에 index=True (조회 성능)
- PerformanceLog(assignment_id, step_id) UNIQUE → 단계당 1로그 보장(업서트)
- 미사용 SymbolAsset 테이블 제거(死 코드 정리). 자체 상징 DB는 도입 시점에 재설계한다.
- (0002) Employer.workplace_code 추가, Worker.access_code 평문 → access_code_hash(+힌트·길이).
  접속 코드는 사업장 안에서만 unique다(교차 테넌트 코드 오라클 제거).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from auth import hash_access_code
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
    # 평문은 저장하지 않는다 — HMAC(JOBCARD_SECRET, "employer_id:code")만 둔다(auth.hash_access_code).
    # 평문은 생성·재발급 응답에서 딱 한 번만 사업주에게 보여 준다.
    access_code_hash: Mapped[str] = mapped_column(String)
    # 사업주 화면에서 "어느 코드였는지" 알아보는 용도의 뒤 2자리와, 짧은(4~5자리) 예전 코드 경고용 길이.
    access_code_hint: Mapped[str] = mapped_column(String, default="")
    access_code_length: Mapped[int] = mapped_column(Integer, default=0)
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
    symbol_url: Mapped[str | None] = mapped_column(String, nullable=True)
    symbol_source: Mapped[str] = mapped_column(String, default="fallback")
    needs_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    tts_audio_url: Mapped[str | None] = mapped_column(String, nullable=True)

    task: Mapped["Task"] = relationship(back_populates="steps")


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    worker_id: Mapped[str] = mapped_column(ForeignKey("workers.id"), index=True)
    assigned_date: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
    status: Mapped[str] = mapped_column(String, default="assigned")


class PerformanceLog(Base):
    __tablename__ = "performance_logs"
    __table_args__ = (
        UniqueConstraint("assignment_id", "step_id", name="uq_log_assignment_step"),
    )
    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    assignment_id: Mapped[str] = mapped_column(ForeignKey("assignments.id"), index=True)
    step_id: Mapped[str] = mapped_column(ForeignKey("steps.id"), index=True)
    completed_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    replay_count: Mapped[int] = mapped_column(Integer, default=0)
    stuck: Mapped[bool] = mapped_column(Boolean, default=False)
